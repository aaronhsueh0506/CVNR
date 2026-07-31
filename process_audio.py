"""
音頻文件降噪處理工具

使用 V1-V3 系列降噪算法處理真實音頻文件。

用法：
    # 基本用法
    python process_audio.py input.wav

    # 指定輸出目錄
    python process_audio.py input.wav --output-dir ./custom_output

    # 只處理特定版本
    python process_audio.py input.wav --versions V3 V3-2

    # 指定配置文件目錄
    python process_audio.py input.wav --config-dir ./my_configs

輸入要求：
    - 音頻格式：WAV（16位 PCM）
    - 採樣率：任意（推薦 16kHz）
    - 聲道：單聲道或立體聲（會自動轉為單聲道）

輸出：
    在輸出目錄下生成：
    - input_v1.wav（頻譜減法）
    - input_v2.wav（Wiener 濾波）
    - input_v3.wav（SPP-MMSE）

配置文件：
    從 config/ 目錄讀取對應版本的 YAML 配置。
"""

import sys
import os
import argparse
import time
from typing import Dict
import numpy as np

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Matplotlib for plotting
try:
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    print("Warning: matplotlib not installed. Skipping waveform plots.")
    print("Install with: pip install matplotlib")

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False
    print("Warning: pyyaml not installed. Using default parameters.")
    print("Install with: pip install pyyaml")

from utils.audio_io import read_audio, write_audio
from utils.visualization import plot_spp_spectrogram
from denoisers import (
    SpectralSubtractionDenoiser,
    WienerDenoiser,
    SppMmseDenoiser,
    MmseLsaDenoiser,
    PmmseDenoiser,
)
from core.nr_modes import apply_mode
from core.nr_strength import apply_strength
from core.signal_grid import resolve_signal_grid


def load_config(config_file: str) -> dict:
    """
    從 YAML 文件加載配置

    Args:
        config_file: 配置文件路徑

    Returns:
        配置字典
    """
    if not YAML_AVAILABLE:
        return {}

    if not os.path.exists(config_file):
        print(f"Warning: Config file not found: {config_file}")
        return {}

    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        return config
    except Exception as e:
        print(f"Error loading config {config_file}: {e}")
        return {}


def build_v3_2_base_params(config, sample_rate, frame_size, frame_shift, fft_size):
    """Build the base MmseLsaDenoiser kwargs from a V3-2 config dict (BEFORE the strength/mode
    overlays). Shared by create_denoiser_from_config and tools/ablate_nr_music.py so the
    config→params mapping lives in exactly one place.
    """
    spp_config = config.get('spp', {})
    gain_config = config.get('gain_calculation', {})
    noise_config = config.get('noise_estimation', {})

    params = {
        'sample_rate': sample_rate,
        'frame_size': frame_size,
        'frame_shift': frame_shift,
        'fft_size': fft_size,
        'alpha_xi': spp_config.get('alpha_xi', 0.98),
        'q': spp_config.get('q', 0.5),
        'xi_min_db': spp_config.get('xi_min_db', -25.0),
        'g_min_db': gain_config.get('g_min_db', -40.0),
        'alpha_g': gain_config.get('alpha_g', 0.7),
        'num_init_frames': noise_config.get('num_init_frames', 20),
    }

    ne_method = noise_config.get('method', 'recursive_average')
    if ne_method == 'mcra':
        params.update({
            'noise_method': 'mcra',
            'alpha_s': noise_config.get('alpha_s', 0.9),
            'alpha_noise': noise_config.get('alpha_d', 0.85),
            'alpha_p': noise_config.get('alpha_p', 0.2),
            'L': noise_config.get('L', 96),
            'delta_db': noise_config.get('delta_db', 5.0),
            'broadband_threshold': noise_config.get('broadband_threshold', 0.8),
            'scene_change_threshold_db': noise_config.get('scene_change_threshold_db', 10.0),
            'scene_change_min_frames': noise_config.get('scene_change_min_frames', 5),
            'scene_change_blend': noise_config.get('scene_change_blend', 0.5),
            'scene_change_flatness_threshold': noise_config.get('scene_change_flatness_threshold', 0.4),
            'mcra_accept_external_spp': noise_config.get('mcra_accept_external_spp', True),
        })
    else:
        params.update({
            'noise_method': 'recursive_average',
            'alpha_noise': noise_config.get('alpha', 0.95),
        })

    return params


