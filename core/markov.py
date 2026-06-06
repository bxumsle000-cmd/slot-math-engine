"""
markov.py - 馬可夫鏈 Free Spin 模型（2 狀態巨觀鏈）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  狀態 0  一般模式:每局需要押注
  狀態 1  Free Spin 模式:免費局, 賠付乘 win_multiplier
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Free Spin 機制(與成品 simulator / API 完全一致)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ① 一般模式每局押注後:
       機率 p   → 觸發 Free Spin, 獲得 N 局免費局
       機率 1-p → 留在一般模式
  ② 進入 Free Spin 後「每一局」都可能再觸發(非只有最後一局):
       機率 r   → 堆疊 +N 局(可在任何一局發生)
       每玩一局消耗 1 局, 剩餘局數歸零才回一般模式

  ⚠ 剩餘局數會因每局都能 +N 而無上限, 故不存在精確的有限 (N+1) 倒數鏈。
    但由更新-回報(renewal-reward)定理, 長期 RTP 只取決於
    「一次觸發的期望 Free Spin 局數」:
        E[FS] = N / (1 - N·r)      （分支論證, 見 stationary_distribution）
    故本模組以 2 狀態巨觀鏈表示, FS→一般 的每局退出率
        q = (1 - N·r) / N          （= E[FS] 的倒數）
    即可讓矩陣穩態與解析 RTP 完全自洽。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  這個模型能算什麼？
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  → 長期有幾 % 的回合在一般模式、幾 % 在 Free Spin(穩態分佈)
  → Free Spin 的免費局＋贏分倍率, 最終讓整體 RTP 提升多少
"""

import numpy as np
from dataclasses import dataclass


@dataclass
class FreespinConfig:
    """
    Free Spin 機制的參數設定。

    Attributes:
        trigger_prob: 每局一般遊戲中觸發 Free Spin 的機率
        free_spin_count: 每次觸發給幾局 Free Spin
        retrigger_prob: Free Spin 期間「每一局」再次觸發（堆疊 +N 局）的機率
        win_multiplier: Free Spin 期間的贏分倍率
    """
    trigger_prob: float      # 每局一般遊戲觸發 Free Spin 的機率(例如 0.01 = 1%)
    free_spin_count: int     # 每次觸發給幾局 Free Spin
    retrigger_prob: float    # 續場機率:Free Spin 期間每一局再得一輪免費局(+N)的機率
    win_multiplier: float    # Free Spin 期間的贏分倍率(例如 3.0 = 三倍賠付)


@dataclass
class MarkovResult:
    """
    馬可夫鏈分析的彙總結果。

    Attributes:
        config: 使用的 Free Spin 參數設定
        transition_matrix: 巨觀狀態轉移矩陣(shape: 2 × 2，狀態 0=一般、1=Free Spin)
        pi_normal: 長期處於一般模式的穩態比例
        pi_free: 長期處於 Free Spin 模式的穩態比例
        base_rtp: 付線理論 RTP（不含 Free Spin 貢獻）
        total_rtp: 整體 RTP = 付線 RTP + Free Spin 貢獻
        freespin_contribution: Free Spin 單獨貢獻的 RTP 增量
    """
    config: FreespinConfig         # 此次分析使用的 Free Spin 參數設定
    transition_matrix: np.ndarray  # 巨觀狀態轉移矩陣, shape (2, 2)（狀態 0=一般、1=Free Spin）
    pi_normal: float               # 長期處於一般模式的穩態比例
    pi_free: float                 # 長期處於 Free Spin 模式的穩態比例(= 1 - pi_normal)
    base_rtp: float                       # 付線理論 RTP（不含 Free Spin 貢獻）
    total_rtp: float = 0.0                # 整體 RTP = 付線 RTP + Free Spin 貢獻
    freespin_contribution: float = 0.0    # Free Spin 單獨貢獻的 RTP 增量


def build_transition_matrix(config: FreespinConfig) -> np.ndarray:  # 建立 2 狀態巨觀轉移矩陣
    """
    建立 2 × 2 的巨觀狀態轉移矩陣 T（狀態 0 = 一般模式，狀態 1 = Free Spin）。

    新機制下「剩餘 FS 局數」會因每局都能堆疊 +N 而無上限，不存在精確的有限
    (N+1) 倒數鏈；但由更新-回報定理，長期 RTP 只取決於平均 FS 局數
    E[FS] = N/(1-N·r)，故以 2 狀態巨觀鏈表示，FS→一般 的每局退出率
    q = (1-N·r)/N（= E[FS] 的倒數）即與解析穩態完全自洽。

    以 N=5, p=0.02, r=0.10 為例（q = (1-0.5)/5 = 0.10）：

              到0(一般)  到1(FS)
        0 [   0.98       0.02 ]  ← 98% 留一般模式，2% 觸發 FS
        1 [   0.10       0.90 ]  ← 每局 10% 結束 FS 回一般，90% 延續

    Args:
        config: Free Spin 參數設定（trigger_prob=p、free_spin_count=N、retrigger_prob=r）

    Returns:
        轉移矩陣，shape (2, 2)，dtype float64

    Raises:
        ValueError: 當 N·r ≥ 1（每局期望新增局數 ≥ 消耗，FS 期望局數發散）
    """
    n_free_spins = config.free_spin_count  # 每次觸發給幾局 Free Spin（N）
    trig_p   = config.trigger_prob     # 一般模式每局觸發 Free Spin 的機率 p
    retrig_p = config.retrigger_prob   # FS 期間每局再觸發（+N 局）的機率 r

    if n_free_spins * retrig_p >= 1.0:  # N·r ≥ 1：每局期望 +N·r 局 ≥ 消耗 1 局，FS 永不結束
        raise ValueError("free_spin_count × retrigger_prob 必須 < 1，否則 Free Spin 期望局數發散")

    q = (1 - n_free_spins * retrig_p) / n_free_spins  # FS 每局退出率 = 平均 FS 局數 N/(1-N·r) 的倒數

    T = np.zeros((2, 2))
    T[0][0] = 1 - trig_p   # 一般模式未觸發，留在一般模式
    T[0][1] = trig_p       # 一般模式觸發 Free Spin
    T[1][0] = q            # Free Spin 當局結束，回一般模式
    T[1][1] = 1 - q        # Free Spin 延續（已含每局 +N 堆疊的整體效果）

    return T


