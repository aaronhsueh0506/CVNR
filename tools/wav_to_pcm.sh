#!/bin/bash
# wav → 48kHz 16bit mono PCM (raw)
# 用法: bash tools/wav_to_pcm.sh <input_wav_dir> <output_pcm_dir>
#
# RNNoise 需要 48kHz 16-bit signed little-endian mono raw PCM
# VCTK 原檔已是 48kHz，直接去掉 wav header 即可

INPUT_DIR="${1:?用法: bash tools/wav_to_pcm.sh <input_wav_dir> <output_pcm_dir>}"
OUTPUT_DIR="${2:?用法: bash tools/wav_to_pcm.sh <input_wav_dir> <output_pcm_dir>}"

mkdir -p "$OUTPUT_DIR"

count=0
total=$(ls "$INPUT_DIR"/*.wav 2>/dev/null | wc -l | tr -d ' ')
echo "=== WAV → PCM (48kHz 16bit mono) ==="
echo "Input:  $INPUT_DIR ($total files)"
echo "Output: $OUTPUT_DIR"
echo "======================================"

for wav in "$INPUT_DIR"/*.wav; do
    fname=$(basename "$wav" .wav)
    ffmpeg -y -i "$wav" -f s16le -acodec pcm_s16le -ar 48000 -ac 1 "$OUTPUT_DIR/${fname}.pcm" 2>/dev/null
    count=$((count + 1))
    if [ $((count % 100)) -eq 0 ]; then
        echo "  [$count/$total]"
    fi
done

echo "完成: $count files"
