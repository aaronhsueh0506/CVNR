#!/bin/bash
# 監控優化進度
#
# 用法:
#   ./tools/monitor_optimization.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_DIR/results/optimization/logs"
OPT_DIR="$PROJECT_DIR/results/optimization"

echo "=========================================="
echo "SPP 參數優化 - 進度監控"
echo "=========================================="

# 找到最新的時間戳
LATEST_TIMESTAMP=$(ls -t "$LOG_DIR"/*.log 2>/dev/null | head -1 | sed 's/.*_\([0-9]*_[0-9]*\)\.log/\1/')

if [ -z "$LATEST_TIMESTAMP" ]; then
    echo "未找到運行中的優化任務"
    exit 1
fi

echo "最新時間戳: $LATEST_TIMESTAMP"
echo ""

VERSIONS=("V3" "V3-2" "V3-3" "V3-4" "V4")

for VERSION in "${VERSIONS[@]}"; do
    LOG_FILE="$LOG_DIR/${VERSION}_${LATEST_TIMESTAMP}.log"
    PID_FILE="$LOG_DIR/${VERSION}_${LATEST_TIMESTAMP}.pid"

    echo "----------------------------------------"
    echo "[$VERSION]"

    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "  狀態: 運行中 (PID: $PID)"
        else
            echo "  狀態: 已完成"
        fi
    else
        echo "  狀態: 未知"
    fi

    if [ -f "$LOG_FILE" ]; then
        # 統計進度
        TOTAL=$(grep -c "測試參數:" "$LOG_FILE" 2>/dev/null || echo "0")
        BEST_SCORE=$(grep "最佳加權分數:" "$LOG_FILE" 2>/dev/null | tail -1 | awk '{print $2}' || echo "N/A")
        BEST_PESQ=$(grep "PESQ 改善:" "$LOG_FILE" 2>/dev/null | tail -1 | awk '{print $3}' || echo "N/A")

        echo "  完成試驗: $TOTAL"
        echo "  最佳分數: $BEST_SCORE"
        echo "  最佳 PESQ: $BEST_PESQ"

        # 顯示最後幾行
        echo "  最新進度:"
        tail -3 "$LOG_FILE" | sed 's/^/    /'
    else
        echo "  日誌文件不存在"
    fi

    echo ""
done

# 檢查結果目錄
echo "----------------------------------------"
echo "結果目錄:"
ls -la "$OPT_DIR" 2>/dev/null | grep "^d" | grep -v "logs" | head -10 || echo "  (無)"
echo ""

# 顯示已完成的優化
echo "已完成的優化:"
for dir in "$OPT_DIR"/V*_*/; do
    if [ -f "${dir}summary.json" ]; then
        VERSION=$(basename "$dir" | cut -d'_' -f1)
        SCORE=$(grep "best_score" "${dir}summary.json" 2>/dev/null | head -1 | grep -o '[0-9.]*' || echo "N/A")
        echo "  $VERSION: $SCORE"
    fi
done