def create_denoiser_from_config(
    version: str,
    config_dir: str,
    sample_rate: int,
    mode: str = None,
    strength: str = None,
    fft_size: int = None,
):
    """
    根據配置文件創建降噪器

    Args:
        version: 版本名稱 (V1, V2, V3, V3-2, V3-3)
        config_dir: 配置文件目錄
        sample_rate: 採樣率
        mode: NR 內容保留模式 ('full' | 'stationary')，僅 V3-2 有效；
              None 則取 config 的 mode，預設 'full'。
        strength: NR 強度預設 ('mild' | 'balanced' | 'aggressive')，僅 V3-2 有效；
              None 則取 config 的 strength，預設 'balanced'（= base YAML）。
              強度軸（深度）與 mode 軸（內容保留）正交，先套 strength 再套 mode，
              對應 C mmse_lsa_config_for_mode() 後接 mmse_lsa_apply_stationary()。

    Returns:
        降噪器實例
    """
    # 加載配置文件 (v1.5.0: 將 V3-2 轉換為 v3_2_config.yaml)
    config_filename = version.lower().replace('-', '_') + "_config.yaml"
    config_file = os.path.join(config_dir, config_filename)
    config = load_config(config_file)

    # Runtime sample rate owns the grid. YAML carries algorithm tunables, but
    # must not re-introduce the former 20/10 ms padded framing at another rate.
    frame_size, frame_shift, fft_size = resolve_signal_grid(sample_rate, fft_size)

    # 根據版本創建降噪器
    if version == 'V1':
        # V1: Spectral Subtraction
        gain_config = config.get('gain_calculation', {})
        noise_config = config.get('noise_estimation', {})

        return SpectralSubtractionDenoiser(
            sample_rate=sample_rate,
            frame_size=frame_size,
            frame_shift=frame_shift,
            fft_size=fft_size,
            alpha=gain_config.get('alpha', 2.0),
            beta=gain_config.get('beta', 0.01),
            alpha_smooth=gain_config.get('alpha_smooth', 0.8),
            num_init_frames=noise_config.get('num_init_frames', 20)
        )

    elif version == 'V2':
        # V2: Wiener Filter
        gain_config = config.get('gain_calculation', {})
        noise_config = config.get('noise_estimation', {})

        ne_method = noise_config.get('method', 'recursive_average')
        v2_params = {
            'sample_rate': sample_rate,
            'frame_size': frame_size,
            'frame_shift': frame_shift,
            'fft_size': fft_size,
            'noise_method': ne_method,
            'alpha': noise_config.get('alpha', 0.95),
            'min_gain': gain_config.get('min_gain', 0.01),
            'alpha_smooth': gain_config.get('alpha_smooth', 0.8),
            'num_init_frames': noise_config.get('num_init_frames', 20),
            'update_during_speech': noise_config.get('update_during_speech', False),
        }
        if ne_method == 'mcra':
            v2_params.update({
                'alpha_s': noise_config.get('alpha_s', 0.9),
                'alpha_d': noise_config.get('alpha_d', 0.85),
                'alpha_p': noise_config.get('alpha_p', 0.2),
                'L': noise_config.get('L', 96),
                'delta_db': noise_config.get('delta_db', 5.0),
            })
        return WienerDenoiser(**v2_params)

    elif version == 'V3':
        # V3: SPP-MMSE
        spp_config = config.get('spp', {})
        gain_config = config.get('gain_calculation', {})
        noise_config = config.get('noise_estimation', {})

        # 基本參數
        params = {
            'sample_rate': sample_rate,
            'frame_size': frame_size,
            'frame_shift': frame_shift,
            'fft_size': fft_size,
            'alpha_xi': spp_config.get('alpha_xi', 0.98),
            'q': spp_config.get('q', 0.5),
            'xi_min_db': spp_config.get('xi_min_db', -25.0),
            'g_min_db': gain_config.get('g_min_db', -40.0),
            'alpha_g': gain_config.get('alpha_g', 0.7),
            'num_init_frames': noise_config.get('num_init_frames', 20),
            'use_full_formula': gain_config.get('use_full_formula', False)
        }

        # 噪聲估計方法
        ne_method = noise_config.get('method', 'recursive_average')
        if ne_method == 'mcra':
            params.update({
                'noise_method': 'mcra',
                'alpha_s': noise_config.get('alpha_s', 0.9),
                'alpha_noise': noise_config.get('alpha_d', 0.85),
                'alpha_p': noise_config.get('alpha_p', 0.2),
                'L': noise_config.get('L', 96),
                'delta_db': noise_config.get('delta_db', 5.0),
                'broadband_threshold': noise_config.get('broadband_threshold', 0.8),
                'scene_change_threshold_db': noise_config.get('scene_change_threshold_db', 10.0),
                'scene_change_min_frames': noise_config.get('scene_change_min_frames', 5),
                'scene_change_blend': noise_config.get('scene_change_blend', 0.5)
            })
        else:
            params.update({
                'noise_method': 'recursive_average',
                'alpha_noise': noise_config.get('alpha', 0.95)
            })


        return SppMmseDenoiser(**params)

    elif version == 'V3-2':
        # V3-2: MMSE-LSA (Ephraim-Malah 1985)
        params = build_v3_2_base_params(config, sample_rate, frame_size, frame_shift, fft_size)

        # NR strength preset (mild | balanced | aggressive) — the DEPTH axis. Applied FIRST so the
        # content mode composes on top (mirrors C config_for_mode() then apply_stationary()).
        # 'balanced' == base YAML (empty overlay). Explicit arg wins over config.
        strength = strength or config.get('strength', 'balanced')
        params = apply_strength(params, strength)

        # NR content-preservation mode (full | stationary). Explicit arg wins over config; the
        # preset overlay sets the stationary levers, then params['mode'] records the choice.
        mode = mode or config.get('mode', 'full')
        params = apply_mode(params, mode)
        params['mode'] = mode
        return MmseLsaDenoiser(**params)

    elif version == 'V3-3':
        # V3-3: PMMSE (Wolfe & Godsill β=0.5)
        spp_config = config.get('spp', {})
        gain_config = config.get('gain_calculation', {})
        noise_config = config.get('noise_estimation', {})

        # 基本參數
        params = {
            'sample_rate': sample_rate,
            'frame_size': frame_size,
            'frame_shift': frame_shift,
            'fft_size': fft_size,
            'alpha_xi': spp_config.get('alpha_xi', 0.98),
            'q': spp_config.get('q', 0.5),
            'xi_min_db': spp_config.get('xi_min_db', -25.0),
            'g_min_db': gain_config.get('g_min_db', -40.0),
            'alpha_g': gain_config.get('alpha_g', 0.7),
            'use_spp_weighting': gain_config.get('use_spp_weighting', True),
            'num_init_frames': noise_config.get('num_init_frames', 20)
        }

        # 噪聲估計方法
        ne_method = noise_config.get('method', 'recursive_average')
        if ne_method == 'mcra':
            params.update({
                'noise_method': 'mcra',
                'alpha_s': noise_config.get('alpha_s', 0.9),
                'alpha_noise': noise_config.get('alpha_d', 0.85),
                'alpha_p': noise_config.get('alpha_p', 0.2),
                'L': noise_config.get('L', 96),
                'delta_db': noise_config.get('delta_db', 5.0),
                'broadband_threshold': noise_config.get('broadband_threshold', 0.8),
                'scene_change_threshold_db': noise_config.get('scene_change_threshold_db', 10.0),
                'scene_change_min_frames': noise_config.get('scene_change_min_frames', 5),
                'scene_change_blend': noise_config.get('scene_change_blend', 0.5)
            })
        else:
            params.update({
                'noise_method': 'recursive_average',
                'alpha_noise': noise_config.get('alpha', 0.95)
            })


        return PmmseDenoiser(**params)

    else:
        raise ValueError(f"Unknown version: {version}")


