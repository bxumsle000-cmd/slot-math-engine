"""
simulator/engine.py - 多線蒙地卡羅模擬引擎（5×3 格式）

每局隨機抽取五條捲軸的停格位置，建立 3×5 可見方格後評估所有付線，
彙整模擬 RTP，並與 calculator.py 的理論值做比對。
"""

import random
from dataclasses import dataclass, field

from core.config import FS_MIN_SCATTER
from core.reel import REEL_STRIPS, PAYLINES, ReelStrip
from core.paytable import PaylineEntry, PAYTABLE
from core.calculator import (
    RTPResult,
    _evaluate_payline,
    calculate_rtp,
)


@dataclass
class SpinOutcome:
    """
    多線旋轉的完整結果，供分析與 API 層使用。

    Attributes:
        stops: 五條捲軸的停格位置（整數索引，0-indexed）
        grid: 3×5 可見符號方格，grid[行][捲軸]，行 0=上、1=中、2=下
        payline_multipliers: 各付線的賠付倍率，長度 = 付線數（0 = 未中獎）
        total_multiplier: 所有付線倍率之和（押滿線時這局的實際總賠付倍率）
        scatter_count: 出現 Scatter 的捲軸數（0–5）
        free_spin_triggered: 是否觸發 Free Spin（scatter_count ≥ 3）
    """
    stops: tuple                    # 五捲軸的停格位置，例如 (5, 12, 3, 18, 0)
    grid: list[list[str]]           # 3×5 方格，grid[行][捲軸]，行 0=上、1=中、2=下
    payline_multipliers: list[int]  # 各付線賠付倍率，長度 = 付線數
    total_multiplier: int           # 所有付線倍率總和（押滿線的這局總賠付）
    scatter_count: int              # 出現 Scatter 的捲軸數（每條捲軸只算有無，不累計行數）
    free_spin_triggered: bool       # scatter_count ≥ 3 → 觸發 Free Spin


@dataclass
class SimulationResult:
    """
    多線模擬執行的彙總結果，用於理論值對比驗證。

    Attributes:
        num_games: 模擬總局數
        simulated_rtp: 模擬 RTP（每線標準化，方便與理論值比較）
        theoretical_rtp: 理論 RTP（由 calculator 精確計算，每線標準化）
        abs_error: 絕對誤差（百分點）
        error_pct: 相對誤差百分比
    """
    num_games: int          # 模擬總局數
    simulated_rtp: float    # 模擬 RTP（每線標準化 = 總賠付 / (局數 × 線數)）
    theoretical_rtp: float  # 理論 RTP（每線標準化，由枚舉法精確計算）
    abs_error: float        # 兩個 RTP 數值的絕對差（百分點）
    error_pct: float        # 相對誤差百分比（abs_error / theoretical_rtp × 100）


def spin(  # 模擬一局多線旋轉，回傳完整結果
    reel_strips: list[ReelStrip] = REEL_STRIPS,
    paylines: list[tuple] = PAYLINES,
    paytable: list[PaylineEntry] = PAYTABLE,
) -> SpinOutcome:
    """
    隨機抽取五條捲軸的停格位置，建立 3×5 方格並評估所有付線。

    Args:
        reel_strips: 捲軸帶列表（各有 total_stops 個停格）
        paylines:    付線定義列表
        paytable:    賠付規則列表

    Returns:
        SpinOutcome，含停格位置、3×5 方格、各付線賠付、總賠付倍率
    """
    reel_strips = reel_strips or REEL_STRIPS  
    num_reels = len(reel_strips)  # 捲軸數(5)

    # 對每條捲軸等機率抽一個停格位置（0 到 total_stops-1）
    # 例：stops = (5, 12, 3, 18, 0)，代表 5 條捲軸各自停在第幾格
    stops = tuple(random.randrange(r.total_stops) for r in reel_strips)

    # 各捲軸從停格位置展開可見的 3 行符號（上中下）
    # 例：windows[0] = ['Blank', 'Seven', 'Cherry']，代表第 0 條捲軸的上/中/下行
    windows = [reel_strips[i].window(stops[i]) for i in range(num_reels)]

    # 轉換成 grid[行][捲軸]：方便付線評估時按行索引取符號
    # grid[0] = 上排所有捲軸符號，grid[1] = 中排，grid[2] = 下排
    grid = [[windows[col][row] for col in range(num_reels)] for row in range(3)]

    payline_multipliers: list[int] = []
    for payline in paylines:
        line_symbols = tuple(windows[col][payline[col]] for col in range(num_reels))
        payline_multipliers.append(_evaluate_payline(line_symbols, paytable))

    # 計算出現 Scatter 的捲軸數：每條捲軸的 3 行視窗中只要有一個 Scatter 就計 1
    scatter_count = sum(1 for col in range(num_reels) if "Scatter" in windows[col])

    return SpinOutcome(
        stops=stops,
        grid=grid,
        payline_multipliers=payline_multipliers,
        total_multiplier=sum(payline_multipliers),  # 總賠付 = 各中獎付線倍率相加（多線可同時中獎）
        scatter_count=scatter_count,
        free_spin_triggered=scatter_count >= FS_MIN_SCATTER,  # ≥FS_MIN_SCATTER 軸出現 Scatter → 觸發 Free Spin
    )


