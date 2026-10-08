"""
Test Data Generator - 生成測試數據
"""

import numpy as np
from typing import Optional, Tuple
from .audio_io import add_noise, write_audio


class TestDataGenerator:
    """
    生成語音降噪測試數據

    功能:
    1. 生成合成噪聲（白噪聲、粉紅噪聲等）
    2. 將噪聲添加到乾淨語音
    3. 生成不同 SNR 等級的測試集
    """

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate

    def generate_white_noise(self, duration: float) -> np.ndarray:
        """
        生成白噪聲

        參數:
            duration: 持續時間（秒）

        返回:
            noise: 白噪聲信號
        """
        n_samples = int(duration * self.sample_rate)
        noise = np.random.randn(n_samples).astype(np.float32)
        return noise

    def generate_pink_noise(self, duration: float) -> np.ndarray:
        """
        生成粉紅噪聲（1/f 噪聲）

        參數:
            duration: 持續時間（秒）

        返回:
            noise: 粉紅噪聲信號
        """
        n_samples = int(duration * self.sample_rate)

        # 使用 Voss-McCartney 算法生成粉紅噪聲
        n_rows = 16
        array = np.random.randn(n_rows, n_samples)
        weights = np.logspace(0.0, -1.0, n_rows)
        weights = weights.reshape(-1, 1)

        noise = np.sum(array * weights, axis=0)
        noise = noise / np.max(np.abs(noise))

        return noise.astype(np.float32)

    def generate_babble_noise(self, duration: float, n_speakers: int = 6) -> np.ndarray:
        """
        生成 babble 噪聲（多人說話聲）

        參數:
            duration: 持續時間（秒）
            n_speakers: 說話人數

        返回:
            noise: babble 噪聲信號
        """
        n_samples = int(duration * self.sample_rate)

        # 簡單模擬：疊加多個不同頻率和幅度的正弦波
        noise = np.zeros(n_samples, dtype=np.float32)
        t = np.arange(n_samples) / self.sample_rate

        for _ in range(n_speakers):
            # 隨機基頻（模擬不同說話人）
            f0 = np.random.uniform(80, 250)  # 基頻範圍

            # 添加基頻和諧波
            for harmonic in range(1, 6):
                freq = f0 * harmonic
                amplitude = 1.0 / harmonic
                phase = np.random.uniform(0, 2 * np.pi)
                noise += amplitude * np.sin(2 * np.pi * freq * t + phase)

        # 添加一些隨機性
        noise += 0.1 * np.random.randn(n_samples)

        # 歸一化
        noise = noise / np.max(np.abs(noise))

        return noise.astype(np.float32)

    def create_noisy_speech(
        self,
        clean_speech: np.ndarray,
        noise_type: str = 'white',
        target_snr_db: float = 5.0,
        noise_signal: Optional[np.ndarray] = None
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        創建帶噪語音

        參數:
            clean_speech: 乾淨語音信號
            noise_type: 噪聲類型 ('white', 'pink', 'babble', 'custom')
            target_snr_db: 目標 SNR (dB)
            noise_signal: 自定義噪聲信號（當 noise_type='custom' 時使用）

        返回:
            noisy_speech: 帶噪語音
            noise: 使用的噪聲信號
        """
        duration = len(clean_speech) / self.sample_rate

        # 生成或使用噪聲
        if noise_signal is not None:
            noise = noise_signal
        elif noise_type == 'white':
            noise = self.generate_white_noise(duration)
        elif noise_type == 'pink':
            noise = self.generate_pink_noise(duration)
        elif noise_type == 'babble':
            noise = self.generate_babble_noise(duration)
        else:
            raise ValueError(f"Unknown noise type: {noise_type}")

        # 添加噪聲到語音
        noisy_speech = add_noise(clean_speech, noise, target_snr_db)

        return noisy_speech, noise[:len(clean_speech)]

    def generate_test_set(
        self,
        clean_speech: np.ndarray,
        noise_types: list = None,
        snr_levels: list = None,
        output_dir: Optional[str] = None
    ) -> dict:
        """
        生成完整的測試集

        參數:
            clean_speech: 乾淨語音信號
            noise_types: 噪聲類型列表
            snr_levels: SNR 等級列表 (dB)
            output_dir: 輸出目錄（可選）

        返回:
            test_set: 測試集字典
        """
        if noise_types is None:
            noise_types = ['white', 'pink', 'babble']

        if snr_levels is None:
            snr_levels = [-5, 0, 5, 10, 15]

        test_set = {}

        for noise_type in noise_types:
            test_set[noise_type] = {}

            for snr_db in snr_levels:
                noisy, noise = self.create_noisy_speech(
                    clean_speech,
                    noise_type=noise_type,
                    target_snr_db=snr_db
                )

                test_set[noise_type][snr_db] = {
                    'clean': clean_speech,
                    'noisy': noisy,
                    'noise': noise,
                    'target_snr': snr_db
                }

                # 保存文件（如果指定了輸出目錄）
                if output_dir is not None:
                    import os
                    os.makedirs(output_dir, exist_ok=True)

                    filename = f"{noise_type}_snr{snr_db:+d}db"
                    write_audio(
                        os.path.join(output_dir, f"{filename}_noisy.wav"),
                        noisy,
                        self.sample_rate
                    )

        return test_set


def download_noizeus_corpus(output_dir: str = './data/noizeus') -> None:
    """
    下載 NOIZEUS corpus

    注意：這需要網絡連接和 wget 或 requests 庫

    參數:
        output_dir: 輸出目錄
    """
    import os
    import urllib.request
    import tarfile

    os.makedirs(output_dir, exist_ok=True)

    url = "http://www.utdallas.edu/~loizou/speech/noizeus/"

    print(f"NOIZEUS corpus 需要手動下載。")
    print(f"請訪問: {url}")
    print(f"下載文件並解壓到: {output_dir}")
    print("\n可用的噪聲類型:")
    print("- White noise")
    print("- Pink noise")
    print("- Babble noise (多人說話)")
    print("- Car noise (汽車噪聲)")
    print("- Exhibition noise (展覽噪聲)")
    print("\n每種噪聲有 4 個 SNR 等級: 0dB, 5dB, 10dB, 15dB")


def generate_sample_speech(
    duration: float = 2.0,
    sample_rate: int = 16000,
    f0: float = 150.0
) -> np.ndarray:
    """
    生成簡單的合成語音（用於測試）

    參數:
        duration: 持續時間（秒）
        sample_rate: 採樣率
        f0: 基頻 (Hz)

    返回:
        speech: 合成語音信號
    """
    n_samples = int(duration * sample_rate)
    t = np.arange(n_samples) / sample_rate

    # 基頻調製（模擬語調變化）
    f0_modulation = f0 * (1 + 0.1 * np.sin(2 * np.pi * 3 * t))

    # 生成諧波
    speech = np.zeros(n_samples)
    for harmonic in range(1, 11):
        amplitude = 1.0 / harmonic ** 1.5
        speech += amplitude * np.sin(2 * np.pi * harmonic * f0_modulation * t)

    # 添加振幅包絡（模擬音節）
    envelope = 0.5 * (1 + np.sin(2 * np.pi * 4 * t))
    speech = speech * envelope

    # 添加共振峰（簡化）
    try:
        from scipy import signal
        # 簡單的低通濾波器
        b, a = signal.butter(4, 3000 / (sample_rate / 2), btype='low')
        speech = signal.filtfilt(b, a, speech)
    except ImportError:
        # 如果沒有 scipy，使用簡單的移動平均濾波
        window_size = 5
        speech = np.convolve(speech, np.ones(window_size)/window_size, mode='same')

    # 歸一化
    speech = speech / np.max(np.abs(speech)) * 0.8

    return speech.astype(np.float32)