def plot_waveforms(
    audio: np.ndarray,
    results: Dict,
    sample_rate: int,
    output_dir: str,
    basename: str
):
    """
    繪製時域波形對比圖

    Args:
        audio: 原始含噪音頻
        results: 降噪結果字典
        sample_rate: 採樣率
        output_dir: 輸出目錄
        basename: 輸入文件基本名稱
    """
    if not MATPLOTLIB_AVAILABLE:
        return

    # 準備數據
    num_versions = len(results) + 1  # +1 for noisy
    duration = len(audio) / sample_rate
    time_axis = np.linspace(0, duration, len(audio))

    # 創建子圖
    fig, axes = plt.subplots(num_versions, 1, figsize=(12, 2.5 * num_versions))

    if num_versions == 1:
        axes = [axes]

    # 繪製原始含噪音頻
    axes[0].plot(time_axis, audio, linewidth=0.5, color='gray')
    axes[0].set_title('Noisy (Input)', fontsize=12, fontweight='bold')
    axes[0].set_ylabel('Amplitude')
    axes[0].set_xlim(0, duration)
    axes[0].grid(True, alpha=0.3)

    # 計算 y 軸範圍（統一所有子圖）
    y_max = max(np.abs(audio).max(),
                max(np.abs(r['enhanced']).max() for r in results.values()))
    y_lim = [-y_max * 1.1, y_max * 1.1]
    axes[0].set_ylim(y_lim)

    # 繪製每個版本的降噪結果
    colors = {'V1': '#FF6B6B', 'V2': '#4ECDC4', 'V3': '#45B7D1'}

    for idx, (version, result) in enumerate(sorted(results.items()), 1):
        enhanced = result['enhanced']
        color = colors.get(version, '#95A5A6')

        # v1.5.0 修復: 為每個輸出動態生成 time_axis，防止維度不匹配
        time_axis_enhanced = np.linspace(0, duration, len(enhanced))
        axes[idx].plot(time_axis_enhanced, enhanced, linewidth=0.5, color=color)

        # 標題包含處理時間和實時率
        rtf = result['rtf']
        proc_time = result['processing_time'] * 1000
        title = f"{version} Enhanced (RTF: {rtf:.3f}, {proc_time:.1f} ms)"
        axes[idx].set_title(title, fontsize=12, fontweight='bold')
        axes[idx].set_ylabel('Amplitude')
        axes[idx].set_xlim(0, duration)
        axes[idx].set_ylim(y_lim)
        axes[idx].grid(True, alpha=0.3)

    # 最後一個子圖顯示 x 軸標籤
    axes[-1].set_xlabel('Time (seconds)')

    # 調整布局
    plt.tight_layout()

    # 保存圖片
    plot_file = os.path.join(output_dir, f"{basename}_waveforms.png")
    plt.savefig(plot_file, dpi=150, bbox_inches='tight')
    print(f"  ✓ Waveform plot: {plot_file}")

    plt.close()


