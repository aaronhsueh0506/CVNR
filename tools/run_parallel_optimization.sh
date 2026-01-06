#!/bin/bash
# 並行運行多版本參數優化
# 使用方法: ./run_parallel_optimization.sh [population] [generations]
# 例如: ./run_parallel_optimization.sh 50 30

# 獲取參數（默認值：population=50, generations=30）
POPULATION=${1:-50}
GENERATIONS=${2:-30}

echo "=================================="
echo "並行參數優化"
echo "=================================="
echo "種群大小: $POPULATION"
echo "迭代代數: $GENERATIONS"
echo "優化版本: V3, V3-2, V3-3, V3-4"
echo "預估時間: ~6-7 小時/版本（並行）"
echo "=================================="
echo ""

# 獲取腳本所在目錄的父目錄（項目根目錄）
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$( cd "$SCRIPT_DIR/.." && pwd )"

# 切換到項目目錄
cd "$PROJECT_DIR"

# 創建日志目錄
LOG_DIR="$PROJECT_DIR/results/optimization_logs"
mkdir -p "$LOG_DIR"

# 啟動時間
START_TIME=$(date +%s)

# 定義優化函數
run_optimization() {
    VERSION=$1
    LOGFILE="$LOG_DIR/${VERSION}_$(date +%Y%m%d_%H%M%S).log"

    echo "[$(date +'%Y-%m-%d %H:%M:%S')] 啟動 $VERSION 優化..." | tee -a "$LOGFILE"

    python3 tools/parameter_optimizer.py \
        --version "$VERSION" \
        --population "$POPULATION" \
        --generations "$GENERATIONS" \
        --weights 0.5 0.3 0.2 \
        2>&1 | tee -a "$LOGFILE"

    EXIT_CODE=${PIPESTATUS[0]}

    if [ $EXIT_CODE -eq 0 ]; then
        echo "[$(date +'%Y-%m-%d %H:%M:%S')] ✓ $VERSION 優化完成" | tee -a "$LOGFILE"
    else
        echo "[$(date +'%Y-%m-%d %H:%M:%S')] ✗ $VERSION 優化失敗 (exit code: $EXIT_CODE)" | tee -a "$LOGFILE"
    fi

    return $EXIT_CODE
}

# 並行運行 4 個版本的優化
echo "開始並行優化..."
echo ""

run_optimization "V3" &
PID_V3=$!

run_optimization "V3-2" &
PID_V3_2=$!

run_optimization "V3-3" &
PID_V3_3=$!

run_optimization "V3-4" &
PID_V3_4=$!

# 等待所有後台任務完成
echo "等待所有優化任務完成..."
echo "  V3 (PID: $PID_V3)"
echo "  V3-2 (PID: $PID_V3_2)"
echo "  V3-3 (PID: $PID_V3_3)"
echo "  V3-4 (PID: $PID_V3_4)"
echo ""

wait $PID_V3
STATUS_V3=$?

wait $PID_V3_2
STATUS_V3_2=$?

wait $PID_V3_3
STATUS_V3_3=$?

wait $PID_V3_4
STATUS_V3_4=$?

# 計算總時間
END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))
HOURS=$((ELAPSED / 3600))
MINUTES=$(((ELAPSED % 3600) / 60))
SECONDS=$((ELAPSED % 60))

# 顯示結果摘要
echo ""
echo "=================================="
echo "優化完成"
echo "=================================="
echo "總耗時: ${HOURS}h ${MINUTES}m ${SECONDS}s"
echo ""
echo "狀態摘要:"
[ $STATUS_V3 -eq 0 ] && echo "  ✓ V3 成功" || echo "  ✗ V3 失敗"
[ $STATUS_V3_2 -eq 0 ] && echo "  ✓ V3-2 成功" || echo "  ✗ V3-2 失敗"
[ $STATUS_V3_3 -eq 0 ] && echo "  ✓ V3-3 成功" || echo "  ✗ V3-3 失敗"
[ $STATUS_V3_4 -eq 0 ] && echo "  ✓ V3-4 成功" || echo "  ✗ V3-4 失敗"
echo ""
echo "日誌文件: $LOG_DIR/"
echo "結果文件: $PROJECT_DIR/results/"
echo "=================================="

# 退出碼：任何一個失敗則返回 1
if [ $STATUS_V3 -ne 0 ] || [ $STATUS_V3_2 -ne 0 ] || [ $STATUS_V3_3 -ne 0 ] || [ $STATUS_V3_4 -ne 0 ]; then
    exit 1
else
    exit 0
fi
