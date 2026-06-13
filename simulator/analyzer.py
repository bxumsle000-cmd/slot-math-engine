"""
simulator/analyzer.py - 多線老虎機統計分析模組（5×3 格式）

提供波動性、賠付分佈、RTP 收斂三項分析。
多線版本命中率顯著較高（多條付線同時評估），統計特性與單線有明顯差異。
"""

import random

import numpy as np
from dataclasses import dataclass

from core.calculator import calculate_rtp
from core.reel import REEL_STRIPS, ReelStrip
from simulator.engine import spin, PAYLINES


@dataclass
class VolatilityStats:
    """
    多線模擬波動性統計。

    Attributes:
        num_games: 模擬總局數
        hit_rate: 命中率（至少一條付線中獎的局數比例）
        simulated_rtp: 模擬 RTP（每線標準化，方便與理論值直接對比）
        theoretical_rtp: 理論 RTP（由計算器精確計算，供對照）
        std_dev: 每局總賠付的標準差，反映波動幅度
        max_payout: 模擬期間單局最大總賠付倍率
    """
    num_games: int          # 模擬總局數
    hit_rate: float         # 命中率：至少一條付線中獎的局數 / 總局數
    simulated_rtp: float    # 模擬 RTP（每線標準化）= 總賠付 / (局數 × 線數)
    theoretical_rtp: float  # 理論 RTP（每線標準化，由 calculator 精確計算，供對照）
    std_dev: float          # 每局總賠付的標準差：反映多線模式下的賠付波動幅度
    max_payout: int         # 單局最大總賠付倍率（所有付線同時中最高獎時最大）


@dataclass
class ConvergencePoint:
    """
    多線 RTP 收斂曲線上的單一取樣點。

    Attributes:
        num_games: 截至此取樣點已跑的局數
        simulated_rtp: 截至此局數的模擬 RTP（每線標準化）
        theoretical_rtp: 理論 RTP（固定值，每個取樣點相同，供計算誤差）
        abs_error: 當前模擬 RTP 與理論 RTP 的差距（百分點）
    """
    num_games: int          # 截至此取樣點已跑的局數
    simulated_rtp: float    # 截至此局的模擬 RTP（每線標準化，隨局數收斂）
    theoretical_rtp: float  # 理論 RTP（固定值，每個取樣點相同）
    abs_error: float        # 誤差（百分點）= |模擬 RTP - 理論 RTP| × 100


def analyze_volatility(  # 計算多線波動性統計
    num_games: int = 500_000,
    seed: int | None = None,
    reel_strips: list[ReelStrip] | None = None,
) -> VolatilityStats:
    """
    模擬 num_games 局多線老虎機，計算波動性統計指標。

    Args:
        num_games: 模擬局數，越多越接近理論值（建議 ≥ 100,000）
        seed: 隨機種子（None 表示每次結果不同，固定值讓結果可重現）
        reel_strips: 自訂捲軸帶列表（None 表示使用預設 REEL_STRIPS）

    Returns:
        VolatilityStats，含命中率、模擬 RTP、標準差、最大賠付
    """
    if seed is not None:
        random.seed(seed)

    strips = reel_strips or REEL_STRIPS  
    # 收集每局的 total_multiplier（所有付線倍率之和）
    payouts = np.array([spin(reel_strips=strips).total_multiplier for _ in range(num_games)])

    num_lines = len(PAYLINES)            # 付線數，動態讀取，用於標準化 RTP
    theoretical_rtp = calculate_rtp(reel_strips=strips).rtp_per_line  # 理論每線 RTP，供對照

    # 模擬 RTP = 總賠付 / 總押注（總押注 = 局數 × 線數，每線押 1 單位）
    simulated_rtp = float(np.mean(payouts)) / num_lines

    # hit_rate = 至少一條線中獎的比例（payouts > 0 代表有任一線中獎）
    hit_rate = float(np.mean(payouts > 0))

    # std_dev = 每局 total_multiplier 的標準差（衡量賠付的波動幅度）
    std_dev = float(np.std(payouts))

    max_payout = int(np.max(payouts))  # 模擬期間出現過的單局最大總賠付

    return VolatilityStats(
        num_games=num_games,
        hit_rate=hit_rate,
        simulated_rtp=simulated_rtp,
        theoretical_rtp=theoretical_rtp,
        std_dev=std_dev,
        max_payout=max_payout,
    )


