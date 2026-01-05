#!/usr/bin/env python3
"""
Clean 音頻保護測試

驗證所有降噪方法對 clean 音頻的保護能力：
- STOI Δ 應該 >= -0.05（允許 5% 下降）
- LSD 應該 < 2.0 dB（失真很小）

使用 pytest 框架運行:
    pytest tests/test_clean_audio.py -v
"""

import pytest
import numpy as np
import librosa
from pathlib import Path
import sys
import os

# 添加父目錄到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pystoi import stoi
from utils.metrics import calculate_lsd
from process_audio import process_audio


# 測試參數
CLEAN_AUDIO_PATH = "test_wav/wav/clean.wav"
OUTPUT_DIR = "test_output/clean_protection"
EVAL_SR = 16000

# 所有方法
ALL_METHODS = ['V1', 'V2', 'V3', 'V3-2', 'V3-3', 'V3-4', 'V4']


@pytest.fixture(scope="module")
def clean_audio():
    """加載 clean 音頻"""
    if not os.path.exists(CLEAN_AUDIO_PATH):
        pytest.skip(f"Clean 音頻文件不存在: {CLEAN_AUDIO_PATH}")

    audio, sr = librosa.load(CLEAN_AUDIO_PATH, sr=EVAL_SR)
    return audio, sr


@pytest.fixture(scope="module")
def denoise_results(clean_audio):
    """對 clean 音頻運行所有降噪方法"""
    audio, sr = clean_audio

    # 創建輸出目錄
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    results = {}

    for method in ALL_METHODS:
        print(f"\n處理 {method}...")

        # 保存輸入文件（臨時）
        input_path = f"{OUTPUT_DIR}/clean_input.wav"
        output_path = f"{OUTPUT_DIR}/{method}_clean_output.wav"

        # 保存輸入
        import soundfile as sf
        sf.write(input_path, audio, sr)

        try:
            # 運行降噪
            process_audio(
                input_path=input_path,
                output_path=output_path,
                version=method,
                config_path=None  # 使用默認配置
            )

            # 加載降噪後的音頻
            enhanced, _ = librosa.load(output_path, sr=EVAL_SR)

            # 確保長度一致
            min_len = min(len(audio), len(enhanced))
            clean_trimmed = audio[:min_len]
            enhanced_trimmed = enhanced[:min_len]

            # 計算指標
            stoi_val = stoi(clean_trimmed, enhanced_trimmed, EVAL_SR, extended=False)
            lsd_val = calculate_lsd(clean_trimmed, enhanced_trimmed)

            # STOI delta（相對於完美的 1.0）
            stoi_delta = stoi_val - 1.0

            results[method] = {
                'STOI': stoi_val,
                'STOI_Delta': stoi_delta,
                'LSD': lsd_val,
                'output_path': output_path
            }

            print(f"  {method}: STOI={stoi_val:.3f} (Δ={stoi_delta:+.3f}), LSD={lsd_val:.2f}")

        except Exception as e:
            print(f"  ✗ {method} 失敗: {e}")
            results[method] = None

    return results


class TestCleanAudioProtection:
    """Clean 音頻保護測試"""

    @pytest.mark.parametrize("method", ALL_METHODS)
    def test_stoi_preservation(self, denoise_results, method):
        """測試 STOI 保持（允許 5% 下降）"""
        result = denoise_results.get(method)

        if result is None:
            pytest.skip(f"{method} 處理失敗")

        stoi_delta = result['STOI_Delta']

        assert stoi_delta >= -0.05, \
            f"{method} STOI 下降過多: {stoi_delta:.3f} (應 >= -0.05)\n" \
            f"  STOI 值: {result['STOI']:.3f}\n" \
            f"  輸出文件: {result['output_path']}"

    @pytest.mark.parametrize("method", ALL_METHODS)
    def test_lsd_minimal(self, denoise_results, method):
        """測試 LSD 很小（< 2.0 dB）"""
        result = denoise_results.get(method)

        if result is None:
            pytest.skip(f"{method} 處理失敗")

        lsd_val = result['LSD']

        assert lsd_val < 2.0, \
            f"{method} LSD 過高: {lsd_val:.2f} (應 < 2.0)\n" \
            f"  輸出文件: {result['output_path']}"

    def test_all_methods_summary(self, denoise_results):
        """匯總所有方法的結果"""
        print("\n" + "=" * 80)
        print("Clean 音頻保護測試結果匯總")
        print("=" * 80)
        print(f"{'方法':<10} | {'STOI':>7} | {'STOI Δ':>8} | {'LSD (dB)':>9} | {'狀態'}")
        print("-" * 80)

        pass_count = 0
        fail_count = 0

        for method in ALL_METHODS:
            result = denoise_results.get(method)

            if result is None:
                print(f"{method:<10} | {'N/A':>7} | {'N/A':>8} | {'N/A':>9} | ✗ 失敗")
                fail_count += 1
                continue

            stoi_val = result['STOI']
            stoi_delta = result['STOI_Delta']
            lsd_val = result['LSD']

            # 檢查是否通過
            stoi_pass = stoi_delta >= -0.05
            lsd_pass = lsd_val < 2.0
            overall_pass = stoi_pass and lsd_pass

            status = "✓ 通過" if overall_pass else "✗ 失敗"

            if overall_pass:
                pass_count += 1
            else:
                fail_count += 1

            print(f"{method:<10} | {stoi_val:7.3f} | {stoi_delta:+8.3f} | {lsd_val:9.2f} | {status}")

        print("=" * 80)
        print(f"通過: {pass_count}/{len(ALL_METHODS)}, 失敗: {fail_count}/{len(ALL_METHODS)}")
        print("=" * 80)

        # 標準說明
        print("\n標準:")
        print("  ✓ STOI Δ >= -0.05 (允許最多 5% 下降)")
        print("  ✓ LSD < 2.0 dB (失真很小)")


