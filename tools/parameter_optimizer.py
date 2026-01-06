#!/usr/bin/env python3
"""
參數優化器 - 使用 NSGA-II 遺傳算法自動搜索最佳參數組合

使用方法:
    python3 tools/parameter_optimizer.py --version V3-2 --population 50 --generations 30

目標:
    優化 PESQ (0.5) + STOI (0.3) + segSNR (0.2)
"""

import os
import sys
import argparse
import json
import yaml
import numpy as np
import subprocess
import shutil
from pathlib import Path
from typing import Dict, List, Tuple
from datetime import datetime

# 添加項目根目錄到 Python 路徑
sys.path.insert(0, str(Path(__file__).parent.parent))

from pymoo.core.problem import Problem
from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.optimize import minimize
from pymoo.termination import get_termination


class SpeechDenoiseOptimizationProblem(Problem):
    """語音降噪參數優化問題定義"""

    def __init__(self, version: str, param_space: Dict,
                 weights: List[float] = [0.5, 0.3, 0.2],
                 base_config_path: str = None):
        """
        Args:
            version: 要優化的版本 (V3, V3-2, V3-3, V3-4)
            param_space: 參數搜索空間定義
                         {param_name: (min, max, type), ...}
            weights: 目標權重 [PESQ, STOI, segSNR]
            base_config_path: 基礎配置文件路徑
        """
        self.version = version
        self.param_space = param_space
        self.weights = np.array(weights)
        self.base_config_path = base_config_path or f"config/{self._get_config_name(version)}"

        # 參數邊界
        self.param_names = list(param_space.keys())
        xl = []  # 下界
        xu = []  # 上界

        for param_name in self.param_names:
            min_val, max_val, _ = param_space[param_name]
            xl.append(min_val)
            xu.append(max_val)

        # 初始化 Problem
        # n_var: 參數數量
        # n_obj: 3 個目標 (PESQ, STOI, segSNR)
        # xl, xu: 變量下界和上界
        super().__init__(n_var=len(self.param_names),
                         n_obj=3,
                         xl=np.array(xl),
                         xu=np.array(xu))

        # 加載基礎配置
        with open(self.base_config_path, 'r') as f:
            self.base_config = yaml.safe_load(f)

        # 評估計數器
        self.eval_count = 0
        self.results_dir = Path(f"results/optimization/{version}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        self.results_dir.mkdir(parents=True, exist_ok=True)

        print(f"[優化器] 初始化完成")
        print(f"  版本: {version}")
        print(f"  參數數量: {len(self.param_names)}")
        print(f"  參數: {self.param_names}")
        print(f"  目標權重: PESQ={weights[0]}, STOI={weights[1]}, segSNR={weights[2]}")
        print(f"  結果目錄: {self.results_dir}")

    def _get_config_name(self, version: str) -> str:
        """根據版本獲取配置文件名"""
        mapping = {
            'V3': 'v3_config.yaml',
            'V3-2': 'v3_2_config.yaml',
            'V3-3': 'v3_3_config.yaml',
            'V3-4': 'v3_4_config.yaml',
        }
        return mapping.get(version, f'v3_config.yaml')

    def _create_config(self, params: np.ndarray) -> str:
        """根據參數創建臨時配置文件"""
        # 複製基礎配置
        config = self.base_config.copy()

        # 更新參數
        for i, param_name in enumerate(self.param_names):
            value = params[i]
            param_type = self.param_space[param_name][2]

            # 根據類型轉換
            if param_type == 'int':
                value = int(round(value))
            elif param_type == 'bool':
                value = bool(round(value))
            else:  # float
                value = float(value)

            # 設置參數（支持嵌套）
            if '.' in param_name:
                parts = param_name.split('.')
                current = config
                for part in parts[:-1]:
                    if part not in current:
                        current[part] = {}
                    current = current[part]
                current[parts[-1]] = value
            else:
                # 簡化：假設所有參數在 spp 或 gain_calculation 中
                if param_name in ['alpha_xi', 'q', 'xi_min_db']:
                    config['spp'][param_name] = value
                elif param_name in ['g_min_db', 'alpha_g', 'use_spp_weighting']:
                    config['gain_calculation'][param_name] = value

        # 保存臨時配置
        temp_config_path = self.results_dir / f"temp_config_{self.eval_count}.yaml"
        with open(temp_config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

        return str(temp_config_path)

    def _get_denoiser_class(self, version: str):
        """根據版本獲取降噪器類"""
        from denoisers import (
            SppMmseDenoiser,
            MmseLsaDenoiser,
            PmmseDenoiser,
            LaplacianMmseDenoiser
        )

        mapping = {
            'V3': SppMmseDenoiser,
            'V3-2': MmseLsaDenoiser,
            'V3-3': PmmseDenoiser,
            'V3-4': LaplacianMmseDenoiser,
        }
        return mapping.get(version)

    def _get_denoiser_params_from_config(self, config, sr, fft_size):
        """從配置文件提取降噪器參數（基於 regenerate_all.py）"""
        params = {
            'sample_rate': sr,
            'fft_size': fft_size,
            'frame_size_ms': config['audio']['frame_size_ms'],
            'frame_shift_ms': config['audio']['frame_shift_ms']
        }

        # 添加噪聲追蹤（如果啟用）
        if config.get('noise_tracking', {}).get('enable', False):
            params['enable_noise_tracking'] = True

        # Gain calculation 參數
        if 'gain_calculation' in config:
            gc = config['gain_calculation']
            if gc.get('method') == 'spp_mmse':
                params.update({
                    'g_min_db': gc.get('g_min_db', -20.0),
                    'alpha_g': gc.get('alpha_g', 0.7),
                    'use_full_formula': gc.get('use_full_formula', False)
                })
            elif gc.get('method') in ['mmse_lsa', 'pmmse', 'laplacian_mmse']:
                params.update({
                    'g_min_db': gc.get('g_min_db', -20.0),
                    'alpha_g': gc.get('alpha_g', 0.7)
                })

        # SPP 參數
        if 'spp' in config:
            spp = config['spp']
            params.update({
                'alpha_xi': spp.get('alpha_xi', 0.98),
                'q': spp.get('q', 0.5),
                'xi_min_db': spp.get('xi_min_db', -25.0)
            })

        return params

    def _evaluate_single(self, params: np.ndarray) -> Dict[str, float]:
        """評估單個參數組合（直接調用降噪器，不使用 subprocess）"""
        import librosa
        import soundfile as sf

        self.eval_count += 1

        # 創建配置字典（不創建臨時文件）
        config = self.base_config.copy()

        # 更新參數
        for i, param_name in enumerate(self.param_names):
            value = params[i]
            param_type = self.param_space[param_name][2]

            # 根據類型轉換
            if param_type == 'int':
                value = int(round(value))
            elif param_type == 'bool':
                value = bool(round(value))
            else:  # float
                value = float(value)

            # 設置參數
            if param_name in ['alpha_xi', 'q', 'xi_min_db']:
                config['spp'][param_name] = value
            elif param_name in ['g_min_db', 'alpha_g', 'use_spp_weighting']:
                config['gain_calculation'][param_name] = value

        print(f"\n[評估 #{self.eval_count}] 參數: {dict(zip(self.param_names, params))}")

        try:
            # 獲取降噪器類
            denoiser_class = self._get_denoiser_class(self.version)
            if denoiser_class is None:
                print(f"  ❌ 不支持的版本: {self.version}")
                return {'pesq': -1.0, 'stoi': -1.0, 'segsnr': -10.0}

            # 提取降噪器參數
            sr = 16000
            fft_size = config['audio']['fft_size']
            denoiser_params = self._get_denoiser_params_from_config(config, sr, fft_size)

            # 創建降噪器
            denoiser = denoiser_class(**denoiser_params)

            # 測試用例
            noise_types = ['babble', 'car', 'street']
            snr_levels = [0, 5, 10, 15]
            test_cases = ['clean'] + [f"{n}_{s}dB" for n in noise_types for s in snr_levels]

            # 處理所有測試用例
            output_dir = Path(__file__).parent.parent / 'output'

            for test_id in test_cases:
                if test_id == 'clean':
                    input_file = Path(__file__).parent.parent / "test_wav/wav/append_silence/clean_prepend.wav"
                else:
                    input_file = Path(__file__).parent.parent / f"test_wav/wav/append_silence/{test_id}_prepend.wav"

                output_file = output_dir / f"{self.version}_{test_id}.wav"

                if not input_file.exists():
                    continue

                # 加載音頻
                noisy, original_sr = librosa.load(str(input_file), sr=None)

                # 重採樣到 16kHz
                if original_sr != sr:
                    noisy = librosa.resample(noisy, orig_sr=original_sr, target_sr=sr)

                # 降噪
                enhanced = denoiser.denoise(noisy)

                # 保存
                sf.write(str(output_file), enhanced, sr)

            # 運行評估（仍需要使用 subprocess 調用 compute_improvement.py）
            result = subprocess.run(
                ['python3', 'compute_improvement.py'],
                cwd=str(Path(__file__).parent.parent),
                capture_output=True,
                text=True,
                timeout=300
            )

            if result.returncode != 0:
                print(f"  ❌ 評估失敗: {result.stderr[:200]}")
                return {'pesq': -1.0, 'stoi': -1.0, 'segsnr': -10.0}

            # 解析結果
            metrics = self._parse_metrics_from_report(self.version)

            print(f"  ✓ PESQ={metrics['pesq']:.3f}, STOI={metrics['stoi']:.3f}, segSNR={metrics['segsnr']:.2f} dB")

            # 保存評估結果
            eval_result = {
                'eval_id': self.eval_count,
                'params': dict(zip(self.param_names, params.tolist())),
                'metrics': metrics
            }
            with open(self.results_dir / f"eval_{self.eval_count}.json", 'w') as f:
                json.dump(eval_result, f, indent=2)

            return metrics

        except Exception as e:
            print(f"  ❌ 評估異常: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'pesq': -1.0, 'stoi': -1.0, 'segsnr': -10.0}

    def _parse_metrics_from_report(self, version: str) -> Dict[str, float]:
        """從 improvement_report.md 解析指標"""
        report_path = Path(__file__).parent.parent / "results" / "improvement_report.md"

        if not report_path.exists():
            print(f"  ⚠️ 報告文件不存在: {report_path}")
            return {'pesq': 0.0, 'stoi': 0.0, 'segsnr': 0.0}

        with open(report_path, 'r') as f:
            content = f.read()

        # 解析 segSNR 表格
        segsnr = 0.0
        for line in content.split('\n'):
            if f'| {version} |' in line or f'| {version.replace("-", "-")} |' in line:
                parts = line.split('|')
                if len(parts) >= 4:
                    try:
                        segsnr_str = parts[2].strip().replace('+', '')
                        segsnr = float(segsnr_str)
                        break
                    except:
                        pass

        # 解析 PESQ 表格
        pesq_delta = 0.0
        in_pesq_section = False
        for line in content.split('\n'):
            if '## 2. 質量指標對比（PESQ）' in line:
                in_pesq_section = True
            elif in_pesq_section and (f'| {version} |' in line or f'| {version.replace("-", "-")} |' in line):
                parts = line.split('|')
                if len(parts) >= 5:
                    try:
                        pesq_delta_str = parts[4].strip().replace('+', '')
                        pesq_delta = float(pesq_delta_str)
                        break
                    except:
                        pass

        # 解析 STOI 表格
        stoi_delta = 0.0
        in_stoi_section = False
        for line in content.split('\n'):
            if '## 3. 質量指標對比（STOI）' in line:
                in_stoi_section = True
            elif in_stoi_section and (f'| {version} |' in line or f'| {version.replace("-", "-")} |' in line):
                parts = line.split('|')
                if len(parts) >= 5:
                    try:
                        stoi_delta_str = parts[4].strip().replace('+', '')
                        stoi_delta = float(stoi_delta_str)
                        break
                    except:
                        pass

        return {
            'pesq': pesq_delta,
            'stoi': stoi_delta,
            'segsnr': segsnr
        }

    def _evaluate(self, X, out, *args, **kwargs):
        """評估種群（pymoo 要求的接口）"""
        # X: 種群矩陣 (n_individuals, n_vars)
        # out["F"]: 目標值矩陣 (n_individuals, n_obj)

        F = []
        for individual in X:
            metrics = self._evaluate_single(individual)

            # pymoo 最小化目標，所以我們要取負值
            # 目標: 最大化 PESQ, STOI, segSNR
            F.append([
                -metrics['pesq'],    # 最大化 PESQ
                -metrics['stoi'],    # 最大化 STOI
                -metrics['segsnr']   # 最大化 segSNR
            ])

        out["F"] = np.array(F)


def define_search_space(version: str) -> Dict:
    """定義各版本的參數搜索空間

    Returns:
        Dict: {param_name: (min, max, type), ...}
    """
    if version == 'V3':
        # MMSE-STSA
        return {
            'alpha_xi': (0.90, 0.99, 'float'),
            'q': (0.4, 0.8, 'float'),
            'g_min_db': (-18.0, -8.0, 'float'),
            'alpha_g': (0.65, 0.90, 'float'),
        }

    elif version == 'V3-2':
        # MMSE-LSA
        return {
            'alpha_xi': (0.88, 0.96, 'float'),
            'q': (0.4, 0.7, 'float'),
            'g_min_db': (-25.0, -15.0, 'float'),
            'alpha_g': (0.60, 0.85, 'float'),
        }

    elif version == 'V3-3':
        # PMMSE
        return {
            'alpha_xi': (0.88, 0.96, 'float'),
            'q': (0.4, 0.7, 'float'),
            'g_min_db': (-25.0, -15.0, 'float'),
            'alpha_g': (0.60, 0.85, 'float'),
            # 'use_spp_weighting': (0, 1, 'bool'),  # 簡化：暫不搜索布爾參數
        }

    elif version == 'V3-4':
        # Laplacian-MMSE
        return {
            'alpha_xi': (0.88, 0.96, 'float'),
            'q': (0.4, 0.7, 'float'),
            'g_min_db': (-25.0, -12.0, 'float'),
            'alpha_g': (0.60, 0.85, 'float'),
        }

    else:
        raise ValueError(f"不支持的版本: {version}")


def main():
    parser = argparse.ArgumentParser(description='語音降噪參數優化器 (NSGA-II)')
    parser.add_argument('--version', type=str, required=True,
                        choices=['V3', 'V3-2', 'V3-3', 'V3-4'],
                        help='要優化的版本')
    parser.add_argument('--population', type=int, default=50,
                        help='種群大小（默認 50）')
    parser.add_argument('--generations', type=int, default=30,
                        help='迭代代數（默認 30）')
    parser.add_argument('--weights', type=float, nargs=3,
                        default=[0.5, 0.3, 0.2],
                        help='目標權重 [PESQ STOI segSNR]（默認 0.5 0.3 0.2）')
    parser.add_argument('--output', type=str, default=None,
                        help='輸出文件路徑（默認 results/optimization/<version>_<timestamp>/）')

    args = parser.parse_args()

    print("=" * 100)
    print("語音降噪參數優化器 - NSGA-II 多目標優化")
    print("=" * 100)
    print(f"版本: {args.version}")
    print(f"種群大小: {args.population}")
    print(f"迭代代數: {args.generations}")
    print(f"目標權重: PESQ={args.weights[0]}, STOI={args.weights[1]}, segSNR={args.weights[2]}")
    print(f"預計評估次數: {args.population * args.generations}")
    print(f"預計時間: ~{args.population * args.generations * 8 / 3600:.1f} 小時（假設每評估 8 秒）")
    print("=" * 100)

    # 定義搜索空間
    param_space = define_search_space(args.version)

    # 創建優化問題
    problem = SpeechDenoiseOptimizationProblem(
        version=args.version,
        param_space=param_space,
        weights=args.weights
    )

    # 創建 NSGA-II 算法
    algorithm = NSGA2(
        pop_size=args.population,
        eliminate_duplicates=True
    )

    # 定義終止條件
    termination = get_termination("n_gen", args.generations)

    # 運行優化
    print("\n開始優化...")
    print("-" * 100)

    res = minimize(
        problem,
        algorithm,
        termination,
        seed=1,
        verbose=True,
        save_history=True
    )

    print("-" * 100)
    print("優化完成!")
    print("=" * 100)

    # 保存結果
    output_dir = Path(args.output) if args.output else problem.results_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    # Pareto 前沿
    pareto_front = res.F
    pareto_params = res.X

    # 保存 Pareto 最優解
    pareto_results = []
    for i, (params, objectives) in enumerate(zip(pareto_params, pareto_front)):
        param_dict = dict(zip(problem.param_names, params.tolist()))
        obj_dict = {
            'pesq': -objectives[0],  # 轉回正值
            'stoi': -objectives[1],
            'segsnr': -objectives[2]
        }
        pareto_results.append({
            'rank': i + 1,
            'params': param_dict,
            'objectives': obj_dict,
            'weighted_score': (args.weights[0] * obj_dict['pesq'] +
                             args.weights[1] * obj_dict['stoi'] +
                             args.weights[2] * obj_dict['segsnr'])
        })

    # 按加權分數排序
    pareto_results.sort(key=lambda x: x['weighted_score'], reverse=True)

    # 保存結果
    with open(output_dir / 'pareto_front.json', 'w') as f:
        json.dump(pareto_results, f, indent=2)

    # 保存最佳配置
    best_result = pareto_results[0]
    print("\n最佳配置（加權分數最高）:")
    print(f"  加權分數: {best_result['weighted_score']:.4f}")
    print(f"  PESQ 改善: {best_result['objectives']['pesq']:.3f}")
    print(f"  STOI 改善: {best_result['objectives']['stoi']:.3f}")
    print(f"  segSNR 改善: {best_result['objectives']['segsnr']:.2f} dB")
    print("\n  參數:")
    for param, value in best_result['params'].items():
        print(f"    {param}: {value:.4f}" if isinstance(value, float) else f"    {param}: {value}")

    # 生成優化後的配置文件
    best_params = np.array([best_result['params'][name] for name in problem.param_names])
    optimized_config_path = problem._create_config(best_params)
    shutil.copy(optimized_config_path, output_dir / f'{args.version}_optimized.yaml')
    os.remove(optimized_config_path)

    print(f"\n結果已保存到: {output_dir}")
    print(f"  - pareto_front.json: Pareto 最優解集")
    print(f"  - {args.version}_optimized.yaml: 最佳配置文件")
    print(f"  - eval_*.json: 所有評估記錄")
    print("=" * 100)


if __name__ == "__main__":
    main()
