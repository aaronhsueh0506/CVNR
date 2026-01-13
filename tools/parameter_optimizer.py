#!/usr/bin/env python3
"""
SPP 參數優化器

針對使用 SPP 的 denoiser 進行參數搜索優化：
- V3 (SPP-MMSE)
- V3-2 (MMSE-LSA)
- V3-3 (PMMSE)
- V3-4 (Laplacian-MMSE)
- V4 (IMCRA-OMLSA)

評估指標: PESQ, STOI, segSNR
搜索方法: 隨機搜索 / 網格搜索 / 關鍵參數網格 / Optuna 貝葉斯優化

用法:
    python tools/parameter_optimizer.py --version V3 --n_trials 50
    python tools/parameter_optimizer.py --version V3-2 --method grid
    python tools/parameter_optimizer.py --version V3 --method focused_grid
    python tools/parameter_optimizer.py --version V3 --method optuna --n_trials 100
"""

import os
import sys
import json
import yaml
import argparse
import subprocess
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional
import copy
import re


# 項目根目錄
PROJECT_DIR = Path(__file__).parent.parent
CONFIG_DIR = PROJECT_DIR / 'config'
RESULTS_DIR = PROJECT_DIR / 'results' / 'optimization'

# 版本到配置文件的映射
VERSION_CONFIG_MAP = {
    'V3': 'v3_config.yaml',
    'V3-2': 'v3_2_config.yaml',
    'V3-3': 'v3_3_config.yaml',
    'V3-4': 'v3_4_config.yaml',
    'V4': 'v4_config.yaml'
}

# 固定 SPP 參數 (全局) - 舊版向後兼容
FIXED_SPP = {
    'alpha_xi': 0.95,
    'q': 0.3,
    'xi_min_db': -25.0
}

# 參數搜索空間 - 只優化 Gain 參數 (舊版向後兼容)
SEARCH_SPACE = {
    'g_min_db': {
        'min': -25.0,
        'max': -15.0,
        'step': 2.0,
        'type': 'float'
    },
    'alpha_g': {
        'min': 0.85,
        'max': 0.95,
        'step': 0.05,
        'type': 'float'
    }
}

# ============================================================================
# 版本專屬搜索空間 (用於 Optuna 貝葉斯優化)
# 格式: (min, max, step) - step=None 表示連續搜索
# ============================================================================
VERSION_SEARCH_SPACES = {
    # V3: MMSE-STSA (線性估計 - 需提升穩定度)
    # 特點：線性算法較溫和，容易有殘留噪聲或回音
    'V3': {
        'q':         (0.40, 0.80, 0.05),   # 較高值加強非穩態噪聲抑制
        'alpha_xi':  (0.90, 0.98, 0.01),   # 先驗 SNR 穩定性
        'xi_min_db': (-25.0, -15.0, 1.0),  # 避免過度壓制微弱語音
        'g_min_db':  (-22.0, -16.0, 0.5),  # 地板值，過低會暴露音樂噪聲
        'alpha_g':   (0.65, 0.90, 0.05),   # 回音(0.7) vs 噪聲(0.85) 平衡
    },
    # V3-2: MMSE-LSA (對數估計 - 需提升反應速度)
    # 特點：對數算法壓制力強，容易導致聲音悶、小聲
    'V3-2': {
        'q':         (0.50, 0.85, 0.05),   # 需較樂觀估計(0.7+)保留高頻
        'alpha_xi':  (0.92, 0.98, 0.01),
        'xi_min_db': (-20.0, -10.0, 1.0),  # 拉高下限防止聲音悶
        'g_min_db':  (-16.0, -10.0, 0.5),  # 較高地板補償音量
        'alpha_g':   (0.50, 0.80, 0.05),   # 較快反應避免截斷尾韻
    },
    # V3-3: PMMSE (感知模型 - 類 STSA)
    # 特點：基於聽覺掩蔽效應，介於 STSA 與 LSA 之間
    'V3-3': {
        'q':         (0.30, 0.70, 0.05),
        'alpha_xi':  (0.90, 0.98, 0.01),
        'xi_min_db': (-25.0, -15.0, 1.0),
        'g_min_db':  (-20.0, -14.0, 0.5),
        'alpha_g':   (0.70, 0.95, 0.05),
    },
    # V3-4: Laplacian MAP (最大後驗機率 - 需修復參數)
    # 特點：極度敏感，需要極低的先驗下限
    'V3-4': {
        'q':         (0.30, 0.70, 0.05),
        'alpha_xi':  (0.90, 0.98, 0.01),
        'xi_min_db': (-35.0, -20.0, 1.0),  # 絕對關鍵！必須允許極低 SNR
        'g_min_db':  (-20.0, -12.0, 0.5),  # 拉高地板掩蓋 MAP 音樂噪聲
        'alpha_g':   (0.70, 0.95, 0.05),   # 較高平滑度穩定增益
    },
}

