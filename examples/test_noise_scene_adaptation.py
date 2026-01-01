"""
測試噪聲場景轉換適應機制 (v1.3.0)

此腳本測試當噪聲場景突然變化時，降噪器是否能快速適應
"""

import numpy as np
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from denoisers.v3_spp_mmse import SppMmseDenoiser


def generate_test_signal(duration=10, sample_rate=16000):
    """
    生成測試信號：純噪聲，中間突然切換噪聲類型

    - 前 5 秒：低頻噪聲（模擬辦公室噪聲）
    - 後 5 秒：高頻噪聲（模擬街道噪聲）
    """
    n_samples = int(duration * sample_rate)
    t = np.arange(n_samples) / sample_rate

    # 前半段：低頻噪聲（100-500 Hz）
    noise1 = np.random.randn(n_samples // 2) * 0.1
    # 簡單的低通濾波
    from scipy import signal as scipy_signal
    sos = scipy_signal.butter(4, 500, 'low', fs=sample_rate, output='sos')
    noise1 = scipy_signal.sosfilt(sos, noise1)

    # 後半段：高頻噪聲（2000-4000 Hz）
    noise2 = np.random.randn(n_samples // 2) * 0.1
    sos = scipy_signal.butter(4, [2000, 4000], 'band', fs=sample_rate, output='sos')
    noise2 = scipy_signal.sosfilt(sos, noise2)

    # 拼接
    test_signal = np.concatenate([noise1, noise2])

    return test_signal, sample_rate


def main():
    print("="*70)
    print("噪聲場景轉換適應測試 (v1.3.0)")
    print("="*70)

    # 生成測試信號
    print("\n生成測試信號...")
    print("  - 前 5 秒：低頻噪聲（辦公室）")
    print("  - 後 5 秒：高頻噪聲（街道）")
    test_signal, sample_rate = generate_test_signal(duration=10, sample_rate=16000)

    # 測試1：無適應機制（關閉噪聲追蹤）
    print("\n" + "="*70)
    print("測試 1: 關閉噪聲場景追蹤")
    print("="*70)
    denoiser_no_tracking = SppMmseDenoiser(
        sample_rate=sample_rate,
        enable_noise_tracking=False  # 關閉
    )
    print("  處理中...")
    enhanced_no_tracking = denoiser_no_tracking.denoise(test_signal)
    print("  ✓ 完成（無噪聲追蹤）")

    # 測試2：有適應機制（開啟噪聲追蹤）
    print("\n" + "="*70)
    print("測試 2: 開啟噪聲場景追蹤")
    print("="*70)
    denoiser_with_tracking = SppMmseDenoiser(
        sample_rate=sample_rate,
        enable_noise_tracking=True  # 開啟
    )
    print("  處理中...")
    enhanced_with_tracking = denoiser_with_tracking.denoise(test_signal)
    print("  ✓ 完成（有噪聲追蹤）")

    # 分析結果
    print("\n" + "="*70)
    print("結果分析")
    print("="*70)

    # 計算前後段的能量
    mid_point = len(test_signal) // 2

    # 輸入信號能量
    input_energy_first = np.mean(test_signal[:mid_point] ** 2)
    input_energy_second = np.mean(test_signal[mid_point:] ** 2)
    input_energy_ratio = input_energy_second / (input_energy_first + 1e-10)

    print(f"\n輸入信號:")
    print(f"  前半段能量: {input_energy_first:.6f}")
    print(f"  後半段能量: {input_energy_second:.6f}")
    print(f"  能量比: {input_energy_ratio:.2f}x")

    # 無追蹤版本
    no_track_energy_first = np.mean(enhanced_no_tracking[:mid_point] ** 2)
    no_track_energy_second = np.mean(enhanced_no_tracking[mid_point:] ** 2)

    print(f"\n無噪聲追蹤:")
    print(f"  前半段能量: {no_track_energy_first:.6f}")
    print(f"  後半段能量: {no_track_energy_second:.6f}")
    print(f"  能量比: {no_track_energy_second / (no_track_energy_first + 1e-10):.2f}x")

    # 有追蹤版本
    with_track_energy_first = np.mean(enhanced_with_tracking[:mid_point] ** 2)
    with_track_energy_second = np.mean(enhanced_with_tracking[mid_point:] ** 2)

    print(f"\n有噪聲追蹤:")
    print(f"  前半段能量: {with_track_energy_first:.6f}")
    print(f"  後半段能量: {with_track_energy_second:.6f}")
    print(f"  能量比: {with_track_energy_second / (with_track_energy_first + 1e-10):.2f}x")

    print("\n" + "="*70)
    print("測試完成！")
    print("="*70)
    print("\n說明:")
    print("  - 如果噪聲追蹤有效，兩個版本的降噪效果應該相似")
    print("  - 有追蹤版本應該能更快適應噪聲場景變化")
    print("  - 實際效果需要聽感測試來評估")
    print()


if __name__ == "__main__":
    try:
        main()
    except ImportError as e:
        print(f"\n錯誤: 缺少依賴 scipy")
        print("請安裝: pip install scipy")
        print(f"\n詳細錯誤: {e}")
