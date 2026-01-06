#!/bin/bash
# 完整參數調整 - 無需互動
# 自動運行所有參數測試並生成最終報告

cd "$(dirname "$0")/.."

echo "========================================"
echo "V3-3 完整參數調整"
echo "========================================"
echo "開始時間: $(date +'%Y-%m-%d %H:%M:%S')"
echo "預計時間: ~44 分鐘"
echo "========================================"
echo ""

# 參數列表
PARAMS=("alpha_xi" "q" "g_min_db" "alpha_g" "base_g_min_db")

# 計數器
TOTAL=${#PARAMS[@]}
CURRENT=0

# 逐個測試
for PARAM in "${PARAMS[@]}"; do
    CURRENT=$((CURRENT + 1))
    echo ""
    echo "========================================"
    echo "[$CURRENT/$TOTAL] 調整參數: $PARAM"
    echo "========================================"

    python3 tools/single_param_tuner.py \
        --version V3-3 \
        --params "$PARAM"

    if [ $? -ne 0 ]; then
        echo "❌ 調整 $PARAM 失敗"
        exit 1
    fi

    echo "✓ $PARAM 完成"
done

echo ""
echo "========================================"
echo "✓ 所有參數調整完成！"
echo "========================================"
echo "完成時間: $(date +'%Y-%m-%d %H:%M:%S')"
echo ""
echo "報告位置:"
echo "  results/param_tuning/V3-3/V3-3_tuning_report.md"
echo "========================================"