# 目標函數權重 (舊版，保留向後兼容)
WEIGHTS = {
    'pesq': 0.5,
    'stoi': 0.3,
    'segsnr': 0.2
}

# 新版複合評分常量
PESQ_MAX = 4.644  # PESQ wideband 最大值 (clean vs clean)
COMPOSITE_WEIGHTS = {
    'pesq': 0.8,   # 主要目標：最大化 PESQ
    'stoi': 0.2    # 次要：STOI 作為 tie-breaker
}
SILENCE_PENALTY_THRESHOLD = -30.0  # g_min_db 閾值 (放寬以適應 V3-4)
SILENCE_PENALTY_VALUE = 0.03  # 懲罰值 (降低懲罰)


def calculate_composite_score(metrics: Dict, g_min_db: float) -> float:
    """
    計算新的複合分數 (根據 optuna_strategy.md)

    公式:
        Final_Score = 0.7 * norm_pesq + 0.3 * stoi
        norm_pesq = raw_pesq_score / 4.644

    死寂懲罰:
        如果 g_min_db < -25，則 Final_Score -= 0.05

    參數:
        metrics: 包含 pesq_raw 和 stoi_raw 的字典
        g_min_db: 當前試驗的 g_min_db 參數

    返回:
        複合分數 (0-1 範圍，越高越好)
    """
    # 歸一化 PESQ
    pesq_raw = metrics.get('pesq_raw', 0)
    norm_pesq = pesq_raw / PESQ_MAX
    norm_pesq = np.clip(norm_pesq, 0, 1)

    # STOI 本身已經是 0-1
    stoi_raw = metrics.get('stoi_raw', 0)
    stoi_raw = np.clip(stoi_raw, 0, 1)

    # 計算複合分數
    final_score = COMPOSITE_WEIGHTS['pesq'] * norm_pesq + COMPOSITE_WEIGHTS['stoi'] * stoi_raw

    # 死寂懲罰
    if g_min_db < SILENCE_PENALTY_THRESHOLD:
        final_score -= SILENCE_PENALTY_VALUE

    return float(final_score)

# 關鍵參數（用於 focused_grid）
# 根據優化經驗，這三個參數對 PESQ 影響最大
KEY_PARAMS = ['q', 'g_min_db', 'alpha_g']

# 關鍵參數的搜索空間（更細密的網格）
KEY_SEARCH_SPACE = {
    'q': {
        'min': 0.2,
        'max': 0.9,
        'step': 0.1,  # 8 個值
        'type': 'float'
    },
    'g_min_db': {
        'min': -20.0,
        'max': -5.0,
        'step': 2.0,  # 8 個值
        'type': 'float'
    },
    'alpha_g': {
        'min': 0.4,
        'max': 0.9,
        'step': 0.1,  # 6 個值
        'type': 'float'
    }
}
# 關鍵參數組合數: 8 × 8 × 6 = 384


def load_config(config_path: Path) -> Dict:
    """加載配置文件"""
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def save_config(config: Dict, config_path: Path):
    """保存配置文件"""
    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)


def generate_random_params() -> Dict[str, float]:
    """生成隨機參數組合 (SPP 固定，只隨機 Gain 參數)"""
    params = FIXED_SPP.copy()  # 先加入固定 SPP 參數
    for param_name, space in SEARCH_SPACE.items():
        if space['type'] == 'float':
            # 生成在範圍內的隨機值，對齊到步長
            n_steps = int((space['max'] - space['min']) / space['step'])
            step_idx = np.random.randint(0, n_steps + 1)
            params[param_name] = round(space['min'] + step_idx * space['step'], 3)
    return params


