"""
音頻預處理腳本

功能：
1. 將所有 opus 文件轉換為 wav (16kHz, 單聲道)
2. 從 noisy - clean 提取純噪聲
3. 將純噪聲 append 到 noisy 音頻前面（提供初始噪聲估計段）
4. 處理 benchmark 文件夾中的 rnnoise 和 speex 結果
"""

import subprocess
import os
import numpy as np
import sys

# 添加父目錄到路徑以導入 utils
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from utils.audio_io import read_audio, write_audio
    HAVE_AUDIO_IO = True
except ImportError:
    print("Warning: 無法導入 utils.audio_io，將使用 scipy 或 soundfile")
    HAVE_AUDIO_IO = False
    try:
        import soundfile as sf
        HAVE_SOUNDFILE = True
    except ImportError:
        HAVE_SOUNDFILE = False
        try:
            from scipy.io import wavfile
            HAVE_SCIPY = True
        except ImportError:
            HAVE_SCIPY = False
            print("Error: 需要安裝 soundfile 或 scipy")
            sys.exit(1)


def read_wav(file_path):
    """讀取 WAV 文件"""
    if HAVE_AUDIO_IO:
        return read_audio(file_path)
    elif HAVE_SOUNDFILE:
        data, sr = sf.read(file_path, dtype='float32')
        return data, sr
    else:  # HAVE_SCIPY
        sr, data = wavfile.read(file_path)
        # 轉換為 float32 並歸一化
        if data.dtype == np.int16:
            data = data.astype(np.float32) / 32768.0
        elif data.dtype == np.int32:
            data = data.astype(np.float32) / 2147483648.0
        return data, sr


def write_wav(file_path, data, sr):
    """寫入 WAV 文件"""
    if HAVE_AUDIO_IO:
        write_audio(file_path, data, sr)
    elif HAVE_SOUNDFILE:
        sf.write(file_path, data, sr, subtype='PCM_16')
    else:  # HAVE_SCIPY
        # 轉換為 int16
        data_int16 = np.clip(data * 32768.0, -32768, 32767).astype(np.int16)
        wavfile.write(file_path, sr, data_int16)


def opus_to_wav(opus_file, wav_file, sample_rate=48000):
    """使用 ffmpeg 將 Opus 轉換為 WAV"""
    if not os.path.exists(opus_file):
        print(f"錯誤: {opus_file} 不存在")
        return False

    command = [
        'ffmpeg', '-y',  # -y 覆蓋現有文件
        '-i', opus_file,
        '-acodec', 'pcm_s16le',
        '-ar', str(sample_rate),
        '-ac', '1',  # 單聲道
        wav_file
    ]

    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
        print(f"✓ 轉換: {os.path.basename(opus_file)} -> {os.path.basename(wav_file)}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ 轉換失敗: {opus_file}")
        print(f"  錯誤: {e.stderr}")
        return False
    except FileNotFoundError:
        print("錯誤: 未找到 ffmpeg。請安裝 ffmpeg。")
        return False


def extract_noise_and_prepend(noisy_wav, clean_wav, output_wav, noise_duration_sec=0.5):
    """
    從 noisy - clean 提取純噪聲，然後 prepend 到 noisy 前面

    參數:
        noisy_wav: 帶噪音頻文件路徑
        clean_wav: 乾淨音頻文件路徑
        output_wav: 輸出文件路徑（noise + noisy）
        noise_duration_sec: 要提取的噪聲時長（秒，默認 0.5 秒 = 500ms）

    說明:
        - V1 需要前 20 幀（200ms）初始化
        - 500ms 提供足夠的緩衝，約 50 幀
    """
    # 讀取音頻
    noisy, sr = read_wav(noisy_wav)
    clean, _ = read_wav(clean_wav)

    # 確保長度一致
    min_len = min(len(noisy), len(clean))
    noisy = noisy[:min_len]
    clean = clean[:min_len]

    # 提取純噪聲 = noisy - clean
    pure_noise = noisy - clean

    # 取前 noise_duration_sec 秒作為初始噪聲段
    noise_samples = int(noise_duration_sec * sr)
    noise_samples = min(noise_samples, len(pure_noise))
    noise_segment = pure_noise[:noise_samples]

    # 拼接: noise_segment + noisy
    output_audio = np.concatenate([noise_segment, noisy])

    # 寫入
    write_wav(output_wav, output_audio, sr)

    print(f"✓ 生成: {os.path.basename(output_wav)}")
    print(f"  噪聲段: {noise_duration_sec}s, 總長度: {len(output_audio)/sr:.2f}s")