def process_audio_file(
    input_file: str,
    output_dir: str,
    versions: list,
    config_dir: str,
    mode: str = None,
    strength: str = None,
    fft_size: int = None,
):
    """
    處理音頻文件

    Args:
        input_file: 輸入音頻文件路徑
        output_dir: 輸出目錄
        versions: 要使用的版本列表 (e.g., ['V1', 'V2'])
        config_dir: 配置文件目錄
    """
    print("="*70)
    print("音頻文件降噪處理")
    print("="*70)

    # 檢查輸入文件
    if not os.path.exists(input_file):
        print(f"Error: Input file not found: {input_file}")
        return False

    # 讀取音頻文件
    print(f"\n[1/4] 讀取音頻文件")
    print("-"*70)
    print(f"  輸入文件: {input_file}")

    try:
        audio, sample_rate = read_audio(input_file)

        # 如果是立體聲，轉換為單聲道
        if len(audio.shape) > 1:
            audio = np.mean(audio, axis=1)
            print(f"  已轉換為單聲道")

        duration = len(audio) / sample_rate
        print(f"  採樣率: {sample_rate} Hz")
        print(f"  時長: {duration:.2f} 秒")
        print(f"  樣本數: {len(audio)}")

    except Exception as e:
        print(f"Error reading audio file: {e}")
        return False

    # 獲取輸入文件名（無擴展名）
    basename = os.path.splitext(os.path.basename(input_file))[0]

    # 確保輸出目錄存在
    os.makedirs(output_dir, exist_ok=True)
    print(f"  輸出目錄: {output_dir}")

    # 處理每個版本
    print(f"\n[2/4] 創建降噪器")
    print("-"*70)

    denoisers = {}
    for version in versions:
        try:
            denoiser = create_denoiser_from_config(
                version, config_dir, sample_rate, mode=mode, strength=strength,
                fft_size=fft_size)
            denoisers[version] = denoiser
            params = denoiser.get_params()
            print(f"  ✓ {version}: {params['name']}")
        except Exception as e:
            print(f"  ✗ {version}: Failed to create - {e}")

    if not denoisers:
        print("\nError: No denoisers were created successfully")
        return False

    # 降噪處理
    print(f"\n[3/4] 降噪處理")
    print("-"*70)

    results = {}
    for version, denoiser in denoisers.items():
        print(f"  處理 {version}...", end=' ', flush=True)

        try:
            start_time = time.time()

            # V3 系列支援 return_spp 獲取 SPP 時頻矩陣
            spp_matrix = None
            if version == 'V3' and hasattr(denoiser, 'denoise'):
                result = denoiser.denoise(audio, return_spp=True)
                if isinstance(result, tuple) and len(result) == 2:
                    enhanced, spp_matrix = result
                else:
                    enhanced = result
            else:
                enhanced = denoiser.denoise(audio)

            processing_time = time.time() - start_time

            # v1.5.1: 確保輸出長度與輸入一致（修復繪圖維度不匹配問題）
            if len(enhanced) != len(audio):
                length_diff = len(enhanced) - len(audio)
                if abs(length_diff) > 0:
                    # 如果長度不一致，進行修正
                    if len(enhanced) > len(audio):
                        # 輸出過長，截斷
                        enhanced = enhanced[:len(audio)]
                    else:
                        # 輸出過短，補零
                        enhanced = np.pad(enhanced, (0, len(audio) - len(enhanced)), mode='constant')

            # 計算實時率
            rtf = processing_time / duration

            results[version] = {
                'enhanced': enhanced,
                'processing_time': processing_time,
                'rtf': rtf,
                'spp_matrix': spp_matrix,  # None for non-V3 denoisers
                'hop_length': denoiser.processor.frame_shift,
            }

            print(f"✓ ({processing_time*1000:.1f} ms, RTF: {rtf:.3f})")

        except Exception as e:
            print(f"✗ Failed: {e}")

    # 保存輸出文件
    print(f"\n[4/6] 保存結果")
    print("-"*70)

    saved_count = 0
    for version, result in results.items():
        output_file = os.path.join(output_dir, f"{basename}_{version.lower()}.wav")

        try:
            write_audio(output_file, result['enhanced'], sample_rate)
            print(f"  ✓ {version}: {output_file}")
            saved_count += 1
        except Exception as e:
            print(f"  ✗ {version}: Failed to save - {e}")

    # 繪製波形圖
    print(f"\n[5/6] 生成波形對比圖")
    print("-"*70)

    try:
        plot_waveforms(audio, results, sample_rate, output_dir, basename)
    except Exception as e:
        print(f"  ✗ Failed to generate plot: {e}")
        if not MATPLOTLIB_AVAILABLE:
            print(f"  提示: 安裝 matplotlib 以生成波形圖: pip install matplotlib")

    # 繪製 SPP 時頻圖（V3 系列）
    print(f"\n[6/6] 生成 SPP 時頻圖")
    print("-"*70)

    spp_count = 0
    for version, result in results.items():
        if result.get('spp_matrix') is not None:
            try:
                spp_output_path = os.path.join(output_dir, f"{basename}_{version.lower()}_spp.png")
                # Use the actual frame_shift, not a hardcoded 10ms default.
                hop_length = result['hop_length']
                plot_spp_spectrogram(
                    result['spp_matrix'],
                    spp_output_path,
                    sample_rate=sample_rate,
                    hop_length=hop_length,
                    title=f'{version} SPP Time-Frequency Map'
                )
                print(f"  ✓ {version} SPP: {spp_output_path}")
                spp_count += 1
            except Exception as e:
                print(f"  ✗ {version} SPP: Failed - {e}")

    if spp_count == 0:
        print(f"  (沒有 V3 系列降噪器，跳過 SPP 圖生成)")

    # 總結
    print("\n" + "="*70)
    print("處理完成")
    print("="*70)
    print(f"成功處理: {saved_count}/{len(versions)} 個版本")
    print(f"輸出目錄: {os.path.abspath(output_dir)}")
    print("="*70)

    return saved_count > 0


