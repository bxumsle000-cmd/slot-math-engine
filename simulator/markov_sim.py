"""
simulator/markov_sim.py - 多線 Free Spin 蒙地卡羅驗證（5×3 格式）

在多線捲軸帶架構上套用 Free Spin 狀態機，模擬並驗證理論 RTP。
RTP 標準化：每局賠付除以線數（len(PAYLINES)），使模擬值與理論值（每線 RTP）同單位。
"""

import random

import numpy as np
from dataclasses import dataclass

from core.markov import FreespinConfig
from core.markov_freespin_rtp import calculate_freespin_rtp
from core.reel import REEL_STRIPS, ReelStrip
from simulator.analyzer import ConvergencePoint
from simulator.engine import PAYLINES, spin


@dataclass
class FreespinVolatilityStats:
    """
    多線含 Free Spin 的波動性統計。

    每筆有效報酬 = 押注局的所有付線合計賠付 + 觸發 FS 後所有 FS 局付線合計賠付 × win_multiplier。
    simulated_rtp 已除以線數標準化，方便與理論值直接對比。

    Attributes:
        config: 使用的 Free Spin 參數設定
        num_paid_spins: 模擬押注局數（Free Spin 免費局不計入分母）
        hit_rate: 有效報酬 > 0 的押注局比例
        simulated_rtp: 模擬 RTP（已標準化 = 總賠付 / (局數 × 線數)）
        std_dev: 每局付線合計有效報酬的標準差
        max_payout: 模擬期間單次押注的最大付線合計有效報酬
        theoretical_rtp: 馬可夫鏈推導的理論 RTP（每線標準化，供對照）
    """
    config: FreespinConfig   # 使用的 Free Spin 參數設定
    num_paid_spins: int      # 模擬押注局數（Free Spin 免費局不計入）
    hit_rate: float          # 有效報酬 > 0 的押注局比例（含 FS 觸發帶來的贏）
    simulated_rtp: float     # 模擬 RTP（每線標準化）= 總賠付 / (局數 × 線數)
    std_dev: float           # 每局付線合計有效報酬的標準差（FS 爆發會顯著拉高）
    max_payout: float        # 單次押注的最大付線合計有效報酬
    theoretical_rtp: float   # 馬可夫鏈推導的理論 RTP（每線標準化，供對照）


def _iter_per_spin_payouts(  # 多線狀態機 generator，逐押注局 yield 付線合計有效報酬
    config: FreespinConfig,
    num_paid_spins: int,
    seed: int | None = None,
    reel_strips: list[ReelStrip] | None = None,
):
    """
    多線版狀態機 generator：每完成一個押注局（含隨後所有 FS 局）yield 付線合計有效報酬。

    有效報酬 = 基礎局付線合計 + 觸發 FS 後所有 FS 局付線合計 × win_multiplier。
    此定義與馬可夫鏈 RTP 公式的分母（押注局數 × 線數）一致。

    Args:
        config: Free Spin 參數設定
        num_paid_spins: 要模擬的押注局數
        seed: 隨機種子（None 表示不固定）
        reel_strips: 自訂捲軸帶列表（None 表示使用預設 REEL_STRIPS）

    Yields:
        每次押注的付線合計有效報酬（float，未除以線數）
    """
    if seed is not None:
        random.seed(seed)

    strips = reel_strips or REEL_STRIPS  # 使用自訂或預設捲軸帶
    for _ in range(num_paid_spins):
        outcome = spin(reel_strips=strips)          # 旋轉一局，取得完整結果
        payout = float(outcome.total_multiplier)              # 基礎局所有付線合計賠付

        if outcome.free_spin_triggered:  # 以真實 Scatter 結果判斷是否觸發 FS（取代隨機骰）
            state = config.free_spin_count  # state = 剩餘 FS 局數（初始為 N）
            while state > 0:
                fs_outcome = spin(reel_strips=strips)
                # FS 局：付線合計賠付再乘 win_multiplier（倍率作用於總賠付）
                payout += fs_outcome.total_multiplier * config.win_multiplier
                state -= 1  # 消耗一局 FS
                if fs_outcome.free_spin_triggered:  # Scatter retrigger：任何 FS 局都可重置
                    state = config.free_spin_count  # 重置為 N 局（= N，非 +N）

        yield payout


def analyze_freespin_volatility(  # 計算多線含 Free Spin 的波動性統計
    config: FreespinConfig,
    num_paid_spins: int = 500_000,
    seed: int | None = None,
    reel_strips: list[ReelStrip] | None = None,
) -> FreespinVolatilityStats:
    """
    模擬 num_paid_spins 個押注局，計算多線含 Free Spin 的波動性統計。

    Args:
        config: Free Spin 參數設定
        num_paid_spins: 押注局數（建議 ≥ 500,000）
        seed: 隨機種子
        reel_strips: 自訂捲軸帶列表（None 表示使用預設 REEL_STRIPS）

    Returns:
        FreespinVolatilityStats
    """
    num_lines = len(PAYLINES)  # 付線數，動態讀取，用於標準化 RTP

    payouts = np.array(list(_iter_per_spin_payouts(config, num_paid_spins, seed, reel_strips)))

    theoretical_rtp = calculate_freespin_rtp(config, reel_strips=reel_strips).total_rtp  # 馬可夫鏈理論值，供對照（需傳捲軸帶，否則理論值不隨 sidebar 更新）

    # 模擬 RTP = 總賠付 / 總押注（總押注 = 局數 × 線數），標準化後與理論值同單位
    simulated_rtp = float(np.mean(payouts)) / num_lines

    return FreespinVolatilityStats(
        config=config,
        num_paid_spins=num_paid_spins,
        hit_rate=float(np.mean(payouts > 0)),   # 有任一付線中獎（或觸發 FS 帶來賠付）的局比例
        simulated_rtp=simulated_rtp,
        std_dev=float(np.std(payouts)),          # 付線合計有效報酬的標準差（FS 爆發會顯著拉高）
        max_payout=float(np.max(payouts)),       # 最大付線合計有效報酬
        theoretical_rtp=theoretical_rtp,
    )