def generate_grid_params() -> List[Dict[str, float]]:
    """生成網格搜索的所有參數組合 (SPP 固定，只搜索 Gain 參數)"""
    import itertools

    param_values = {}
    for param_name, space in SEARCH_SPACE.items():
        values = np.arange(space['min'], space['max'] + space['step'] / 2, space['step'])
        param_values[param_name] = [round(v, 3) for v in values]

    # 生成所有組合
    keys = list(param_values.keys())
    combinations = list(itertools.product(*[param_values[k] for k in keys]))

    # 每個組合都加入固定 SPP 參數
    result = []
    for combo in combinations:
        params = FIXED_SPP.copy()
        params.update(dict(zip(keys, combo)))
        result.append(params)
    return result


def generate_focused_grid_params(base_config: Dict) -> List[Dict[str, float]]:
    """
    生成關鍵參數的網格搜索組合
    固定 alpha_xi 和 xi_min_db，只搜索 q, g_min_db, alpha_g
    """
    import itertools

    # 從基礎配置獲取固定參數
    fixed_params = {}
    if 'spp' in base_config:
        fixed_params['alpha_xi'] = base_config['spp'].get('alpha_xi', 0.92)
        fixed_params['xi_min_db'] = base_config['spp'].get('xi_min_db', -15.0)

    # 生成關鍵參數的組合
    param_values = {}
    for param_name, space in KEY_SEARCH_SPACE.items():
        values = np.arange(space['min'], space['max'] + space['step'] / 2, space['step'])
        param_values[param_name] = [round(v, 3) for v in values]

    # 生成所有組合
    keys = list(param_values.keys())
    combinations = list(itertools.product(*[param_values[k] for k in keys]))

    # 合併固定參數和搜索參數
    result = []
    for combo in combinations:
        params = fixed_params.copy()
        params.update(dict(zip(keys, combo)))
        result.append(params)

    return result


