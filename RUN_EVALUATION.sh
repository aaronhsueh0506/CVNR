#!/bin/bash
# Phase 3 評估運行腳本
#
# 使用方法:
#   chmod +x RUN_EVALUATION.sh
#   ./RUN_EVALUATION.sh

set -e  # 遇到錯誤立即退出

echo "========================================================================"
echo "Phase 3 優化評估流程"
echo "========================================================================"
echo ""

# 切換到項目目錄
cd "$(dirname "$0")"

echo "📁 當前目錄: $(pwd)"
echo ""

# Step 1: 重新生成降噪輸出（使用 SNR adaptive 配置）
echo "========================================================================"
echo "Step 1: 重新生成降噪輸出（SNR Adaptive 已啟用）"
echo "========================================================================"
echo ""
echo "⚠️  注意: 這將重新處理所有測試用例，可能需要較長時間"
echo ""
read -p "是否繼續? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]
then
    echo "已取消"
    exit 1
fi

if [ -f "regenerate_all_outputs.py" ]; then
    echo "開始重新生成..."
    python3 regenerate_all_outputs.py
    echo "✅ 降噪輸出已更新"
else
    echo "⚠️  未找到 regenerate_all_outputs.py，跳過此步驟"
    echo "   如果配置文件已更新，請確保重新生成降噪輸出"
fi

echo ""

# Step 2: 運行完整評估
echo "========================================================================"
echo "Step 2: 運行完整評估（Improvement, PESQ, STOI, LSD）"
echo "========================================================================"
echo ""

if [ -f "compute_improvement.py" ]; then
    python3 compute_improvement.py | tee evaluation_output.log
    echo ""
    echo "✅ 評估完成"
    echo "   報告: results/improvement_report.md"
    echo "   日誌: evaluation_output.log"
else
    echo "❌ 錯誤: 找不到 compute_improvement.py"
    exit 1
fi

echo ""

# Step 3: 生成 CSV 報告
echo "========================================================================"
echo "Step 3: 生成 CSV 報告（Methods × SNR 樞紐表）"
echo "========================================================================"
echo ""

if [ -f "tools/generate_csv_results.py" ]; then
    python3 tools/generate_csv_results.py
    echo "✅ CSV 報告已生成"
    echo "   位置: results/metrics_by_snr/"
elif [ -d "results/metrics_by_snr" ]; then
    echo "✅ CSV 已在 Step 2 中自動生成"
else
    echo "⚠️  未找到 CSV 生成腳本，跳過"
fi

echo ""

# Step 4: Clean 音頻保護測試
echo "========================================================================"
echo "Step 4: Clean 音頻保護測試"
echo "========================================================================"
echo ""

read -p "是否運行 Clean 音頻測試? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]
then
    if [ -f "tests/test_clean_audio.py" ]; then
        # 嘗試使用 pytest，如果不可用則直接運行
        if command -v pytest &> /dev/null; then
            pytest tests/test_clean_audio.py -v
        else
            echo "⚠️  pytest 不可用，使用直接運行模式"
            python3 tests/test_clean_audio.py
        fi
        echo "✅ Clean 音頻測試完成"
    else
        echo "❌ 錯誤: 找不到 tests/test_clean_audio.py"
    fi
else
    echo "跳過 Clean 音頻測試"
fi

echo ""

# Step 5: 生成可視化圖表（可選）
echo "========================================================================"
echo "Step 5: 生成可視化圖表（可選）"
echo "========================================================================"
echo ""

read -p "是否生成可視化圖表? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]
then
    if [ -f "results/plot_results.py" ]; then
        python3 results/plot_results.py
        echo "✅ 圖表已生成"
        echo "   位置: results/"
    else
        echo "⚠️  未找到繪圖腳本，跳過"
    fi
else
    echo "跳過圖表生成"
fi

echo ""

# 匯總
echo "========================================================================"
echo "✅ 評估流程完成！"
echo "========================================================================"
echo ""
echo "📊 查看結果:"
echo "   - Markdown 報告: results/improvement_report.md"
echo "   - CSV 數據: results/metrics_by_snr/*.csv"
echo "   - 圖表: results/*.png (如已生成)"
echo "   - 完整日誌: evaluation_output.log"
echo ""
echo "🔍 關鍵檢查項:"
echo "   1. STOI Δ 是否全部 >= 0 (或接近 0)"
echo "   2. V3-2/V3-3 的 STOI Δ 是否 >= +0.01"
echo "   3. V3-2/V3-3 在高 SNR (15dB) 的 PESQ 是否 > 2.3"
echo "   4. segSNR 改善量是否維持（下降不超過 1 dB）"
echo "   5. Clean 音頻測試是否全部通過"
echo ""
echo "📖 詳細文檔: PHASE3_COMPLETION.md"
echo ""
