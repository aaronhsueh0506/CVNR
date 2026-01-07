#!/usr/bin/env python3
"""
生成參數調優測試配置

為每個版本生成所有參數組合的 YAML 配置文件
保存到 config/tune/ 目錄

用法：
    python3 tools/generate_tune_configs.py
    python3 tools/generate_tune_configs.py --versions V3 V3-2
    python3 tools/generate_tune_configs.py --dry-run  # 只顯示不生成
"""

import os
import yaml
import argparse
from itertools import product
from pathlib import Path


# 參數範圍（每個 3 個值，共 81 組/版本）
PARAM_RANGES = {
    'alpha_xi': [0.92, 0.94, 0.96],
    'q': [0.4, 0.5, 0.6],
    'g_min_db': [-15.0, -12.0, -9.0],
    'alpha_g': [0.6, 0.7, 0.8],
}

# 版本與基礎配置映射
VERSION_CONFIG_MAP = {
    'V3': 'config/v3_config.yaml',
    'V3-2': 'config/v3_2_config.yaml',
    'V3-3': 'config/v3_3_config.yaml',
    'V3-4': 'config/v3_4_config.yaml',
    'V4': 'config/v4_config.yaml',
}

# 版本名稱轉換（用於文件名）
VERSION_FILENAME_MAP = {
    'V3': 'v3',
    'V3-2': 'v3-2',
    'V3-3': 'v3-3',
    'V3-4': 'v3-4',
    'V4': 'v4',
}


def load_base_config(config_path: str) -> dict:
    """加載基礎配置"""
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def apply_params_to_config(config: dict, params: dict) -> dict:
    """將參數應用到配置"""
    config = config.copy()

    # 深拷貝 spp 和 gain_calculation
    if 'spp' in config:
        config['spp'] = config['spp'].copy()
    if 'gain_calculation' in config:
        config['gain_calculation'] = config['gain_calculation'].copy()

    # 應用參數
    for param_name, value in params.items():
        if param_name in ['alpha_xi', 'q', 'xi_min_db']:
            if 'spp' not in config:
                config['spp'] = {}
            config['spp'][param_name] = value
        elif param_name in ['g_min_db', 'alpha_g']:
            if 'gain_calculation' not in config:
                config['gain_calculation'] = {}
            config['gain_calculation'][param_name] = value

    return config


def generate_param_combinations() -> list:
    """生成所有參數組合"""
    param_names = list(PARAM_RANGES.keys())
    param_values = list(PARAM_RANGES.values())

    combinations = []
    for values in product(*param_values):
        params = dict(zip(param_names, values))
        combinations.append(params)

    return combinations


def generate_configs_for_version(version: str, output_dir: Path, dry_run: bool = False) -> int:
    """為單個版本生成所有配置"""
    base_config_path = VERSION_CONFIG_MAP[version]
    base_config = load_base_config(base_config_path)

    combinations = generate_param_combinations()
    version_filename = VERSION_FILENAME_MAP[version]

    count = 0
    for i, params in enumerate(combinations, 1):
        # 生成配置
        config = apply_params_to_config(base_config, params)

        # 更新版本標記
        config['version'] = f"{config.get('version', version)}-t{i:03d}"

        # 生成文件名
        filename = f"{version_filename}_t{i:03d}.yaml"
        filepath = output_dir / filename

        if dry_run:
            print(f"  [DRY-RUN] {filename}: {params}")
        else:
            # 寫入文件
            with open(filepath, 'w', encoding='utf-8') as f:
                # 添加註釋頭
                f.write(f"# {version} 調參測試配置 #{i:03d}\n")
                f.write(f"# 參數: alpha_xi={params['alpha_xi']}, q={params['q']}, ")
                f.write(f"g_min_db={params['g_min_db']}, alpha_g={params['alpha_g']}\n")
                f.write(f"# 基於: {base_config_path}\n\n")
                yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

            count += 1

    return count


def main():
    parser = argparse.ArgumentParser(description='生成參數調優測試配置')
    parser.add_argument('--versions', type=str, nargs='+',
                        default=list(VERSION_CONFIG_MAP.keys()),
                        help='指定版本 (默認: 全部)')
    parser.add_argument('--output-dir', type=str, default='config/tune',
                        help='輸出目錄 (默認: config/tune)')
    parser.add_argument('--dry-run', action='store_true',
                        help='只顯示將生成的配置，不實際寫入')
    args = parser.parse_args()

    output_dir = Path(args.output_dir)

    # 創建輸出目錄
    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    # 計算組合數
    num_combinations = 1
    for values in PARAM_RANGES.values():
        num_combinations *= len(values)

    print("=" * 80)
    print("生成參數調優測試配置")
    print("=" * 80)
    print(f"參數範圍:")
    for name, values in PARAM_RANGES.items():
        print(f"  {name}: {values}")
    print(f"\n每個版本組合數: {num_combinations}")
    print(f"版本: {args.versions}")
    print(f"總配置數: {num_combinations * len(args.versions)}")
    print(f"輸出目錄: {output_dir}")
    print("=" * 80)

    total_count = 0
    for version in args.versions:
        if version not in VERSION_CONFIG_MAP:
            print(f"\n⚠️  跳過未知版本: {version}")
            continue

        print(f"\n生成 {version} 配置...")
        count = generate_configs_for_version(version, output_dir, args.dry_run)
        total_count += count

        if not args.dry_run:
            print(f"  ✓ 生成 {count} 個配置文件")

    print("\n" + "=" * 80)
    if args.dry_run:
        print(f"[DRY-RUN] 將生成 {num_combinations * len(args.versions)} 個配置文件")
    else:
        print(f"完成! 共生成 {total_count} 個配置文件")
        print(f"輸出目錄: {output_dir}/")
    print("=" * 80)


if __name__ == "__main__":
    main()
