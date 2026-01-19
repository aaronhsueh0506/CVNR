#!/bin/bash
# 並行運行所有版本的參數優化
#
# 用法:
#   ./tools/run_parallel_optimization.sh [n_trials]
#   默認 n_trials = 30

set -e

N_TRIALS=${1:-30}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_DIR/results/optimization/logs"

mkdir -p "$LOG_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)

echo "=========================================="
echo "SPP 參數優化 - 並行執行"
echo "=========================================="
echo "試驗次數: $N_TRIALS"
echo "時間戳: $TIMESTAMP"
echo "日誌目錄: $LOG_DIR"
echo "=========================================="

cd "$PROJECT_DIR"

# 順序運行所有版本（避免文件衝突）
VERSIONS=("V3" "V3-2" "V3-3" "V3-4" "V4")
TOTAL_VERSIONS=${#VERSIONS[@]}
CURRENT=0

for VERSION in "${VERSIONS[@]}"; do
    CURRENT=$((CURRENT + 1))
    LOG_FILE="$LOG_DIR/${VERSION}_${TIMESTAMP}.log"
    echo ""
    echo "[$CURRENT/$TOTAL_VERSIONS] 啟動 $VERSION 優化..."
    echo "  日誌: $LOG_FILE"

    python3 tools/parameter_optimizer.py \
        --version "$VERSION" \
        --method random \
        --n_trials "$N_TRIALS" \
        2>&1 | tee "$LOG_FILE"

    # 檢查結果
    if [ $? -eq 0 ]; then
        echo "  ✓ $VERSION 優化完成"
    else
        echo "  ✗ $VERSION 優化失敗"
    fi
done

echo ""

echo ""
echo "=========================================="
echo "所有優化任務完成！"
echo "=========================================="
echo ""
echo "結果目錄: $PROJECT_DIR/results/optimization/"
echo ""
echo "分析結果:"
echo "  python3 tools/analyze_optimization_results.py --timestamp $TIMESTAMP"
