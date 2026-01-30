"""
RNNoise ONNX 匯出 — 轉成逐幀串流推論的靜態圖

流程:
  1. 載入 .pth checkpoint
  2. 包裝成 streaming forward (輸入 3 frame → 輸出 1 frame)
  3. torch.onnx.export 靜態 shape
  4. onnxsim 簡化 (合併冗餘 slice/reshape)

用法:
    python export_onnx.py --model output/rnnoise_best.pth --output rnnoise.onnx
"""

import argparse
import torch
import torch.nn as nn

from train import RNNoiseModel, N_BANDS

# ============================================================
# Streaming Wrapper (靜態圖, 逐幀推論)
# ============================================================

class RNNoiseStreaming(nn.Module):
    """
    將訓練模型包裝成串流推論格式 (消除 Transpose):
    - Conv1d(k=3) 對 3 frame 等價於 Linear(n_bands*3 → cond_size)
    - Conv1d(k=1) 等價於 Linear(cond_size → gru_size)
    - 權重從訓練模型的 Conv1d 重排而來，數值完全一致
    - GRU hidden states 作為顯式輸入/輸出
    """
    def __init__(self, model: RNNoiseModel):
        super().__init__()
        self.gru_size = model.gru_size
        n_bands = model.n_bands

        # Conv1d(k=3) → Linear: weight (out, in, 3) → (out, in*3)
        conv1_w = model.conv1.weight.data    # (cond, n_bands, 3)
        conv1_b = model.conv1.bias.data      # (cond,)
        cond_size = conv1_w.shape[0]
        self.fc1 = nn.Linear(n_bands * 3, cond_size)
        self.fc1.weight.data = conv1_w.reshape(cond_size, -1)
        self.fc1.bias.data = conv1_b

        # Conv1d(k=1) → Linear: weight (out, in, 1) → (out, in)
        conv2_w = model.conv2.weight.data    # (gru, cond, 1)
        conv2_b = model.conv2.bias.data      # (gru,)
        gru_size = conv2_w.shape[0]
        self.fc2 = nn.Linear(cond_size, gru_size)
        self.fc2.weight.data = conv2_w.squeeze(-1)
        self.fc2.bias.data = conv2_b

        # GRU 與 output dense 直接搬
        self.gru1 = model.gru1
        self.gru2 = model.gru2
        self.gru3 = model.gru3
        self.dense_out = model.dense_out

    def forward(self, x, h1, h2, h3):
        """
        x:  (1, 3, n_bands) — 最近 3 frame 的 ERB log energy
        h1: (1, 1, gru_size)
        h2: (1, 1, gru_size)
        h3: (1, 1, gru_size)
        回傳: gains (1, 1, n_bands), h1_out, h2_out, h3_out
        """
        # Conv → Linear (無 Transpose): (1,3,18) → flatten → (1,1,54) → fc1 → tanh → fc2 → tanh
        conv_out = torch.tanh(self.fc1(x.reshape(1, 1, -1)))   # (1, 1, cond)
        conv_out = torch.tanh(self.fc2(conv_out))               # (1, 1, gru_size)

        # 3 層 GRU
        gru1_out, h1_out = self.gru1(conv_out, h1)
        gru2_out, h2_out = self.gru2(gru1_out, h2)
        gru3_out, h3_out = self.gru3(gru2_out, h3)

        # Concat + output (在同一個 dim 上, 無需 transpose)
        cat = torch.cat([conv_out, gru1_out, gru2_out, gru3_out], dim=-1)
        gains = torch.sigmoid(self.dense_out(cat))  # (1, 1, n_bands)

        return gains, h1_out, h2_out, h3_out

# ============================================================
# 圖簡化: 移除 no-op Transpose / Squeeze / Constant
# ============================================================