def create_optuna_study(version: str, base_config: Dict, result_dir: Path,
                        n_trials: int = 100,
                        expanded: bool = False) -> Tuple[Optional[Dict], Optional[Dict]]:
    """
    使用 Optuna 進行貝葉斯優化

    參數:
        expanded: 是否使用擴大的搜索空間

    返回:
        (best_params, best_metrics) 或 (None, None) 如果失敗
    """
    try:
        import optuna
        from optuna.samplers import TPESampler
    except ImportError:
        print("錯誤: 需要安裝 optuna")
        print("  pip install optuna")
        return None, None

    # 創建臨時配置文件路徑
    temp_config_path = result_dir / "temp_config.yaml"

    # 記錄所有試驗結果
    all_results = []

    # 使用版本專屬搜索空間
    if version in VERSION_SEARCH_SPACES:
        search_space = VERSION_SEARCH_SPACES[version]
        print(f"使用 {version} 專屬搜索空間:")
    else:
        # 向後兼容：使用舊的固定空間
        search_space = {
            'q':         (FIXED_SPP['q'], FIXED_SPP['q'], None),
            'alpha_xi':  (FIXED_SPP['alpha_xi'], FIXED_SPP['alpha_xi'], None),
            'xi_min_db': (FIXED_SPP['xi_min_db'], FIXED_SPP['xi_min_db'], None),
            'g_min_db':  (-25.0, -15.0, 2.0),
            'alpha_g':   (0.85, 0.95, 0.05)
        }
        print(f"使用預設搜索空間 (版本 {version} 無專屬設定):")

    for k, (lo, hi, step) in search_space.items():
        step_str = f", step={step}" if step else ""
        print(f"  {k}: [{lo}, {hi}]{step_str}")

    def objective(trial):
        """Optuna 目標函數 - 使用複合分數"""
        # 根據版本專屬搜索空間優化所有參數
        params = {}
        for param_name, (lo, hi, step) in search_space.items():
            if lo == hi:
                # 固定值
                params[param_name] = lo
            elif step is not None:
                # 離散搜索
                params[param_name] = trial.suggest_float(param_name, lo, hi, step=step)
            else:
                # 連續搜索
                params[param_name] = trial.suggest_float(param_name, lo, hi)

        print(f"\n[Trial {trial.number + 1}] 參數:")
        for k, v in params.items():
            print(f"  {k}: {v:.3f}")

        # 應用參數到配置
        config = apply_params_to_config(base_config, params)
        save_config(config, temp_config_path)

        # 運行評估
        metrics = run_evaluation(version, temp_config_path)

        if metrics is None:
            print("  ✗ 評估失敗")
            return float('-inf')  # 返回極小值

        # 計算複合分數
        composite_score = calculate_composite_score(metrics, params['g_min_db'])

        # 顯示詳細結果
        print(f"  原始 PESQ: {metrics.get('pesq_raw', 0):.3f}, STOI: {metrics.get('stoi_raw', 0):.3f}")
        print(f"  改善量: ΔPESQ={metrics['pesq']:+.3f}, ΔSTOI={metrics['stoi']:+.3f}, ΔsegSNR={metrics['segsnr']:+.2f}")
        print(f"  複合分數: {composite_score:.4f}", end="")
        if params['g_min_db'] < SILENCE_PENALTY_THRESHOLD:
            print(f" (已應用死寂懲罰 -{SILENCE_PENALTY_VALUE})")
        else:
            print()

        # 記錄結果
        result = {
            'trial': trial.number + 1,
            'params': params,
            'metrics': metrics,
            'composite_score': composite_score,
            'pesq_improvement': metrics['pesq']  # 保留 PESQ 改善量
        }
        all_results.append(result)

        # 保存單次結果
        result_file = result_dir / f"trial_{trial.number + 1:04d}.json"
        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        return composite_score  # 最大化複合分數

    # 創建 study（最大化複合分數）
    sampler = TPESampler(seed=42, n_startup_trials=10)
    study = optuna.create_study(
        direction='maximize',
        sampler=sampler,
        study_name=f'{version}_optimization'
    )

    # 設置 Optuna 日誌級別
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    print(f"\n開始 Optuna 貝葉斯優化 ({n_trials} trials)...")
    print("使用 TPE (Tree-structured Parzen Estimator) 採樣器")
    print(f"目標函數: {COMPOSITE_WEIGHTS['pesq']} * norm_pesq + {COMPOSITE_WEIGHTS['stoi']} * stoi")
    print("前 10 個 trials 用於初始化探索")

    # 執行優化
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    # 清理臨時文件
    if temp_config_path.exists():
        temp_config_path.unlink()

    # 獲取最佳結果
    best_trial = study.best_trial
    best_params = best_trial.params.copy()
    # 不再需要加入 FIXED_SPP，因為所有參數都在搜索空間中
    best_composite_score = best_trial.value

    # 找到對應的完整 metrics 和 pesq_improvement
    best_metrics = None
    best_pesq_improvement = None
    for result in all_results:
        if result['trial'] == best_trial.number + 1:
            best_metrics = result['metrics']
            best_pesq_improvement = result.get('pesq_improvement', 0)
            break

    # 保存 study 統計
    study_stats = {
        'best_trial': best_trial.number + 1,
        'best_params': best_params,
        'best_composite_score': best_composite_score,
        'best_pesq_improvement': best_pesq_improvement,
        'objective_formula': f"{COMPOSITE_WEIGHTS['pesq']} * (pesq_raw / {PESQ_MAX}) + {COMPOSITE_WEIGHTS['stoi']} * stoi_raw",
        'silence_penalty': f'-{SILENCE_PENALTY_VALUE} if g_min_db < {SILENCE_PENALTY_THRESHOLD}',
        'n_trials': len(study.trials),
        'n_successful': len([t for t in study.trials if t.value != float('-inf')]),
        'version': version,
        'search_space': {k: list(v) for k, v in search_space.items()}
    }

    stats_path = result_dir / 'optuna_stats.json'
    with open(stats_path, 'w', encoding='utf-8') as f:
        json.dump(study_stats, f, indent=2, ensure_ascii=False)

    return best_params, best_metrics


def apply_params_to_config(base_config: Dict, params: Dict[str, float]) -> Dict:
    """將參數應用到配置文件"""
    config = copy.deepcopy(base_config)

    # SPP 參數
    if 'spp' not in config:
        config['spp'] = {}
    if 'alpha_xi' in params:
        config['spp']['alpha_xi'] = params['alpha_xi']
    if 'q' in params:
        config['spp']['q'] = params['q']
    if 'xi_min_db' in params:
        config['spp']['xi_min_db'] = params['xi_min_db']

    # Gain 參數
    if 'gain_calculation' not in config:
        config['gain_calculation'] = {}
    if 'g_min_db' in params:
        config['gain_calculation']['g_min_db'] = params['g_min_db']
    if 'alpha_g' in params:
        config['gain_calculation']['alpha_g'] = params['alpha_g']

    return config