def stationary_distribution(config: FreespinConfig) -> float:  # 計算一般模式的穩態比例
    """
    用解析公式直接求 π_normal(一般模式的穩態比例)。

    新機制：進入 FS 後每一局都以機率 r 再觸發、堆疊 +N 局。
    以「剩餘 FS 局數」c 為計量，每局 c 先 -1，再以機率 r 累加 N。
    令 T = 自單位剩餘局數起、直到 c 歸零的期望總局數，由分支(branching)論證：
        T = 1 + r·N·T   →   T = 1 / (1 - N·r)
    故一次觸發(給 N 局)的期望 FS 局數 E[FS] = N·T = N / (1 - N·r)。

    再由更新-回報：每觸發一次平均歷經 1/p 個一般局與 E[FS] 個 FS 局，
        π_free / π_normal = p · E[FS] = N·p / (1 - N·r)
        π_normal = (1 - N·r) / [(1 - N·r) + N·p]

    Args:
        config: Free Spin 參數設定（trigger_prob=p、free_spin_count=N、retrigger_prob=r）

    Returns:
        pi_normal:長期處於一般模式的比例(pi_free = 1 - pi_normal)

    Raises:
        ValueError: 當 N·r ≥ 1（FS 期望局數發散，穩態無定義）
    """
    n_free_spins = config.free_spin_count  # 每次觸發給幾局 Free Spin（N）
    trig_p   = config.trigger_prob     # 觸發機率 p
    retrig_p = config.retrigger_prob   # FS 期間每局續場機率 r

    if n_free_spins * retrig_p >= 1.0:  # N·r ≥ 1：FS 期望局數發散，穩態無定義
        raise ValueError("free_spin_count × retrigger_prob 必須 < 1，否則 Free Spin 期望局數發散")

    survive = 1 - n_free_spins * retrig_p  # (1 - N·r)：FS 終止性指標，越小代表 FS 平均越長
    pi_normal = survive / (survive + n_free_spins * trig_p)  # π_0 = (1-N·r) / [(1-N·r) + N·p]

    return pi_normal


def print_markov_report(result: MarkovResult) -> None:  # 印出馬可夫鏈 RTP 分析報告
    """
    印出馬可夫鏈分析報告。

    Args:
        result: calculate_freespin_rtp 的回傳值
    """
    cfg = result.config

    print("=" * 65)
    print("  馬可夫鏈 Free Spin RTP 分析報告")
    print("=" * 65)
    print(f"  Free Spin 設定:")
    print(f"    觸發機率     : {cfg.trigger_prob * 100:.2f}%(每局一般遊戲)")
    print(f"    每次給局數   : {cfg.free_spin_count} 局")
    print(f"    Retrigger 率 : {cfg.retrigger_prob * 100:.2f}%")
    print(f"    贏分倍率     : {cfg.win_multiplier}x")
    print()
    print(f"  穩態分佈:")
    print(f"    一般模式     : {result.pi_normal * 100:.4f}% 的時間")
    print(f"    Free Spin    : {result.pi_free * 100:.4f}% 的時間")
    print(f"    平均每觸發一次 Free Spin, 可得 {cfg.free_spin_count / (1 - cfg.free_spin_count * cfg.retrigger_prob):.1f} 局")
    print()
    print(f"  RTP 分析:")
    print(f"    付線 RTP(一般模式)    : {result.base_rtp * 100:.4f}%")
    print(f"    Free Spin 貢獻        : +{result.freespin_contribution * 100:.4f}%")
    print(f"    整體 RTP(兩項合計)    : {result.total_rtp * 100:.4f}%")
    print("=" * 65)


if __name__ == "__main__":
    from core.markov_freespin_rtp import calculate_freespin_rtp
    from core.config import DEFAULT_FS_CONFIG

    # 觸發與續場機率皆由捲軸帶 Scatter 分佈衍生（見 calculate_freespin_rtp），
    # 故這裡用 DEFAULT_FS_CONFIG，只示範 N（局數）與 M（倍率），不手填 trigger/retrigger。
    result = calculate_freespin_rtp(DEFAULT_FS_CONFIG)
    print_markov_report(result)