def analyze_distribution(  # 統計多線各倍率出現次數
    num_games: int = 500_000,
    seed: int | None = None,
    reel_strips: list[ReelStrip] | None = None,
) -> dict[int, int]:
    """
    模擬 num_games 局，統計每局總賠付倍率（所有付線合計）的出現次數。

    Args:
        num_games: 模擬局數
        seed: 隨機種子
        reel_strips: 自訂捲軸帶列表（None 表示使用預設 REEL_STRIPS）

    Returns:
        {total_multiplier: 出現次數} 的字典，按倍率由小到大排列
    """
    if seed is not None:
        random.seed(seed)

    strips = reel_strips or REEL_STRIPS  # 使用自訂或預設捲軸帶
    counts: dict[int, int] = {}
    for _ in range(num_games):
        m = spin(reel_strips=strips).total_multiplier  # 這局所有中獎付線的倍率總和
        counts[m] = counts.get(m, 0) + 1

    return dict(sorted(counts.items()))  # 依倍率升序排列，方便繪圖


def analyze_convergence(  # 記錄多線 RTP 收斂過程
    num_games: int = 500_000,
    checkpoints: int = 50,
    seed: int | None = None,
    reel_strips: list[ReelStrip] | None = None,
) -> list[ConvergencePoint]:
    """
    每跑 (num_games / checkpoints) 局記錄一次當前模擬 RTP，
    回傳收斂曲線資料點序列。

    Args:
        num_games: 總模擬局數
        checkpoints: 取樣點數量（均勻分佈在總局數內）
        seed: 隨機種子
        reel_strips: 自訂捲軸帶列表（None 表示使用預設 REEL_STRIPS）

    Returns:
        list[ConvergencePoint]，長度 = checkpoints
    """
    if seed is not None:
        random.seed(seed)

    strips = reel_strips or REEL_STRIPS  # 使用自訂或預設捲軸帶
    num_lines = len(PAYLINES)  # 付線數，動態讀取，標準化 RTP 時除以此值
    theoretical_rtp = calculate_rtp(reel_strips=strips).rtp_per_line  # 預先計算理論值，避免每次取樣重複計算

    checkpoint_interval = num_games // checkpoints  # 每隔幾局記錄一次，均勻分布取樣點
    series: list[ConvergencePoint] = []
    total_payout = 0

    for i in range(1, num_games + 1):
        total_payout += spin(reel_strips=strips).total_multiplier  # 累加每局的總賠付

        if i % checkpoint_interval == 0:
            # 截至目前的模擬 RTP = 累積總賠付 / (已跑局數 × 線數)
            simulated_rtp = (total_payout / i) / num_lines
            abs_error = abs(simulated_rtp - theoretical_rtp) * 100  # 轉成百分點，方便判斷達標

            series.append(ConvergencePoint(
                num_games=i,
                simulated_rtp=simulated_rtp,
                theoretical_rtp=theoretical_rtp,
                abs_error=abs_error,
            ))

    return series


if __name__ == "__main__":
    num_lines = len(PAYLINES)  # 付線數

    print(f"【1/3】計算多線波動性統計（50 萬局，{num_lines} 條付線）")
    stats = analyze_volatility(num_games=500_000, seed=42)
    print(f"  命中率     ：{stats.hit_rate * 100:.4f}%")
    print(f"  模擬 RTP   ：{stats.simulated_rtp * 100:.4f}%")
    print(f"  理論 RTP   ：{stats.theoretical_rtp * 100:.4f}%")
    print(f"  標準差     ：{stats.std_dev:.4f}")
    print(f"  最大賠付   ：{stats.max_payout}x")

    print()
    print("【2/3】計算多線賠付分佈")
    dist = analyze_distribution(num_games=500_000, seed=42)
    zero_count = dist.get(0, 0)
    print(f"  未中獎（0x）：{zero_count:,} 局（{zero_count / 500_000 * 100:.2f}%）")

    print()
    print("【3/3】計算多線 RTP 收斂曲線")
    series = analyze_convergence(num_games=500_000, checkpoints=10, seed=42)
    for pt in series:
        ok = " ✅" if pt.abs_error < 0.1 else ""
        print(f"  {pt.num_games:>8,} 局  RTP {pt.simulated_rtp * 100:.4f}%  誤差 {pt.abs_error:.6f}pp{ok}")
