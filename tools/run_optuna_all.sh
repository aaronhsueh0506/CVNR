#!/bin/bash
# 依序執行所有版本的 Optuna 優化

cd /Users/mingyu/Desktop/Code/公司/speech_denoise

N_TRIALS=${1:-100}  # 默認 100 trials

echo "=========================================="
echo "開始 Optuna 貝葉斯優化"
echo "每版本 $N_TRIALS trials"
echo "=========================================="

VERSIONS=("V3" "V3-2" "V3-3" "V3-4" "V4")

for VERSION in "${VERSIONS[@]}"; do
    echo ""
    echo "=========================================="
    echo "開始優化 $VERSION ($(date))"
    echo "=========================================="

    LOG_FILE="results/optimization/${VERSION}_optuna_$(date +%Y%m%d_%H%M%S).log"

    python3 tools/parameter_optimizer.py \
        --version "$VERSION" \
        --method optuna \
        --n_trials "$N_TRIALS" \
        2>&1 | tee "$LOG_FILE"

    echo ""
    echo "$VERSION 完成 ($(date))"
done

echo ""
echo "=========================================="
echo "所有版本優化完成!"
echo "=========================================="