def run_evaluation(version: str, config_path: Path) -> Optional[Dict]:
    """
    運行評估流程：regenerate_all.py + 直接評估

    返回:
        包含 PESQ, STOI, segSNR 改善量的字典
    """
    try:
        # 1. 運行 regenerate_all.py
        regen_cmd = [
            sys.executable,
            str(PROJECT_DIR / 'regenerate_all.py'),
            '--version', version,
            '--config', str(config_path)
        ]
        result = subprocess.run(
            regen_cmd,
            cwd=str(PROJECT_DIR),
            capture_output=True,
            text=True,
            timeout=300  # 5 分鐘超時
        )
        if result.returncode != 0:
            print(f"  regenerate_all.py 失敗: {result.stderr[:200]}")
            return None

        # 2. 直接評估（使用內部函數，避免解析 markdown）
        metrics = evaluate_version_directly(version)
        return metrics

    except subprocess.TimeoutExpired:
        print("  評估超時")
        return None
    except Exception as e:
        print(f"  評估錯誤: {e}")
        import traceback
        traceback.print_exc()
        return None


def evaluate_version_directly(version: str) -> Optional[Dict]:
    """直接評估指定版本的降噪輸出"""
    import librosa

    # 添加項目路徑
    sys.path.insert(0, str(PROJECT_DIR))
    from utils.metrics import calculate_pesq, calculate_stoi
    from utils.metrics_loizou import composite_measure

    EVAL_SR = 16000
    TRIM_SECONDS = 0.5  # 移除前 0.5 秒靜音

    # 測試用例
    noise_types = ['babble', 'car', 'street']
    snr_levels = [5, 10, 15]  # 移除 0dB
    test_cases = [f"{n}_{s}dB" for n in noise_types for s in snr_levels]

    # 改善量 (用於向後兼容)
    pesq_improvements = []
    stoi_improvements = []
    segsnr_improvements = []

    # 原始分數 (用於新的複合評分)
    pesq_raw_scores = []
    stoi_raw_scores = []

    # Clean 參考檔案 (使用 append_silence 目錄下的版本)
    clean_path = PROJECT_DIR / 'test_wav' / 'wav' / 'append_silence' / 'clean_prepend.wav'
    clean, _ = librosa.load(str(clean_path), sr=EVAL_SR)

    # Trim clean（移除前 0.5 秒靜音，與 noisy/enhanced 對齊）
    skip_samples = int(TRIM_SECONDS * EVAL_SR)
    clean = clean[skip_samples:]

    for test_id in test_cases:
        # 文件路徑 (使用 append_silence 目錄)
        noisy_path = PROJECT_DIR / 'test_wav' / 'wav' / 'append_silence' / f'{test_id}_prepend.wav'
        enhanced_path = PROJECT_DIR / 'output' / f'{version}_{test_id}.wav'

        if not enhanced_path.exists():
            continue

        try:
            # 加載音頻
            noisy, _ = librosa.load(str(noisy_path), sr=EVAL_SR)
            enhanced, _ = librosa.load(str(enhanced_path), sr=EVAL_SR)

            # Trim（移除前 0.5 秒）
            skip_samples = int(TRIM_SECONDS * EVAL_SR)
            noisy = noisy[skip_samples:]
            enhanced = enhanced[skip_samples:]

            # 對齊長度
            min_len = min(len(clean), len(noisy), len(enhanced))
            clean_seg = clean[:min_len]
            noisy_seg = noisy[:min_len]
            enhanced_seg = enhanced[:min_len]

            # 計算 PESQ
            try:
                noisy_pesq = calculate_pesq(clean_seg, noisy_seg, EVAL_SR)
                enhanced_pesq = calculate_pesq(clean_seg, enhanced_seg, EVAL_SR)
                if enhanced_pesq is not None:
                    pesq_raw_scores.append(enhanced_pesq)  # 收集原始分數
                if noisy_pesq is not None and enhanced_pesq is not None:
                    pesq_improvements.append(enhanced_pesq - noisy_pesq)
            except Exception:
                pass

            # 計算 STOI
            try:
                noisy_stoi = calculate_stoi(clean_seg, noisy_seg, EVAL_SR)
                enhanced_stoi = calculate_stoi(clean_seg, enhanced_seg, EVAL_SR)
                if enhanced_stoi is not None:
                    stoi_raw_scores.append(enhanced_stoi)  # 收集原始分數
                if noisy_stoi is not None and enhanced_stoi is not None:
                    stoi_improvements.append(enhanced_stoi - noisy_stoi)
            except Exception:
                pass

            # 計算 segSNR
            try:
                noisy_metrics = composite_measure(clean_seg, noisy_seg, EVAL_SR)
                enhanced_metrics = composite_measure(clean_seg, enhanced_seg, EVAL_SR)
                segsnr_improvements.append(
                    enhanced_metrics['segSNR'] - noisy_metrics['segSNR']
                )
            except Exception:
                pass

        except Exception as e:
            print(f"    警告: {test_id} 評估失敗: {e}")
            continue

    # 計算平均值
    if not pesq_improvements or not stoi_improvements or not segsnr_improvements:
        return None

    return {
        # 改善量 (向後兼容)
        'pesq': np.mean(pesq_improvements),
        'stoi': np.mean(stoi_improvements),
        'segsnr': np.mean(segsnr_improvements),
        # 原始分數 (用於新的複合評分)
        'pesq_raw': np.mean(pesq_raw_scores) if pesq_raw_scores else 0,
        'stoi_raw': np.mean(stoi_raw_scores) if stoi_raw_scores else 0
    }