def analyze_freespin_distribution(  # 統計多線含 Free Spin 的有效報酬分佈
    config: FreespinConfig,
    num_paid_spins: int = 500_000,
    seed: int | None = None,
    reel_strips: list[ReelStrip] | None = None,
) -> dict[int, int]:
    """
    模擬 num_paid_spins 個押注局，統計每局付線合計有效報酬（整數化後）的出現次數。

    Args:
        config: Free Spin 參數設定
        num_paid_spins: 押注局數
        seed: 隨機種子
        reel_strips: 自訂捲軸帶列表（None 表示使用預設 REEL_STRIPS）

    Returns:
        {付線合計有效報酬倍率: 出現次數}，按倍率由小到大排列
    """
    counts: dict[int, int] = {}
    for payout in _iter_per_spin_payouts(config, num_paid_spins, seed, reel_strips):
        key = int(round(payout))  # round 防止 win_multiplier 浮點誤差，結果仍為整數
        counts[key] = counts.get(key, 0) + 1

    return dict(sorted(counts.items()))  # 依倍率升序排列


def analyze_freespin_convergence(  # 記錄多線含 Free Spin 的 RTP 收斂曲線
    config: FreespinConfig,
    total_paid_spins: int = 500_000,
    checkpoints: int = 50,
    seed: int | None = None,
    reel_strips: list[ReelStrip] | None = None,
) -> list[ConvergencePoint]:
    """
    每跑 (total_paid_spins / checkpoints) 個押注局記錄一次模擬 RTP，
    回傳多線含 Free Spin 的收斂曲線資料點序列。

    Args:
        config: Free Spin 參數設定
        total_paid_spins: 總押注局數
        checkpoints: 取樣點數量（均勻分佈在總局數內）
        seed: 隨機種子
        reel_strips: 自訂捲軸帶列表（None 表示使用預設 REEL_STRIPS）

    Returns:
        list[ConvergencePoint]，長度 = checkpoints
    """
    strips = reel_strips or REEL_STRIPS  # 使用自訂或預設捲軸帶
    num_lines = len(PAYLINES)  # 付線數，動態讀取，標準化 RTP 時除以此值
    theoretical_rtp = calculate_freespin_rtp(config, reel_strips=strips).total_rtp  # 預先計算，避免每次取樣重複呼叫

    checkpoint_interval = total_paid_spins // checkpoints  # 每隔幾局取樣一次
    series: list[ConvergencePoint] = []
    total_payout = 0.0

    for i, payout in enumerate(_iter_per_spin_payouts(config, total_paid_spins, seed, strips), 1):
        total_payout += payout

        if i % checkpoint_interval == 0:
            # 截至目前的模擬 RTP = 累積總賠付 / (已跑局數 × 線數)
            sim_rtp = (total_payout / i) / num_lines
            series.append(ConvergencePoint(
                num_games=i,
                simulated_rtp=sim_rtp,
                theoretical_rtp=theoretical_rtp,
                abs_error=abs(sim_rtp - theoretical_rtp) * 100,  # 轉成百分點，方便判斷達標
            ))

    return series


# 啟動方式：PYTHONPATH=. .venv/bin/python simulator/markov_sim.py
if __name__ == "__main__":
    from core.config import DEFAULT_FS_CONFIG
    config = DEFAULT_FS_CONFIG
    num_lines = len(PAYLINES)  # 付線數

    print(f"【1/3】多線含 Free Spin 波動性統計（50 萬局，{num_lines} 條付線）")
    stats = analyze_freespin_volatility(config, num_paid_spins=500_000, seed=42)
    print(f"  命中率     ：{stats.hit_rate * 100:.4f}%")
    print(f"  模擬 RTP   ：{stats.simulated_rtp * 100:.4f}%  （每線標準化）")
    print(f"  理論 RTP   ：{stats.theoretical_rtp * 100:.4f}%  （馬可夫鏈）")
    print(f"  標準差     ：{stats.std_dev:.4f}")
    print(f"  最大有效報酬：{stats.max_payout:.0f}x（{num_lines} 線合計）")

    print()
    print("【2/3】多線含 Free Spin RTP 收斂曲線")
    series = analyze_freespin_convergence(config, total_paid_spins=500_000, checkpoints=10, seed=42)
    for pt in series:
        ok = " ✅" if pt.abs_error < 0.1 else ""
        print(f"  {pt.num_games:>8,} 局  RTP {pt.simulated_rtp * 100:.4f}%  誤差 {pt.abs_error:.4f}pp{ok}")

    print()
    print("【3/3】多線含 Free Spin 理論 RTP（馬可夫鏈）")
    from core.markov_freespin_rtp import calculate_freespin_rtp
    from core.markov import print_markov_report
    result = calculate_freespin_rtp(config)
    print_markov_report(result)