if __name__ == '__main__':
    """直接運行測試（不使用 pytest）"""
    import soundfile as sf

    print("=" * 80)
    print("Clean 音頻保護測試（直接運行模式）")
    print("=" * 80)

    # 加載 clean 音頻
    if not os.path.exists(CLEAN_AUDIO_PATH):
        print(f"✗ Clean 音頻文件不存在: {CLEAN_AUDIO_PATH}")
        sys.exit(1)

    audio, sr = librosa.load(CLEAN_AUDIO_PATH, sr=EVAL_SR)
    print(f"✓ 已加載 clean 音頻: {len(audio)} 樣本, {sr} Hz\n")

    # 創建輸出目錄
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 結果
    results = {}

    for method in ALL_METHODS:
        print(f"處理 {method}...")

        input_path = f"{OUTPUT_DIR}/clean_input.wav"
        output_path = f"{OUTPUT_DIR}/{method}_clean_output.wav"

        # 保存輸入
        sf.write(input_path, audio, sr)

        try:
            # 運行降噪
            process_audio(
                input_path=input_path,
                output_path=output_path,
                version=method,
                config_path=None
            )

            # 加載降噪後的音頻
            enhanced, _ = librosa.load(output_path, sr=EVAL_SR)

            # 確保長度一致
            min_len = min(len(audio), len(enhanced))
            clean_trimmed = audio[:min_len]
            enhanced_trimmed = enhanced[:min_len]

            # 計算指標
            stoi_val = stoi(clean_trimmed, enhanced_trimmed, EVAL_SR, extended=False)
            lsd_val = calculate_lsd(clean_trimmed, enhanced_trimmed)
            stoi_delta = stoi_val - 1.0

            # 檢查是否通過
            stoi_pass = stoi_delta >= -0.05
            lsd_pass = lsd_val < 2.0
            overall_pass = stoi_pass and lsd_pass

            status = "✓" if overall_pass else "✗"

            print(f"  {status} STOI={stoi_val:.3f} (Δ={stoi_delta:+.3f}), LSD={lsd_val:.2f}")

            results[method] = {
                'STOI': stoi_val,
                'STOI_Delta': stoi_delta,
                'LSD': lsd_val,
                'pass': overall_pass
            }

        except Exception as e:
            print(f"  ✗ 失敗: {e}")
            results[method] = None

    # 匯總
    print("\n" + "=" * 80)
    print("測試結果匯總")
    print("=" * 80)
    print(f"{'方法':<10} | {'STOI':>7} | {'STOI Δ':>8} | {'LSD (dB)':>9} | {'狀態'}")
    print("-" * 80)

    pass_count = 0
    fail_count = 0

    for method in ALL_METHODS:
        result = results.get(method)

        if result is None:
            print(f"{method:<10} | {'N/A':>7} | {'N/A':>8} | {'N/A':>9} | ✗ 失敗")
            fail_count += 1
            continue

        status = "✓ 通過" if result['pass'] else "✗ 失敗"
        print(f"{method:<10} | {result['STOI']:7.3f} | {result['STOI_Delta']:+8.3f} | "
              f"{result['LSD']:9.2f} | {status}")

        if result['pass']:
            pass_count += 1
        else:
            fail_count += 1

    print("=" * 80)
    print(f"通過: {pass_count}/{len(ALL_METHODS)}, 失敗: {fail_count}/{len(ALL_METHODS)}")
    print("=" * 80)

    print("\n標準:")
    print("  ✓ STOI Δ >= -0.05 (允許最多 5% 下降)")
    print("  ✓ LSD < 2.0 dB (失真很小)")

    if pass_count == len(ALL_METHODS):
        print("\n✅ 所有方法都通過了 clean 音頻保護測試！")
        sys.exit(0)
    else:
        print(f"\n⚠️  有 {fail_count} 個方法未通過測試")
        sys.exit(1)
