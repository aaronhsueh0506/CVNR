#!/bin/bash
# 監控優化進度

TIMESTAMP="20260105_230515"
VERSIONS=("V3" "V3-2" "V3-3" "V3-4")
TOTAL_EVALS=300

echo "========================================="
echo "優化進度監控"
echo "========================================="
echo ""

while true; do
    clear
    echo "========================================="
    echo "優化進度監控 - $(date +'%Y-%m-%d %H:%M:%S')"
    echo "========================================="
    echo ""

    # 檢查運行中的進程
    RUNNING=$(ps aux | grep "parameter_optimizer.py" | grep -v grep | wc -l | tr -d ' ')
    echo "運行中的優化器: $RUNNING / 4"
    echo ""

    # 檢查每個版本的進度
    echo "版本進度 (已完成 / 總計):"
    echo "-------------------"

    ALL_DONE=true
    for VERSION in "${VERSIONS[@]}"; do
        RESULT_DIR="/Users/mingyu/Desktop/Code/公司/speech_denoise/results/optimization/${VERSION}_${TIMESTAMP}"
        if [ -d "$RESULT_DIR" ]; then
            COUNT=$(ls "$RESULT_DIR"/eval_*.json 2>/dev/null | wc -l | tr -d ' ')
            PERCENT=$((COUNT * 100 / TOTAL_EVALS))
            printf "%-6s: %3d / %3d (%3d%%)\n" "$VERSION" "$COUNT" "$TOTAL_EVALS" "$PERCENT"

            if [ "$COUNT" -lt "$TOTAL_EVALS" ]; then
                ALL_DONE=false
            fi
        else
            echo "$VERSION: 未啟動"
            ALL_DONE=false
        fi
    done

    echo ""

    # 如果全部完成，退出
    if [ "$RUNNING" -eq 0 ] || [ "$ALL_DONE" = true ]; then
        echo "========================================="
        echo "✓ 優化已完成！"
        echo "========================================="
        break
    fi

    # 估算剩餘時間
    if [ "$RUNNING" -gt 0 ]; then
        # 計算平均進度
        TOTAL_COUNT=0
        for VERSION in "${VERSIONS[@]}"; do
            RESULT_DIR="/Users/mingyu/Desktop/Code/公司/speech_denoise/results/optimization/${VERSION}_${TIMESTAMP}"
            if [ -d "$RESULT_DIR" ]; then
                COUNT=$(ls "$RESULT_DIR"/eval_*.json 2>/dev/null | wc -l | tr -d ' ')
                TOTAL_COUNT=$((TOTAL_COUNT + COUNT))
            fi
        done

        AVG_COUNT=$((TOTAL_COUNT / 4))
        if [ "$AVG_COUNT" -gt 0 ]; then
            REMAINING=$((TOTAL_EVALS - AVG_COUNT))
            # 假設每評估 15 秒
            EST_SECONDS=$((REMAINING * 15))
            EST_MINUTES=$((EST_SECONDS / 60))
            echo "預估剩餘時間: ~$EST_MINUTES 分鐘"
        fi
    fi

    echo ""
    echo "按 Ctrl+C 退出監控 (優化將繼續在後台運行)"
    echo ""

    # 每 30 秒更新一次
    sleep 30
done

echo ""
echo "結果保存在: results/optimization/"
echo "日誌文件: results/optimization_logs/"