def main():
    parser = argparse.ArgumentParser(
        description='音頻文件降噪處理工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 處理單個文件
  python process_audio.py input.wav

  # 指定輸出目錄
  python process_audio.py input.wav --output-dir ./output

  # 只使用 V3 系列
  python process_audio.py input.wav --versions V3 V3-2

  # 使用自定義配置
  python process_audio.py input.wav --config-dir ./my_configs

  # V3-2 強度預設 + 內容保留模式（僅影響 V3-2）
  python process_audio.py input.wav --versions V3-2 --nr-mode aggressive
  python process_audio.py music.wav --versions V3-2 --mode stationary
        """
    )

    parser.add_argument(
        'input_file',
        help='輸入音頻文件路徑 (.wav 格式)'
    )

    parser.add_argument(
        '--output-dir',
        default='./output',
        help='輸出目錄（默認: ./output）'
    )

    parser.add_argument(
        '--versions',
        nargs='+',
        default=['V1', 'V2', 'V3', 'V3-2'],
        choices=['V1', 'V2', 'V3', 'V3-2', 'V3-3'],
        help='要使用的版本（默認: V1 V2 V3 V3-2）'
    )

    parser.add_argument(
        '--config-dir',
        default=None,
        help='配置文件目錄（默認: ./config，相對於腳本目錄）'
    )

    parser.add_argument(
        '--nr-mode',
        default=None,
        choices=['mild', 'moderate', 'balanced', 'aggressive'],
        help='V3-2 強度預設（深度軸）：mild|moderate|balanced|aggressive（默認: balanced = base config）'
    )

    parser.add_argument(
        '--mode',
        default=None,
        choices=['full', 'stationary'],
        help='V3-2 內容保留模式（內容軸）：full|stationary（默認: full）。stationary 只移除穩態底噪，保留音樂/瞬態'
    )

    parser.add_argument(
        '--fft-size',
        type=int,
        default=None,
        help='No-padding grid override (256/512 @16kHz; 1024 @48kHz)',
    )

    args = parser.parse_args()

    # 如果沒有指定 config_dir，使用相對於腳本的路徑
    if args.config_dir is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        args.config_dir = os.path.join(script_dir, 'config')

    # 處理音頻文件
    success = process_audio_file(
        args.input_file,
        args.output_dir,
        args.versions,
        args.config_dir,
        mode=args.mode,
        strength=args.nr_mode,
        fft_size=args.fft_size,
    )

    # 返回退出碼
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
