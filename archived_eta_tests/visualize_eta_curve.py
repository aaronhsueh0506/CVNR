#!/usr/bin/env python3
"""
可視化不同 eta 參數的響應曲線

用法:
    python visualize_eta_curve.py
"""

import numpy as np
import matplotlib.pyplot as plt


def eta_sigmoid(beta, threshold, slope):
    """Sigmoid 模式的 eta 響應"""
    eta = 1.0 / (1.0 + np.exp(slope * (beta - threshold)))
    return np.maximum(eta, 0.01)


def eta_hard(beta, threshold):
    """Hard threshold 模式的 eta 響應"""
    return np.where(beta > threshold, 0.1, 1.0)


def eta_original(beta):
    """原始版本 (0.95 上限)"""
    return 0.95 / (1.0 + np.exp(20 * (beta - 10)))


def main():
    beta = np.linspace(0, 30, 300)

    fig, axes = plt.subplots(2, 2, figsize=(12, 10))

    # 1. 比較原始版本 vs 新版本
    ax1 = axes[0, 0]
    ax1.plot(beta, eta_original(beta), 'r-', linewidth=2, label='Original (max=0.95, center=10)')
    ax1.plot(beta, eta_sigmoid(beta, 10, 20), 'b-', linewidth=2, label='New sigmoid (max=1.0, center=10)')
    ax1.plot(beta, eta_hard(beta, 10), 'g--', linewidth=2, label='Hard threshold (th=10)')
    ax1.axhline(y=1.0, color='k', linestyle=':', alpha=0.5)
    ax1.axhline(y=0.1, color='k', linestyle=':', alpha=0.5)
    ax1.axvline(x=10, color='gray', linestyle='--', alpha=0.5, label='threshold=10')
    ax1.set_xlabel('Beta (energy ratio)')
    ax1.set_ylabel('Eta')
    ax1.set_title('Original vs New Version')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    ax1.set_ylim(-0.05, 1.1)

    # 2. 不同 threshold 的影響
    ax2 = axes[0, 1]
    for th in [5, 10, 15, 20]:
        ax2.plot(beta, eta_sigmoid(beta, th, 20), linewidth=2, label=f'threshold={th}')
    ax2.set_xlabel('Beta (energy ratio)')
    ax2.set_ylabel('Eta')
    ax2.set_title('Effect of Threshold (slope=20)')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    ax2.set_ylim(-0.05, 1.1)

    # 3. 不同 slope 的影響
    ax3 = axes[1, 0]
    for slope in [5, 10, 20, 40]:
        ax3.plot(beta, eta_sigmoid(beta, 10, slope), linewidth=2, label=f'slope={slope}')
    ax3.axvline(x=10, color='gray', linestyle='--', alpha=0.5)
    ax3.set_xlabel('Beta (energy ratio)')
    ax3.set_ylabel('Eta')
    ax3.set_title('Effect of Slope (threshold=10)')
    ax3.legend()
    ax3.grid(True, alpha=0.3)
    ax3.set_ylim(-0.05, 1.1)

    # 4. 建議的配置
    ax4 = axes[1, 1]
    configs = [
        ('Conservative', 15, 10, 'b'),
        ('Balanced', 10, 20, 'g'),
        ('Aggressive', 5, 30, 'r'),
        ('Hard (th=10)', 10, 0, 'purple'),
    ]
    for name, th, slope, color in configs:
        if slope > 0:
            ax4.plot(beta, eta_sigmoid(beta, th, slope), color=color, linewidth=2, label=f'{name} (th={th}, slope={slope})')
        else:
            ax4.plot(beta, eta_hard(beta, th), color=color, linewidth=2, linestyle='--', label=f'{name} (th={th})')

    ax4.set_xlabel('Beta (energy ratio)')
    ax4.set_ylabel('Eta')
    ax4.set_title('Recommended Configurations')
    ax4.legend()
    ax4.grid(True, alpha=0.3)
    ax4.set_ylim(-0.05, 1.1)

    # 添加說明
    fig.text(0.5, 0.02,
             'Eta = 1.0: No change to noise update | Eta → 0: Fast noise update (scene change)',
             ha='center', fontsize=10, style='italic')

    plt.tight_layout(rect=[0, 0.03, 1, 1])
    plt.savefig('eta_curve_comparison.png', dpi=150)
    print("📊 已保存: eta_curve_comparison.png")

    # 打印建議
    print("\n" + "="*60)
    print("參數建議")
    print("="*60)
    print("""
場景               | threshold | slope | 說明
-------------------|-----------|-------|------------------
保守（少誤觸發）    | 15-20     | 10    | 只有大幅場景變化才觸發
平衡（推薦）        | 10        | 20    | 適中的敏感度
激進（快速響應）    | 5-8       | 30    | 小幅場景變化也會觸發
Hard threshold     | 10        | 0     | 二值響應，無中間狀態

穩定噪聲環境: 建議用保守設定 (threshold=15, slope=10)
動態噪聲環境: 建議用平衡設定 (threshold=10, slope=20)
""")

    plt.show()


if __name__ == "__main__":
    main()
