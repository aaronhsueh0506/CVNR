#!/bin/bash
# 快速檢查優化進度

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPT_DIR="$PROJECT_DIR/results/optimization"

echo "=========================================="
echo "SPP 參數優化進度"
echo "=========================================="
echo ""

# 找到所有優化目錄
for dir in "$OPT_DIR"/V*_*/; do
    if [ -d "$dir" ]; then
        VERSION=$(basename "$dir" | cut -d'_' -f1)
        TIMESTAMP=$(basename "$dir" | cut -d'_' -f2-3)
        COUNT=$(ls "$dir"eval_*.json 2>/dev/null | wc -l | tr -d ' ')

        echo "[$VERSION] ($TIMESTAMP)"
        echo "  試驗數: $COUNT"

        # 找出最佳結果
        if [ "$COUNT" -gt 0 ]; then
            BEST_FILE=$(ls -t "$dir"eval_*.json 2>/dev/null | head -1)
            BEST_SCORE=$(grep "weighted_score" "$BEST_FILE" | grep -o '[0-9.]*')
            BEST_PESQ=$(grep '"pesq"' "$BEST_FILE" | grep -o '[0-9.-]*' | head -1)
            echo "  最新分數: $BEST_SCORE"
            echo "  最新 PESQ: $BEST_PESQ"
        fi

        # 檢查是否有 summary（已完成）
        if [ -f "${dir}summary.json" ]; then
            FINAL_SCORE=$(grep "best_score" "${dir}summary.json" | grep -o '[0-9.]*')
            echo "  ✓ 已完成! 最佳分數: $FINAL_SCORE"
        fi
        echo ""
    fi
done

# 檢查是否還有運行中的進程
RUNNING=$(ps aux | grep parameter_optimizer | grep -v grep | wc -l | tr -d ' ')
if [ "$RUNNING" -gt 0 ]; then
    echo "狀態: 優化進行中 ($RUNNING 個進程)"
else
    echo "狀態: 無運行中的優化任務"
fi
echo ""
