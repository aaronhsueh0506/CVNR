#!/bin/bash
# 自動監控優化進度，完成後立即分析

TIMESTAMP="20260105_230515"
VERSIONS=("V3" "V3-2" "V3-3" "V3-4")
TOTAL_EVALS=300
CHECK_INTERVAL=60  # 每60秒檢查一次

echo "========================================="
echo "自動監控與分析系統"
echo "========================================="
echo "時間戳: $TIMESTAMP"
echo "檢查間隔: ${CHECK_INTERVAL}秒"
echo "========================================="
echo ""

while true; do
    # 檢查運行中的進程
    RUNNING=$(ps aux | grep "parameter_optimizer.py" | grep -v grep | wc -l | tr -d ' ')

    # 統計完成進度
    ALL_DONE=true
    TOTAL_COUNT=0

    for VERSION in "${VERSIONS[@]}"; do
        RESULT_DIR="/Users/mingyu/Desktop/Code/公司/speech_denoise/results/optimization/${VERSION}_${TIMESTAMP}"
        if [ -d "$RESULT_DIR" ]; then
            COUNT=$(ls "$RESULT_DIR"/eval_*.json 2>/dev/null | wc -l | tr -d ' ')
            TOTAL_COUNT=$((TOTAL_COUNT + COUNT))

            if [ "$COUNT" -lt "$TOTAL_EVALS" ]; then
                ALL_DONE=false
            fi
        else
            ALL_DONE=false
        fi
    done

    AVG_COUNT=$((TOTAL_COUNT / 4))

    echo "[$(date +'%Y-%m-%d %H:%M:%S')] 進度: $AVG_COUNT/$TOTAL_EVALS | 運行中: $RUNNING"

    # 如果全部完成，開始分析
    if [ "$RUNNING" -eq 0 ] && [ "$ALL_DONE" = true ]; then
        echo ""
        echo "========================================="
        echo "✓ 優化已完成！開始分析結果..."
        echo "========================================="
        echo ""

        cd /Users/mingyu/Desktop/Code/公司/speech_denoise

        # 運行分析腳本
        python3 tools/analyze_optimization_results.py --timestamp "$TIMESTAMP"

        if [ $? -eq 0 ]; then
            echo ""
            echo "========================================="
            echo "✓ 分析完成！"
            echo "========================================="
            echo ""
            echo "結果文件："
            echo "  - results/optimization/optimization_report_${TIMESTAMP}.md"
            echo "  - results/optimization/V3_${TIMESTAMP}/V3_optimized.yaml"
            echo "  - results/optimization/V3-2_${TIMESTAMP}/V3-2_optimized.yaml"
            echo "  - results/optimization/V3-3_${TIMESTAMP}/V3-3_optimized.yaml"
            echo "  - results/optimization/V3-4_${TIMESTAMP}/V3-4_optimized.yaml"
            echo ""
        else
            echo "❌ 分析失敗，請手動檢查"
        fi

        break
    fi

    # 等待下一次檢查
    sleep $CHECK_INTERVAL
done

echo "監控結束"
