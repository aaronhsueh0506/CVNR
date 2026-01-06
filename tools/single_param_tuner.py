#!/usr/bin/env python3
"""
單參數調整工具
逐個參數調整並觀察影響，最後統整出最佳組合
"""

import json
import yaml
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple
import argparse
import subprocess


class SingleParamTuner:
    """單參數調整器 - 逐個參數測試不同值"""

    def __init__(self, version: str, base_config_path: Path):
        self.version = version
        self.base_config_path = base_config_path

        # 加載基礎配置
        with open(base_config_path, 'r') as f:
            self.base_config = yaml.safe_load(f)

        # 結果保存目錄
        self.results_dir = Path(__file__).parent.parent / 'results' / 'param_tuning' / version
        self.results_dir.mkdir(parents=True, exist_ok=True)

    def define_param_test_values(self, param_name: str) -> List[float]:
        """定義每個參數的測試值範圍 (簡化版，間隔不過於精細)"""

        test_ranges = {
            # SPP 參數
            'alpha_xi': [0.88, 0.90, 0.92, 0.94, 0.96],  # 5個值，間隔0.02
            'q': [0.4, 0.5, 0.6, 0.7],  # 4個值，間隔0.1
            'xi_min_db': [-30, -25, -20],  # 3個值，間隔5

            # Gain calculation 參數
            'g_min_db': [-25, -20, -18, -15, -12],  # 5個值
            'alpha_g': [0.6, 0.7, 0.75, 0.8],  # 4個值，間隔0.05或0.1

            # SNR Adaptive 參數
            'base_g_min_db': [-15, -12, -10, -8],  # 4個值，間隔2-3
            'snr_smoothing': [0.85, 0.9, 0.95],  # 3個值，間隔0.05

            # PMMSE 專用
            'use_spp_weighting': [False, True],  # 2個值
        }

        return test_ranges.get(param_name, [])

    def get_current_param_value(self, param_name: str):
        """獲取當前參數值"""
        if param_name in ['alpha_xi', 'q', 'xi_min_db']:
            return self.base_config['spp'][param_name]
        elif param_name in ['g_min_db', 'alpha_g', 'use_spp_weighting']:
            return self.base_config['gain_calculation'][param_name]
        elif param_name in ['base_g_min_db', 'snr_smoothing']:
            return self.base_config['snr_adaptive'][param_name]
        return None

    def set_param_value(self, config: Dict, param_name: str, value):
        """在配置中設置參數值"""
        config_copy = config.copy()

        if param_name in ['alpha_xi', 'q', 'xi_min_db']:
            config_copy['spp'][param_name] = value
        elif param_name in ['g_min_db', 'alpha_g', 'use_spp_weighting']:
            config_copy['gain_calculation'][param_name] = value
        elif param_name in ['base_g_min_db', 'snr_smoothing']:
            config_copy['snr_adaptive'][param_name] = value

        return config_copy

    def evaluate_config(self, config: Dict, param_name: str, param_value) -> Dict[str, float]:
        """評估單個配置"""
        # 保存臨時配置
        temp_config_path = self.results_dir / f"temp_{param_name}_{param_value}.yaml"
        with open(temp_config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

        # 備份原配置
        backup_path = self.base_config_path.with_suffix('.yaml.backup')
        import shutil
        shutil.copy(self.base_config_path, backup_path)

        try:
            # 使用臨時配置覆蓋原配置
            shutil.copy(temp_config_path, self.base_config_path)

            # 運行 regenerate_all.py
            result = subprocess.run(
                ['python3', 'regenerate_all.py'],
                cwd=str(Path(__file__).parent.parent),
                capture_output=True,
                text=True,
                timeout=600
            )

            if result.returncode != 0:
                print(f"  ❌ regenerate_all.py 失敗: {result.stderr[:200]}")
                return {'pesq': 0.0, 'stoi': 0.0, 'segsnr': 0.0}

            # 運行 compute_improvement.py
            result = subprocess.run(
                ['python3', 'compute_improvement.py'],
                cwd=str(Path(__file__).parent.parent),
                capture_output=True,
                text=True,
                timeout=300
            )

            if result.returncode != 0:
                print(f"  ❌ compute_improvement.py 失敗: {result.stderr[:200]}")
                return {'pesq': 0.0, 'stoi': 0.0, 'segsnr': 0.0}

            # 解析結果
            metrics = self._parse_metrics_from_report()
            return metrics

        finally:
            # 恢復原配置
            shutil.copy(backup_path, self.base_config_path)
            backup_path.unlink()
            temp_config_path.unlink()

    def _parse_metrics_from_report(self) -> Dict[str, float]:
        """從 improvement_report.md 解析指標"""
        report_path = Path(__file__).parent.parent / "results" / "improvement_report.md"

        if not report_path.exists():
            return {'pesq': 0.0, 'stoi': 0.0, 'segsnr': 0.0}

        with open(report_path, 'r') as f:
            content = f.read()

        # 解析 PESQ
        pesq_match = None
        for line in content.split('\n'):
            if f"| {self.version} |" in line and "PESQ" in content[:content.index(line)]:
                parts = line.split('|')
                if len(parts) >= 5:
                    try:
                        pesq_match = float(parts[4].strip())
                        break
                    except:
                        pass

        # 解析 STOI
        stoi_match = None
        for line in content.split('\n'):
            if f"| {self.version} |" in line and "STOI" in content[:content.index(line)]:
                parts = line.split('|')
                if len(parts) >= 5:
                    try:
                        stoi_match = float(parts[4].strip())
                        break
                    except:
                        pass

        # 解析 segSNR
        segsnr_match = None
        for line in content.split('\n'):
            if f"| {self.version} |" in line and "segSNR改善" in content[:content.index(line)]:
                parts = line.split('|')
                if len(parts) >= 3:
                    try:
                        segsnr_match = float(parts[2].strip())
                        break
                    except:
                        pass

        return {
            'pesq': pesq_match or 0.0,
            'stoi': stoi_match or 0.0,
            'segsnr': segsnr_match or 0.0
        }

    def tune_single_param(self, param_name: str) -> Dict:
        """調整單個參數並記錄結果"""
        print(f"\n{'='*80}")
        print(f"調整參數: {param_name}")
        print(f"{'='*80}")

        # 獲取測試值
        test_values = self.define_param_test_values(param_name)
        current_value = self.get_current_param_value(param_name)

        print(f"當前值: {current_value}")
        print(f"測試值: {test_values}")
        print()

        results = []

        for i, value in enumerate(test_values, 1):
            print(f"[{i}/{len(test_values)}] 測試 {param_name} = {value} ...", end=' ')

            # 創建新配置
            config = self.set_param_value(self.base_config, param_name, value)

            # 評估
            metrics = self.evaluate_config(config, param_name, value)

            # 計算加權分數
            weighted_score = 0.5 * metrics['pesq'] + 0.3 * metrics['stoi'] + 0.2 * (metrics['segsnr'] / 10.0)

            result = {
                'param_name': param_name,
                'param_value': value,
                'is_current': (value == current_value),
                'metrics': metrics,
                'weighted_score': weighted_score
            }
            results.append(result)

            print(f"PESQ={metrics['pesq']:.3f}, STOI={metrics['stoi']:.3f}, segSNR={metrics['segsnr']:.2f} dB, Score={weighted_score:.4f}")

        # 保存結果
        result_file = self.results_dir / f"{param_name}_tuning.json"
        with open(result_file, 'w') as f:
            json.dump({
                'param_name': param_name,
                'current_value': current_value,
                'results': results
            }, f, indent=2)

        print(f"\n結果已保存: {result_file}")

        # 找出最佳值
        best_result = max(results, key=lambda x: x['weighted_score'])
        print(f"\n最佳值: {best_result['param_value']} (Score={best_result['weighted_score']:.4f})")
        print(f"  PESQ: {best_result['metrics']['pesq']:.3f}")
        print(f"  STOI: {best_result['metrics']['stoi']:.3f}")
        print(f"  segSNR: {best_result['metrics']['segsnr']:.2f} dB")

        if best_result['param_value'] != current_value:
            improvement = best_result['weighted_score'] - next(r['weighted_score'] for r in results if r['is_current'])
            print(f"  相對當前值改善: {improvement:+.4f}")

        return {
            'param_name': param_name,
            'current_value': current_value,
            'best_value': best_result['param_value'],
            'best_score': best_result['weighted_score'],
            'best_metrics': best_result['metrics'],
            'all_results': results
        }

    def generate_report(self, tuning_results: List[Dict], output_path: Path):
        """生成調整報告"""
        report = [f"# {self.version} 參數調整報告\n\n"]
        report.append(f"**配置文件**: {self.base_config_path}\n\n")
        report.append("## 各參數調整結果\n\n")

        for result in tuning_results:
            param_name = result['param_name']
            current_value = result['current_value']
            best_value = result['best_value']
            best_metrics = result['best_metrics']

            report.append(f"### {param_name}\n\n")
            report.append(f"- **當前值**: {current_value}\n")
            report.append(f"- **最佳值**: {best_value}\n")
            report.append(f"- **最佳性能**:\n")
            report.append(f"  - PESQ: {best_metrics['pesq']:.3f}\n")
            report.append(f"  - STOI: {best_metrics['stoi']:.3f}\n")
            report.append(f"  - segSNR: {best_metrics['segsnr']:.2f} dB\n")
            report.append(f"  - 加權分數: {result['best_score']:.4f}\n")

            # 繪製趨勢表格
            report.append(f"\n**調整趨勢**:\n\n")
            report.append(f"| 值 | PESQ | STOI | segSNR | 加權分數 |\n")
            report.append(f"|{'-'*10}|{'-'*8}|{'-'*8}|{'-'*10}|{'-'*12}|\n")

            for r in result['all_results']:
                marker = " ⭐" if r['param_value'] == best_value else (" 📍" if r['is_current'] else "")
                report.append(f"| {r['param_value']}{marker} | {r['metrics']['pesq']:.3f} | "
                            f"{r['metrics']['stoi']:.3f} | {r['metrics']['segsnr']:+.2f} | "
                            f"{r['weighted_score']:.4f} |\n")

            report.append("\n")

        # 統整建議
        report.append("## 統整建議\n\n")
        report.append("基於以上測試，建議將參數調整為：\n\n")
        report.append("```yaml\n")

        # 按類別分組
        spp_params = [r for r in tuning_results if r['param_name'] in ['alpha_xi', 'q', 'xi_min_db']]
        gain_params = [r for r in tuning_results if r['param_name'] in ['g_min_db', 'alpha_g', 'use_spp_weighting']]
        snr_params = [r for r in tuning_results if r['param_name'] in ['base_g_min_db', 'snr_smoothing']]

        if spp_params:
            report.append("spp:\n")
            for r in spp_params:
                report.append(f"  {r['param_name']}: {r['best_value']}\n")

        if gain_params:
            report.append("\ngain_calculation:\n")
            for r in gain_params:
                report.append(f"  {r['param_name']}: {r['best_value']}\n")

        if snr_params:
            report.append("\nsnr_adaptive:\n")
            for r in snr_params:
                report.append(f"  {r['param_name']}: {r['best_value']}\n")

        report.append("```\n")

        # 保存報告
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(''.join(report))

        print(f"\n報告已保存: {output_path}")


def main():
    parser = argparse.ArgumentParser(description='單參數逐步調整工具')
    parser.add_argument('--version', type=str, required=True,
                        help='要優化的版本 (V3, V3-2, V3-3, V3-4)')
    parser.add_argument('--params', type=str, nargs='+',
                        help='要調整的參數列表')
    parser.add_argument('--all', action='store_true',
                        help='調整所有參數')

    args = parser.parse_args()

    # 配置文件映射
    config_map = {
        'V3': 'config/v3_config.yaml',
        'V3-2': 'config/v3_2_config.yaml',
        'V3-3': 'config/v3_3_config.yaml',
        'V3-4': 'config/v3_4_config.yaml'
    }

    if args.version not in config_map:
        print(f"❌ 不支持的版本: {args.version}")
        print(f"支持的版本: {', '.join(config_map.keys())}")
        return

    config_path = Path(__file__).parent.parent / config_map[args.version]

    if not config_path.exists():
        print(f"❌ 配置文件不存在: {config_path}")
        return

    # 創建調整器
    tuner = SingleParamTuner(args.version, config_path)

    # 確定要調整的參數
    all_params = ['alpha_xi', 'q', 'g_min_db', 'alpha_g', 'base_g_min_db']

    if args.all:
        params_to_tune = all_params
    elif args.params:
        params_to_tune = args.params
    else:
        print("請指定 --params 或使用 --all")
        print(f"可用參數: {', '.join(all_params)}")
        return

    print(f"\n{'='*80}")
    print(f"{args.version} 參數調整")
    print(f"{'='*80}")
    print(f"配置文件: {config_path}")
    print(f"調整參數: {', '.join(params_to_tune)}")
    print(f"{'='*80}\n")

    # 逐個調整參數
    tuning_results = []
    for param_name in params_to_tune:
        result = tuner.tune_single_param(param_name)
        tuning_results.append(result)

    # 生成報告
    report_path = tuner.results_dir / f"{args.version}_tuning_report.md"
    tuner.generate_report(tuning_results, report_path)

    print(f"\n{'='*80}")
    print("調整完成！")
    print(f"{'='*80}")


if __name__ == '__main__':
    main()