def _remove_noop_transposes(model):
    """
    移除 seq=1, batch=1 下冗餘的 Transpose 和 Squeeze 節點。
    將被移除節點的輸出直接接到其輸入上。
    """
    import onnx

    graph = model.graph
    remove_ops = {'Transpose', 'Squeeze'}
    removed = []

    # 建立 output→node 和 input 依賴表
    output_map = {}  # tensor_name → producing node
    for node in graph.node:
        for out in node.output:
            output_map[out] = node

    to_remove = []
    rename = {}  # old_output → replacement_input

    for node in graph.node:
        if node.op_type == 'Transpose' and len(node.input) == 1:
            # Transpose perm=[1,0,2] on shape (1,1,N) 是 no-op
            rename[node.output[0]] = node.input[0]
            to_remove.append(node)
            removed.append(node.op_type)
        elif node.op_type == 'Squeeze':
            # Squeeze dim=0 on GRU output (1,1,1,N) → (1,1,N) 保留
            # 但如果輸出被 Transpose 消費而 Transpose 已被移除, 可以 chain
            pass

    # 套用 rename: 所有引用被移除節點 output 的地方改指向其 input
    # 需要遞迴 resolve (A→B→C 的情況)
    def resolve(name):
        while name in rename:
            name = rename[name]
        return name

    for node in graph.node:
        for i in range(len(node.input)):
            node.input[i] = resolve(node.input[i])

    # 也更新 graph outputs
    for out in graph.output:
        out.name = resolve(out.name)

    # 移除節點
    for node in to_remove:
        graph.node.remove(node)

    # 移除孤立的 Constant 節點 (被 Squeeze 用的 axis 常數)
    used_inputs = set()
    for node in graph.node:
        for inp in node.input:
            used_inputs.add(inp)
    for inp in graph.output:
        used_inputs.add(inp.name)

    orphans = [n for n in graph.node
               if n.op_type == 'Constant' and
               all(o not in used_inputs for o in n.output)]
    for node in orphans:
        graph.node.remove(node)
        removed.append('Constant')

    if removed:
        from collections import Counter
        print(f"  移除的節點: {dict(Counter(removed))}")

    return model

# ============================================================
# 匯出
# ============================================================

def export(args):
    # 載入訓練好的模型
    ckpt = torch.load(args.model, map_location='cpu', weights_only=False)
    model = RNNoiseModel(n_bands=N_BANDS, cond_size=64, gru_size=128)
    model.load_state_dict(ckpt['state_dict'])
    model.eval()

    # 包裝成 streaming
    streaming = RNNoiseStreaming(model)
    streaming.eval()

    gru_size = model.gru_size

    # Dummy inputs (全部靜態 shape)
    x  = torch.randn(1, 3, N_BANDS)
    h1 = torch.zeros(1, 1, gru_size)
    h2 = torch.zeros(1, 1, gru_size)
    h3 = torch.zeros(1, 1, gru_size)

    # 匯出 ONNX
    raw_path = args.output.replace('.onnx', '_raw.onnx') if args.simplify else args.output

    torch.onnx.export(
        streaming,
        (x, h1, h2, h3),
        raw_path,
        input_names=['input', 'h1_in', 'h2_in', 'h3_in'],
        output_names=['gains', 'h1_out', 'h2_out', 'h3_out'],
        opset_version=17,
        do_constant_folding=True,
    )
    print(f"ONNX 匯出完成: {raw_path}")

    # 手動簡化: 移除冗餘 Transpose / Squeeze (seq=1,batch=1 下皆為 no-op)
    if args.simplify:
        try:
            import onnx

            model_onnx = onnx.load(raw_path)
            n_before = len(model_onnx.graph.node)

            model_onnx = _remove_noop_transposes(model_onnx)

            onnx.save(model_onnx, args.output)
            n_after = len(model_onnx.graph.node)
            print(f"簡化完成: {args.output}")
            print(f"  節點數: {n_before} → {n_after} (減少 {n_before - n_after})")
        except ImportError:
            print("需要安裝 onnx: pip install onnx")
            return

        # 刪除中間檔
        import os
        if os.path.exists(raw_path) and raw_path != args.output:
            os.remove(raw_path)

    # 驗證輸出一致性
    if args.verify:
        verify_output(streaming, args.output, x, h1, h2, h3)

def verify_output(streaming, onnx_path, x, h1, h2, h3):
    """比較 PyTorch 和 ONNX 輸出是否一致"""
    try:
        import onnxruntime as ort
        import numpy as np

        with torch.no_grad():
            pt_gains, pt_h1, pt_h2, pt_h3 = streaming(x, h1, h2, h3)

        sess = ort.InferenceSession(onnx_path)
        ort_out = sess.run(None, {
            'input':  x.numpy(),
            'h1_in':  h1.numpy(),
            'h2_in':  h2.numpy(),
            'h3_in':  h3.numpy(),
        })

        diff = np.abs(pt_gains.numpy() - ort_out[0]).max()
        print(f"  PyTorch vs ONNX 最大誤差: {diff:.8f}")
        if diff < 1e-5:
            print("  ✓ 驗證通過")
        else:
            print("  ⚠ 誤差偏大，請檢查")
    except ImportError:
        print("需要安裝 onnxruntime 來驗證: pip install onnxruntime")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='RNNoise ONNX 匯出')
    parser.add_argument('--model', required=True, help='訓練好的 .pth 檔')
    parser.add_argument('--output', default='rnnoise.onnx', help='輸出 .onnx 路徑')
    parser.add_argument('--simplify', action='store_true', default=True,
                        help='使用 onnxsim 簡化 (預設開啟)')
    parser.add_argument('--no-simplify', dest='simplify', action='store_false')
    parser.add_argument('--verify', action='store_true', help='驗證 ONNX 輸出一致性')
    export(parser.parse_args())
