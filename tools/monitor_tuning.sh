#!/bin/bash
# 監控參數調整進度

cd "$(dirname "$0")/.."

clear
echo "========================================"
echo "V3-3 參數調整進度監控"
echo "========================================"
echo "當前時間: $(date +'%Y-%m-%d %H:%M:%S')"
echo ""

# 檢查進程
RUNNING=$(ps aux | grep "single_param_tuner.py" | grep -v grep | wc -l | tr -d ' ')
echo "運行狀態: "
if [ "$RUNNING" -gt 0 ]; then
    echo "  ✓ 正在運行"
else
    echo "  ⚠️  未運行"
fi
echo ""

# 檢查結果文件
RESULT_DIR="results/param_tuning/V3-3"
if [ -d "$RESULT_DIR" ]; then
    echo "已完成的參數測試:"
    for file in "$RESULT_DIR"/*_tuning.json; do
        if [ -f "$file" ]; then
            PARAM=$(basename "$file" _tuning.json)
            COUNT=$(jq '.results | length' "$file" 2>/dev/null || echo "?")
            echo "  ✓ $PARAM: $COUNT 個測試值"
        fi
    done
else
    echo "  尚無結果"
fi

echo ""
echo "========================================"
echo "日誌最新內容:"
echo "========================================"
tail -20 /tmp/complete_tuning.log 2>/dev/null || echo "無日誌"

echo ""
echo "========================================"
