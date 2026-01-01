import subprocess
import os

def opus_to_wav_ffmpeg(opus_file, wav_file):
    """使用 ffmpeg 将 Opus 文件转换为 WAV 文件"""
    # 确保输入文件存在
    if not os.path.exists(opus_file):
        print(f"错误: 输入文件 {opus_file} 不存在!")
        return

    # ffmpeg 命令: -i (输入), -acodec pcm_s16le (指定PCM编码), -ar 16000 (采样率), -ac 1 (单声道)
    # 注意: 可以根据需要调整采样率和声道数 (例如，-ar 44100 -ac 2)
    command = [
        'ffmpeg',
        '-i', opus_file,
        '-acodec', 'pcm_s16le', # 16-bit Little-endian PCM
        '-ar', '16000',         # 16kHz采样率
        '-ac', '1',             # 单声道
        wav_file
    ]

    try:
        # 执行命令
        subprocess.run(command, check=True, capture_output=True, text=True)
        print(f"成功将 {opus_file} 转换为 {wav_file}")
    except subprocess.CalledProcessError as e:
        print(f"ffmpeg 执行失败: {e}")
        print(f"Stderr: {e.stderr}")
    except FileNotFoundError:
        print("错误: 未找到 ffmpeg 命令。请确保它已安装并在系统 PATH 中。")

# 示例用法
opus_input = "street_10dB.opus"
wav_output = "street_10dB.wav"

# 假设你有一个名为 input.opus 的文件
# 创建一个假的 opus_input 文件用于演示（实际上你需要一个真正的 .opus 文件）
# ... (实际使用时请确保有真实的 Opus 文件)

opus_to_wav_ffmpeg(opus_input, wav_output)
