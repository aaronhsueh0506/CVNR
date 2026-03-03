#!/bin/bash
# 48kHz 16bit mono PCM (raw) → WAV
# 用法: bash tools/pcm_to_wav.sh <input_pcm_dir> <output_wav_dir>
#
# 將 RNNoise 輸出的 raw PCM 轉回 wav

INPUT_DIR="${1:?用法: bash tools/pcm_to_wav.sh <input_pcm_dir> <output_wav_dir>}"
OUTPUT_DIR="${2:?用法: bash tools/pcm_to_wav.sh <input_pcm_dir> <output_wav_dir>}"

mkdir -p "$OUTPUT_DIR"

count=0
total=$(ls "$INPUT_DIR"/*.pcm 2>/dev/null | wc -l | tr -d ' ')
echo "=== PCM → WAV (48kHz 16bit mono) ==="
echo "Input:  $INPUT_DIR ($total files)"
echo "Output: $OUTPUT_DIR"
echo "======================================"

for pcm in "$INPUT_DIR"/*.pcm; do
    fname=$(basename "$pcm" .pcm)
    ffmpeg -y -f s16le -ar 48000 -ac 1 -i "$pcm" "$OUTPUT_DIR/${fname}.wav" 2>/dev/null
    count=$((count + 1))
    if [ $((count % 100)) -eq 0 ]; then
        echo "  [$count/$total]"
    fi
done

echo "完成: $count files"
