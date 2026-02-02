"""
RNNoise ONNX 匯出 — 轉成逐幀串流推論的靜態圖

Netron 目標結構:
  Transpose → FusedConv(Tanh) → FusedConv(Tanh)
  → Reshape → GRU → GRU → GRU → Concat → Gemm → Sigmoid

用法:
    python export_onnx.py --model output/rnnoise_best.pth --output rnnoise.onnx
"""

import argparse
import numpy as np
import torch
import torch.nn as nn

from train import RNNoiseModel, N_BANDS

# ============================================================
# 手動建構 ONNX 圖 (完全控制 Netron 呈現)
# ============================================================

def build_onnx(model: RNNoiseModel):
    """從 PyTorch 模型直接建構乾淨的 ONNX 圖"""
    import onnx
    from onnx import helper, TensorProto, numpy_helper

    n_bands = model.n_bands
    gru_size = model.gru_size
    cond_size = model.conv1.weight.shape[0]  # 64

    nodes = []
    initializers = []

    def add_init(name, data):
        initializers.append(numpy_helper.from_array(data, name))

    # ---- 權重提取 ----
    conv1_w = model.conv1.weight.data.numpy()   # (64, 18, 3)
    conv1_b = model.conv1.bias.data.numpy()      # (64,)
    conv2_w = model.conv2.weight.data.numpy()   # (128, 64, 1)
    conv2_b = model.conv2.bias.data.numpy()      # (128,)
    out_w = model.dense_out.weight.data.numpy()  # (18, 512)
    out_b = model.dense_out.bias.data.numpy()    # (18,)

    add_init('conv1.W', conv1_w)
    add_init('conv1.B', conv1_b)
    add_init('conv2.W', conv2_w)
    add_init('conv2.B', conv2_b)
    add_init('dense.W', out_w.T)  # Gemm 需要 (512, 18), transB=0
    add_init('dense.B', out_b)

    # GRU 權重: PyTorch gate 順序 [r, z, n], ONNX 要 [z, r, h]
    # ONNX GRU 要: W (num_dir, 3*hidden, input), R (num_dir, 3*hidden, hidden), B (num_dir, 6*hidden)
    def reorder_gates(t, H):
        """PyTorch [r,z,n] → ONNX [z,r,h], t shape: (3*H, ...)"""
        r, z, n = t[:H], t[H:2*H], t[2*H:3*H]
        return np.concatenate([z, r, n], axis=0)

    for i, gru in enumerate([model.gru1, model.gru2, model.gru3], 1):
        H = gru.hidden_size
        w_ih = gru.weight_ih_l0.data.numpy()  # (3*H, input)
        w_hh = gru.weight_hh_l0.data.numpy()  # (3*H, H)
        b_ih = gru.bias_ih_l0.data.numpy()    # (3*H,)
        b_hh = gru.bias_hh_l0.data.numpy()    # (3*H,)
        # 重排 gate 順序
        w_ih = reorder_gates(w_ih, H)
        w_hh = reorder_gates(w_hh, H)
        b_ih = reorder_gates(b_ih, H)
        b_hh = reorder_gates(b_hh, H)
        # ONNX: W=[1, 3*H, input], R=[1, 3*H, H], B=[1, 6*H]
        add_init(f'gru{i}.W', w_ih[np.newaxis, :, :])
        add_init(f'gru{i}.R', w_hh[np.newaxis, :, :])
        add_init(f'gru{i}.B', np.concatenate([b_ih, b_hh])[np.newaxis, :])

    # Reshape / Squeeze 用的 shape 常數
    add_init('shape_gru_in', np.array([1, 1, gru_size], dtype=np.int64))
    add_init('shape_gemm_in', np.array([1, 4 * gru_size], dtype=np.int64))
    add_init('shape_out', np.array([1, 1, n_bands], dtype=np.int64))
    add_init('squeeze_axes', np.array([0], dtype=np.int64))

    # ---- 節點 ----

    # 1. Transpose: (1,3,18) → (1,18,3) for Conv NCW format
    nodes.append(helper.make_node('Transpose', ['input'], ['transposed'],
                                  perm=[0, 2, 1], name='Transpose'))

    # 2. FusedConv(Tanh): conv1(k=3) + tanh
    nodes.append(helper.make_node('FusedConv', ['transposed', 'conv1.W', 'conv1.B'],
                                  ['conv1_out'], name='Conv1_Tanh',
                                  domain='com.microsoft',
                                  kernel_shape=[3], activation='Tanh'))

    # 3. FusedConv(Tanh): conv2(k=1) + tanh
    nodes.append(helper.make_node('FusedConv', ['conv1_out', 'conv2.W', 'conv2.B'],
                                  ['conv2_out'], name='Conv2_Tanh',
                                  domain='com.microsoft',
                                  kernel_shape=[1], activation='Tanh'))

    # 4. Reshape: (1,128,1) → (1,1,128) for GRU
    nodes.append(helper.make_node('Reshape', ['conv2_out', 'shape_gru_in'],
                                  ['gru_in'], name='Reshape_GRU'))

    # 5-7. GRU × 3
    prev = 'gru_in'
    for i in range(1, 4):
        gru_out = f'gru{i}_Y'
        h_out = f'h{i}_out'
        nodes.append(helper.make_node(
            'GRU',
            [prev, f'gru{i}.W', f'gru{i}.R', f'gru{i}.B', '', f'h{i}_in'],
            [gru_out, h_out],
            name=f'GRU{i}',
            hidden_size=gru_size,
            linear_before_reset=1,
        ))
        # GRU Y output: (seq=1, num_dir=1, batch=1, hidden) → 需要取 [0] 得到 (1,1,hidden)
        squeezed = f'gru{i}_out'
        nodes.append(helper.make_node('Squeeze', [gru_out, 'squeeze_axes'], [squeezed],
                                      name=f'Squeeze{i}'))
        prev = squeezed

    # 8. Concat: [gru_in(=conv_out_reshaped), gru1_out, gru2_out, gru3_out] → (1,1,512)
    nodes.append(helper.make_node('Concat',
                                  ['gru_in', 'gru1_out', 'gru2_out', 'gru3_out'],
                                  ['concat_out'], name='Concat', axis=-1))

    # 9. Reshape: (1,1,512) → (1,512) for Gemm
    nodes.append(helper.make_node('Reshape', ['concat_out', 'shape_gemm_in'],
                                  ['gemm_in'], name='Reshape_Gemm'))

    # 10. Gemm: (1,512) @ (512,18) + bias → (1,18)
    nodes.append(helper.make_node('Gemm', ['gemm_in', 'dense.W', 'dense.B'],
                                  ['gemm_out'], name='Dense',
                                  alpha=1.0, beta=1.0, transB=0))

    # 11. Sigmoid
    nodes.append(helper.make_node('Sigmoid', ['gemm_out'], ['gains_flat'],
                                  name='Sigmoid'))

    # 12. Reshape: (1,18) → (1,1,18)
    nodes.append(helper.make_node('Reshape', ['gains_flat', 'shape_out'],
                                  ['gains'], name='Reshape_Out'))

    # ---- Graph I/O ----
    inputs = [
        helper.make_tensor_value_info('input',  TensorProto.FLOAT, [1, 3, n_bands]),
        helper.make_tensor_value_info('h1_in',  TensorProto.FLOAT, [1, 1, gru_size]),
        helper.make_tensor_value_info('h2_in',  TensorProto.FLOAT, [1, 1, gru_size]),
        helper.make_tensor_value_info('h3_in',  TensorProto.FLOAT, [1, 1, gru_size]),
    ]
    outputs = [
        helper.make_tensor_value_info('gains',   TensorProto.FLOAT, [1, 1, n_bands]),
        helper.make_tensor_value_info('h1_out',  TensorProto.FLOAT, [1, 1, gru_size]),
        helper.make_tensor_value_info('h2_out',  TensorProto.FLOAT, [1, 1, gru_size]),
        helper.make_tensor_value_info('h3_out',  TensorProto.FLOAT, [1, 1, gru_size]),
    ]

    graph = helper.make_graph(nodes, 'rnnoise', inputs, outputs, initializers)
    model_onnx = helper.make_model(graph, opset_imports=[
        helper.make_opsetid('', 17),
        helper.make_opsetid('com.microsoft', 1),
    ])
    model_onnx.ir_version = 9

    return model_onnx

