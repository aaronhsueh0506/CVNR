#!/usr/bin/env bash
# 監控 Optuna 優化進度

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NR_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RESULTS_DIR="${NR_OPTUNA_RESULTS_DIR:-$NR_ROOT/results/optimization}"

if [ ! -d "$RESULTS_DIR" ]; then
    echo "尚無 Optuna 結果目錄: $RESULTS_DIR"
    exit 0
fi
cd "$RESULTS_DIR"

echo "=========================================="
echo "Optuna 優化進度監控"
echo "=========================================="
echo ""

for VERSION in V3 V3-2 V3-3 V3-4 V4; do
    # 找到最新的目錄
    LATEST_DIR=$(ls -td ${VERSION}_* 2>/dev/null | head -1)

    if [ -z "$LATEST_DIR" ]; then
        echo "$VERSION: 尚未開始"
        continue
    fi

    # 統計完成的 trials
    COMPLETED=$(ls "$LATEST_DIR"/trial_*.json 2>/dev/null | wc -l | tr -d ' ')

    # 找到最佳 PESQ
    if [ "$COMPLETED" -gt 0 ]; then
        BEST_PESQ=$(cat "$LATEST_DIR"/trial_*.json 2>/dev/null | grep -o '"pesq_score": [0-9.-]*' | cut -d':' -f2 | sort -rn | head -1)
        echo "$VERSION: $COMPLETED/100 trials 完成, 最佳 PESQ: $BEST_PESQ"
    else
        echo "$VERSION: 0/100 trials 完成"
    fi
done

echo ""
echo "=========================================="

# 檢查進程是否仍在運行
RUNNING=$(ps aux | grep "parameter_optimizer" | grep -v grep | wc -l | tr -d ' ')
echo "正在運行的進程: $RUNNING"