def main():
    print("="*70)
    print("音頻預處理腳本")
    print("="*70)

    # 設置路徑
    base_dir = os.path.dirname(os.path.abspath(__file__))

    # 創建輸出目錄
    wav_dir = os.path.join(base_dir, 'wav')
    append_silence_dir = os.path.join(base_dir, 'append_silence')
    benchmark_wav_dir = os.path.join(base_dir, 'benchmark_wav')

    os.makedirs(wav_dir, exist_ok=True)
    os.makedirs(append_silence_dir, exist_ok=True)
    os.makedirs(benchmark_wav_dir, exist_ok=True)
    os.makedirs(os.path.join(benchmark_wav_dir, 'rnnoise'), exist_ok=True)
    os.makedirs(os.path.join(benchmark_wav_dir, 'speex'), exist_ok=True)

    print(f"\n輸出目錄:")
    print(f"  - wav/              : 原始 WAV 文件")
    print(f"  - append_silence/   : 前面添加噪聲段的 WAV 文件")
    print(f"  - benchmark_wav/    : benchmark 結果的 WAV 文件")

    # ========== 步驟 1: 轉換所有根目錄的 opus 文件 ==========
    print("\n" + "="*70)
    print("步驟 1: 轉換測試音頻 (opus -> wav)")
    print("="*70)

    opus_files = [
        'clean.opus',
        'babble_0dB.opus', 'babble_5dB.opus', 'babble_10dB.opus', 'babble_15dB.opus',
        'car_0dB.opus', 'car_5dB.opus', 'car_10dB.opus', 'car_15dB.opus',
        'street_0dB.opus', 'street_5dB.opus', 'street_10dB.opus', 'street_15dB.opus',
    ]

    converted_files = {}
    for opus_file in opus_files:
        opus_path = os.path.join(base_dir, opus_file)
        if os.path.exists(opus_path):
            wav_file = opus_file.replace('.opus', '.wav')
            wav_path = os.path.join(wav_dir, wav_file)
            if opus_to_wav(opus_path, wav_path):
                converted_files[opus_file] = wav_path
        else:
            print(f"⚠ 跳過: {opus_file} (文件不存在)")

    # ========== 步驟 2: 提取噪聲並 prepend ==========
    print("\n" + "="*70)
    print("步驟 2: 提取噪聲並 prepend 到測試音頻")
    print("="*70)

    clean_wav = converted_files.get('clean.opus')
    if not clean_wav:
        print("錯誤: 未找到 clean.wav，無法繼續")
        return

    # 處理所有噪聲音頻
    noise_types = ['babble', 'car', 'street']
    snr_levels = ['0dB', '5dB', '10dB', '15dB']

    for noise_type in noise_types:
        for snr in snr_levels:
            opus_file = f"{noise_type}_{snr}.opus"
            noisy_wav = converted_files.get(opus_file)

            if noisy_wav:
                output_file = f"{noise_type}_{snr}_prepend.wav"
                output_path = os.path.join(append_silence_dir, output_file)

                try:
                    extract_noise_and_prepend(noisy_wav, clean_wav, output_path, noise_duration_sec=0.5)
                except Exception as e:
                    print(f"✗ 處理失敗: {opus_file}")
                    print(f"  錯誤: {e}")

    # ========== 步驟 3: 轉換 benchmark 文件 ==========
    print("\n" + "="*70)
    print("步驟 3: 轉換 benchmark 結果 (opus -> wav)")
    print("="*70)

    # RNNoise
    print("\n[RNNoise]")
    rnnoise_dir = os.path.join(base_dir, 'benchmark', 'rnnoise')
    if os.path.exists(rnnoise_dir):
        for opus_file in os.listdir(rnnoise_dir):
            if opus_file.endswith('.opus'):
                opus_path = os.path.join(rnnoise_dir, opus_file)
                wav_file = opus_file.replace('.opus', '.wav')
                wav_path = os.path.join(benchmark_wav_dir, 'rnnoise', wav_file)
                opus_to_wav(opus_path, wav_path)
    else:
        print("⚠ benchmark/rnnoise/ 目錄不存在")

    # Speex
    print("\n[Speex]")
    speex_dir = os.path.join(base_dir, 'benchmark', 'speex')
    if os.path.exists(speex_dir):
        for opus_file in os.listdir(speex_dir):
            if opus_file.endswith('.opus'):
                opus_path = os.path.join(speex_dir, opus_file)
                wav_file = opus_file.replace('.opus', '.wav')
                wav_path = os.path.join(benchmark_wav_dir, 'speex', wav_file)
                opus_to_wav(opus_path, wav_path)
    else:
        print("⚠ benchmark/speex/ 目錄不存在")

    # ========== 完成 ==========
    print("\n" + "="*70)
    print("處理完成！")
    print("="*70)
    print(f"\n輸出文件位置:")
    print(f"  1. 原始 WAV:          {wav_dir}/")
    print(f"  2. Prepend 噪聲 WAV:  {append_silence_dir}/")
    print(f"  3. Benchmark WAV:     {benchmark_wav_dir}/")
    print()


if __name__ == "__main__":
    main()
