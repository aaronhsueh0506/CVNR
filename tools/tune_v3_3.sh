#!/bin/bash
# V3-3 參數調整腳本
# 逐個參數調整，觀察影響後統整

echo "========================================"
echo "V3-3 單參數調整工具"
echo "========================================"
echo "策略: 逐個參數測試，觀察影響後統整"
echo "預計測試: 5+4+5+4+4 = 22 個配置"
echo "預計時間: ~22 × 2分鐘 = 44分鐘"
echo "========================================"
echo ""

# 調整順序：從影響最大的參數開始
PARAMS=(
    "alpha_xi"          # SPP 平滑係數 (5個值)
    "q"                 # 語音先驗概率 (4個值)
    "g_min_db"          # 最小增益 (5個值)
    "alpha_g"           # 增益平滑 (4個值)
    "base_g_min_db"     # SNR自適應基準 (4個值)
)

echo "調整順序:"
for i in "${!PARAMS[@]}"; do
    echo "  $((i+1)). ${PARAMS[$i]}"
done
echo ""

read -p "按 Enter 開始調整，或 Ctrl+C 取消..."

# 逐個調整
for PARAM in "${PARAMS[@]}"; do
    echo ""
    echo "========================================"
    echo "正在調整: $PARAM"
    echo "========================================"

    python3 tools/single_param_tuner.py \
        --version V3-3 \
        --params "$PARAM"

    if [ $? -ne 0 ]; then
        echo "❌ 調整 $PARAM 失敗"
        exit 1
    fi

    echo ""
    echo "✓ $PARAM 調整完成"
    echo ""
    read -p "按 Enter 繼續下一個參數..."
done

echo ""
echo "========================================"
echo "✓ 所有參數調整完成！"
echo "========================================"
echo ""
echo "查看報告:"
echo "  cat results/param_tuning/V3-3/V3-3_tuning_report.md"
echo ""