def run_simulation(  # 執行 N 局多線模擬，回傳彙總結果
    num_games: int = 1_000_000,
    seed: int | None = None,
) -> SimulationResult:
    """
    跑 num_games 局多線模擬，彙整模擬 RTP 並與理論值對比。

    押注模型：每局押滿所有付線，每線各 1 單位，每局總押注 = 線數。
    模擬 RTP = 總賠付 / (局數 × 線數)，標準化後與單線 RTP 同單位。

    Args:
        num_games: 模擬局數（越多越接近理論值，建議 ≥ 1,000,000）
        seed: 隨機種子（None 表示不固定，固定值讓結果可重現）

    Returns:
        SimulationResult，含模擬 RTP、理論 RTP、誤差
    """
    if seed is not None:
        random.seed(seed)

    total_payout = 0
    for _ in range(num_games):
        total_payout += spin().total_multiplier  # 每局累加所有中獎付線的賠付

    num_lines = len(PAYLINES)  # 付線數，動態讀取
    # 模擬 RTP = 總賠付 / 總押注，總押注 = 局數 × 線數（每線押 1 單位）
    simulated_rtp = total_payout / (num_games * num_lines)

    theoretical: RTPResult = calculate_rtp()
    theoretical_rtp = theoretical.rtp_per_line  # 理論每線 RTP，與模擬 RTP 同單位

    abs_error = abs(simulated_rtp - theoretical_rtp) * 100  # 轉成百分點，方便判斷 < 0.1pp 是否達標
    error_pct = abs(simulated_rtp - theoretical_rtp) / theoretical_rtp * 100  # 相對誤差：絕對差 / 理論值

    return SimulationResult(
        num_games=num_games,
        simulated_rtp=simulated_rtp,
        theoretical_rtp=theoretical_rtp,
        abs_error=abs_error,
        error_pct=error_pct,
    )


def print_simulation_report(result: SimulationResult) -> None:  # 印出多線模擬對比報告
    """
    印出多線模擬 RTP vs 理論 RTP 對比報告。

    Args:
        result: run_simulation 的回傳值
    """
    ok = "✅ 達標" if result.abs_error < 0.1 else "❌ 未達標（目標 < 0.1 個百分點）"
    print("=" * 60)
    print("  多線老虎機模擬 RTP vs 理論 RTP 對比報告")
    print("=" * 60)
    print(f"  模擬局數   ：{result.num_games:>12,} 局")
    print(f"  模擬 RTP   ：{result.simulated_rtp * 100:>11.4f}%  （每線標準化）")
    print(f"  理論 RTP   ：{result.theoretical_rtp * 100:>11.4f}%  （每線標準化）")
    print(f"  絕對誤差   ：{result.abs_error:>11.6f} 百分點  {ok}")
    print(f"  相對誤差   ：{result.error_pct:>11.4f}%")
    print("=" * 60)


if __name__ == "__main__":
    print("正在模擬 1,000,000 局多線老虎機（5×3），請稍候...")
    result = run_simulation(num_games=1_000_000, seed=42)
    print_simulation_report(result)