def parse_improvement_report(report_path: Path, version: str) -> Optional[Dict]:
    """從 improvement_report.md 解析指定版本的指標"""
    with open(report_path, 'r', encoding='utf-8') as f:
        content = f.read()

    metrics = {}

    # 解析 PESQ 改善量
    pesq_pattern = rf'\| {version}\s+\| [\d.]+\s+\| [\d.]+\s+\| ([+-]?[\d.]+)\s+\|'
    pesq_match = re.search(pesq_pattern, content)
    if pesq_match:
        metrics['pesq'] = float(pesq_match.group(1))

    # 解析 STOI 改善量
    stoi_pattern = rf'\| {version}\s+\| [\d.]+\s+\| [\d.]+\s+\| ([+-]?[\d.]+)\s+\|'
    # 找到 STOI 部分
    stoi_section = re.search(r'## 3\. 質量指標對比（STOI）.*?(?=##|\Z)', content, re.DOTALL)
    if stoi_section:
        stoi_match = re.search(pesq_pattern.replace('PESQ', 'STOI'), stoi_section.group())
        if stoi_match:
            metrics['stoi'] = float(stoi_match.group(1))

    # 解析 segSNR 改善量
    segsnr_pattern = rf'\| {version}\s+\| ([+-]?[\d.]+)\s+\|'
    segsnr_section = re.search(r'## 1\. 改善量指標.*?(?=##|\Z)', content, re.DOTALL)
    if segsnr_section:
        segsnr_match = re.search(segsnr_pattern, segsnr_section.group())
        if segsnr_match:
            metrics['segsnr'] = float(segsnr_match.group(1))

    # 如果沒有找到所有指標，嘗試更寬鬆的解析
    if len(metrics) < 3:
        # 從輸出中直接搜索版本行
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if f'| {version} ' in line or f'| {version}|' in line:
                parts = [p.strip() for p in line.split('|') if p.strip()]
                if len(parts) >= 4:
                    try:
                        # 嘗試解析數字
                        for j, part in enumerate(parts[1:], 1):
                            val = part.replace('+', '')
                            if re.match(r'^-?[\d.]+$', val):
                                if 'pesq' not in metrics and j == 3:
                                    metrics['pesq'] = float(val)
                                elif 'stoi' not in metrics and j == 3:
                                    metrics['stoi'] = float(val)
                                elif 'segsnr' not in metrics and j == 1:
                                    metrics['segsnr'] = float(val)
                    except (ValueError, IndexError):
                        pass

    return metrics if len(metrics) == 3 else None


def calculate_weighted_score(metrics: Dict) -> float:
    """計算加權分數"""
    # 歸一化到 [0, 1] 範圍
    pesq_norm = (metrics['pesq'] + 0.3) / 0.6  # 假設範圍 [-0.3, +0.3]
    stoi_norm = (metrics['stoi'] + 0.1) / 0.15  # 假設範圍 [-0.1, +0.05]
    segsnr_norm = (metrics['segsnr'] + 1.0) / 7.0  # 假設範圍 [-1, +6]

    # 限制到 [0, 1]
    pesq_norm = max(0, min(1, pesq_norm))
    stoi_norm = max(0, min(1, stoi_norm))
    segsnr_norm = max(0, min(1, segsnr_norm))

    return (WEIGHTS['pesq'] * pesq_norm +
            WEIGHTS['stoi'] * stoi_norm +
            WEIGHTS['segsnr'] * segsnr_norm)