# ============================================================
# 匯出
# ============================================================

def export(args):
    import onnx

    ckpt = torch.load(args.model, map_location='cpu', weights_only=False)
    model = RNNoiseModel(n_bands=N_BANDS, cond_size=64, gru_size=128)
    model.load_state_dict(ckpt['state_dict'])
    model.eval()

    model_onnx = build_onnx(model)
    onnx.save(model_onnx, args.output)

    # 統計
    from collections import Counter
    ops = Counter(n.op_type for n in model_onnx.graph.node)
    n_nodes = len(model_onnx.graph.node)
    print(f"ONNX 匯出完成: {args.output}")
    print(f"  節點數: {n_nodes}")
    print(f"  Op: {dict(ops)}")

    # 驗證
    if args.verify:
        verify_output(model, args.output)

def verify_output(model, onnx_path):
    """用 PyTorch streaming forward 比較 ONNX 輸出"""
    try:
        import onnxruntime as ort

        x = torch.randn(1, 3, N_BANDS)
        h = torch.zeros(1, 1, model.gru_size)

        # PyTorch forward (streaming 等價計算)
        with torch.no_grad():
            tmp = x.permute(0, 2, 1)
            tmp = torch.tanh(model.conv1(tmp))
            tmp = torch.tanh(model.conv2(tmp))
            conv_out = tmp.permute(0, 2, 1)  # (1,1,128)
            g1, h1 = model.gru1(conv_out, h)
            g2, h2 = model.gru2(g1, h)
            g3, h3 = model.gru3(g2, h)
            cat = torch.cat([conv_out, g1, g2, g3], dim=-1)
            pt_gains = torch.sigmoid(model.dense_out(cat))

        sess = ort.InferenceSession(onnx_path)
        ort_out = sess.run(None, {
            'input':  x.numpy(),
            'h1_in':  h.numpy(),
            'h2_in':  h.numpy(),
            'h3_in':  h.numpy(),
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
