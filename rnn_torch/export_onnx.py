"""
RNNoise ONNX 匯出 — 逐幀串流推論

使用標準 torch.onnx.export，讓 ORT 自行做圖優化 (Conv+Tanh fusion 等)

用法:
    python export_onnx.py --model output/rnnoise_best.pth --output rnnoise.onnx
"""

import argparse
import numpy as np
import torch
import torch.nn as nn

from train import RNNoiseModel, N_BANDS


class RNNoiseStreaming(nn.Module):
    """單幀串流推論 wrapper，輸入 3 frame 特徵，輸出 1 frame gains"""

    def __init__(self, model: RNNoiseModel):
        super().__init__()
        self.conv1 = model.conv1
        self.conv2 = model.conv2
        self.gru1 = model.gru1
        self.gru2 = model.gru2
        self.gru3 = model.gru3
        self.dense_out = model.dense_out
        self.gru_size = model.gru_size

    def forward(self, x, h1, h2, h3):
        """
        x:  (1, 3, n_bands) — 3 frame 特徵
        h1, h2, h3: (1, 1, gru_size) — GRU hidden states
        回傳: gains (1, 1, n_bands), h1_out, h2_out, h3_out
        """
        # Conv1d: (1, 3, 18) → permute → (1, 18, 3) → conv1(k=3) → (1, 64, 1)
        tmp = x.permute(0, 2, 1)
        tmp = torch.tanh(self.conv1(tmp))
        tmp = torch.tanh(self.conv2(tmp))
        conv_out = tmp.permute(0, 2, 1)  # (1, 1, 128)

        # 3 層 GRU
        g1, h1_out = self.gru1(conv_out, h1)
        g2, h2_out = self.gru2(g1, h2)
        g3, h3_out = self.gru3(g2, h3)

        # Concat + Dense + Sigmoid
        cat = torch.cat([conv_out, g1, g2, g3], dim=-1)  # (1, 1, 512)
        gains = torch.sigmoid(self.dense_out(cat))        # (1, 1, 18)

        return gains, h1_out, h2_out, h3_out


def export(args):
    ckpt = torch.load(args.model, map_location='cpu', weights_only=False)
    model = RNNoiseModel(n_bands=N_BANDS, cond_size=64, gru_size=128)
    model.load_state_dict(ckpt['state_dict'])
    model.eval()

    streaming = RNNoiseStreaming(model)
    streaming.eval()

    gru_size = model.gru_size
    x = torch.randn(1, 3, N_BANDS)
    h = torch.zeros(1, 1, gru_size)

    torch.onnx.export(
        streaming,
        (x, h, h, h),
        args.output,
        input_names=['input', 'h1_in', 'h2_in', 'h3_in'],
        output_names=['gains', 'h1_out', 'h2_out', 'h3_out'],
        opset_version=17,
        do_constant_folding=True,
    )

    # 統計
    import onnx
    from collections import Counter
    model_onnx = onnx.load(args.output)
    ops = Counter(n.op_type for n in model_onnx.graph.node)
    n_nodes = len(model_onnx.graph.node)
    print(f"ONNX 匯出完成: {args.output}")
    print(f"  節點數: {n_nodes}")
    print(f"  Op: {dict(ops)}")

    if args.verify:
        verify_output(model, args.output)


def verify_output(model, onnx_path):
    """用 PyTorch streaming forward 比較 ONNX 輸出"""
    try:
        import onnxruntime as ort

        x = torch.randn(1, 3, N_BANDS)
        h = torch.zeros(1, 1, model.gru_size)

        # PyTorch forward
        with torch.no_grad():
            tmp = x.permute(0, 2, 1)
            tmp = torch.tanh(model.conv1(tmp))
            tmp = torch.tanh(model.conv2(tmp))
            conv_out = tmp.permute(0, 2, 1)
            g1, h1 = model.gru1(conv_out, h)
            g2, h2 = model.gru2(g1, h)
            g3, h3 = model.gru3(g2, h)
            cat = torch.cat([conv_out, g1, g2, g3], dim=-1)
            pt_gains = torch.sigmoid(model.dense_out(cat))

        sess = ort.InferenceSession(onnx_path)
        ort_out = sess.run(None, {
            'input': x.numpy(),
            'h1_in': h.numpy(),
            'h2_in': h.numpy(),
            'h3_in': h.numpy(),
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
    parser.add_argument('--verify', action='store_true', help='驗證 ONNX 輸出一致性')
    export(parser.parse_args())