def optimize(version: str, method: str = 'random', n_trials: int = 50,
             population: int = 1, expanded: bool = False) -> List[Dict]:
    """
    執行參數優化

    參數:
        version: 版本名稱 (V3, V3-2, V3-3, V3-4, V4)
        method: 搜索方法 ('random', 'grid', 'focused_grid', 'optuna')
        n_trials: 隨機搜索/Optuna 的試驗次數
        population: 並行評估的數量（目前僅支持 1）
        expanded: 是否使用擴大的搜索空間 (僅 optuna)

    返回:
        所有試驗結果的列表
    """
    print("=" * 80)
    print(f"SPP 參數優化器")
    print("=" * 80)
    print(f"版本: {version}")
    print(f"搜索方法: {method}")

    if method == 'random':
        print(f"試驗次數: {n_trials}")
    elif method == 'grid':
        print(f"試驗次數: 完整網格 (約 8820 組合)")
    elif method == 'focused_grid':
        print(f"試驗次數: 關鍵參數網格 (384 組合)")
        print(f"固定參數: alpha_xi, xi_min_db (使用當前配置值)")
        print(f"搜索參數: q, g_min_db, alpha_g")
    elif method == 'optuna':
        print(f"試驗次數: {n_trials} (貝葉斯優化)")
        if expanded:
            print(f"搜索空間: 擴大")

    print("=" * 80)

    # 創建結果目錄
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    result_dir = RESULTS_DIR / f"{version}_{timestamp}"
    result_dir.mkdir(parents=True, exist_ok=True)

    # 加載基礎配置
    config_name = VERSION_CONFIG_MAP.get(version)
    if not config_name:
        print(f"錯誤: 未知版本 {version}")
        return []

    base_config_path = CONFIG_DIR / config_name
    base_config = load_config(base_config_path)

    # Optuna 使用獨立的優化流程
    if method == 'optuna':
        best_params, best_metrics = create_optuna_study(
            version, base_config, result_dir, n_trials, expanded=expanded
        )

        if best_params and best_metrics:
            # 計算複合分數
            composite_score = calculate_composite_score(best_metrics, best_params['g_min_db'])

            print("\n" + "=" * 80)
            print("Optuna 優化完成!")
            print("=" * 80)
            print(f"最佳複合分數: {composite_score:.4f}")
            print(f"  PESQ 原始: {best_metrics.get('pesq_raw', 0):.3f}")
            print(f"  STOI 原始: {best_metrics.get('stoi_raw', 0):.3f}")
            print(f"  PESQ 改善: {best_metrics['pesq']:+.4f}")
            print(f"最佳參數:")
            for k, v in best_params.items():
                print(f"  {k}: {v}")

            # 保存最佳配置
            best_config = apply_params_to_config(base_config, best_params)
            best_config_path = result_dir / f"{version}_best.yaml"
            save_config(best_config, best_config_path)
            print(f"\n最佳配置已保存: {best_config_path}")

            # 保存優化摘要
            summary = {
                'version': version,
                'method': method,
                'n_trials': n_trials,
                'best_params': best_params,
                'best_metrics': best_metrics,
                'best_composite_score': composite_score,
                'best_pesq_improvement': best_metrics['pesq'],
                'objective_formula': f"{COMPOSITE_WEIGHTS['pesq']} * (pesq_raw / {PESQ_MAX}) + {COMPOSITE_WEIGHTS['stoi']} * stoi_raw",
                'search_space': {k: list(v) for k, v in VERSION_SEARCH_SPACES.get(version, {}).items()},
                'timestamp': timestamp
            }
            summary_path = result_dir / 'summary.json'
            with open(summary_path, 'w', encoding='utf-8') as f:
                json.dump(summary, f, indent=2, ensure_ascii=False)

        return []  # Optuna 結果在內部處理

    # 生成參數組合
    if method == 'grid':
        param_list = generate_grid_params()
        print(f"網格搜索: 共 {len(param_list)} 個組合")
    elif method == 'focused_grid':
        param_list = generate_focused_grid_params(base_config)
        print(f"關鍵參數網格搜索: 共 {len(param_list)} 個組合")
    else:
        param_list = [generate_random_params() for _ in range(n_trials)]
        print(f"隨機搜索: {n_trials} 個試驗")

    # 臨時配置文件路徑
    temp_config_path = result_dir / f"temp_config.yaml"

    results = []
    best_score = -float('inf')
    best_params = None
    best_metrics = None

    for i, params in enumerate(param_list):
        print(f"\n[{i+1}/{len(param_list)}] 測試參數:")
        for k, v in params.items():
            print(f"  {k}: {v}")

        # 應用參數到配置
        config = apply_params_to_config(base_config, params)
        save_config(config, temp_config_path)

        # 運行評估
        metrics = run_evaluation(version, temp_config_path)

        if metrics:
            score = calculate_weighted_score(metrics)
            pesq_score = metrics['pesq']  # 使用 PESQ 作為主要指標
            result = {
                'trial': i + 1,
                'params': params,
                'metrics': metrics,
                'weighted_score': score,
                'pesq_score': pesq_score
            }
            results.append(result)

            print(f"  結果: PESQ={metrics['pesq']:+.3f}, "
                  f"STOI={metrics['stoi']:+.3f}, "
                  f"segSNR={metrics['segsnr']:+.2f}")
            print(f"  PESQ 改善: {pesq_score:.4f}")

            # 更新最佳（以 PESQ 為主）
            if pesq_score > best_score:
                best_score = pesq_score
                best_params = params.copy()
                best_metrics = metrics.copy()
                print(f"  ✓ 新的最佳 PESQ!")

            # 保存單次結果
            result_file = result_dir / f"eval_{i+1:04d}.json"
            with open(result_file, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
        else:
            print(f"  ✗ 評估失敗")

    # 清理臨時文件
    if temp_config_path.exists():
        temp_config_path.unlink()

    # 保存最佳結果
    if best_params:
        print("\n" + "=" * 80)
        print("優化完成!")
        print("=" * 80)
        print(f"最佳 PESQ 改善: {best_score:+.4f}")
        print(f"最佳參數:")
        for k, v in best_params.items():
            print(f"  {k}: {v}")
        print(f"最佳指標:")
        print(f"  PESQ 改善: {best_metrics['pesq']:+.3f}")
        print(f"  STOI 改善: {best_metrics['stoi']:+.3f}")
        print(f"  segSNR 改善: {best_metrics['segsnr']:+.2f} dB")

        # 保存最佳配置
        best_config = apply_params_to_config(base_config, best_params)
        best_config_path = result_dir / f"{version}_best.yaml"
        save_config(best_config, best_config_path)
        print(f"\n最佳配置已保存: {best_config_path}")

        # 保存優化摘要
        summary = {
            'version': version,
            'method': method,
            'n_trials': len(param_list),
            'n_successful': len(results),
            'best_params': best_params,
            'best_metrics': best_metrics,
            'best_pesq': best_score,  # 主要指標：PESQ 改善
            'timestamp': timestamp
        }
        summary_path = result_dir / 'summary.json'
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

    return results


def main():
    parser = argparse.ArgumentParser(description='SPP 參數優化器')
    parser.add_argument('--version', type=str, required=True,
                        choices=['V3', 'V3-2', 'V3-3', 'V3-4', 'V4'],
                        help='要優化的版本')
    parser.add_argument('--method', type=str, default='random',
                        choices=['random', 'grid', 'focused_grid', 'optuna'],
                        help='搜索方法: random(隨機), grid(完整網格), '
                             'focused_grid(關鍵參數網格), optuna(貝葉斯) (default: random)')
    parser.add_argument('--n_trials', type=int, default=50,
                        help='隨機/Optuna 搜索的試驗次數 (default: 50)')
    parser.add_argument('--population', type=int, default=1,
                        help='並行評估數量 (default: 1)')
    parser.add_argument('--expanded', action='store_true',
                        help='使用擴大的搜索空間 (僅 optuna 模式)')

    args = parser.parse_args()

    results = optimize(
        version=args.version,
        method=args.method,
        n_trials=args.n_trials,
        population=args.population,
        expanded=args.expanded
    )

    print(f"\n完成! 共 {len(results)} 個有效試驗")


if __name__ == '__main__':
    main()
