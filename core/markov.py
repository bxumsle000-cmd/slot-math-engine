"""
markov.py - 馬可夫鏈 Free Spin 模型（(N+1) 狀態吸收鏈）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Free Spin 機制（與成品 simulator / API 完全一致）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ① 一般模式每局押注後:
       機率 p   → 觸發 Free Spin, 獲得 N 局免費局
       機率 1-p → 留在一般模式
  ② 進入 Free Spin 後「每一局」都可能再觸發(非只有最後一局):
       機率 r   → 重置為 N 局（= N，不是 +N；剩餘局數打回上限）
       每玩一局消耗 1 局, 剩餘局數歸零才回一般模式

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  這個模型能算什麼？
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  → 一次觸發平均玩幾局 Free Spin（E[FS]）
  → 長期有幾 % 的回合在一般模式、幾 % 在 Free Spin（穩態比例）
  → Free Spin 的免費局＋贏分倍率, 最終讓整體 RTP 提升多少
"""

import numpy as np
from dataclasses import dataclass


@dataclass
class FreespinConfig:
    """
    Free Spin 機制的參數設定。

    觸發機率（p）與續場機率（r）「不是」此設定的欄位：兩者一律由捲軸帶的
    Scatter 分佈自動衍生（見 markov_freespin_rtp.scatter_trigger_prob），
    並以獨立參數傳入 build_transition_matrix / expected_fs_spins，
    故本設定只保留真正可由設計者調整的 N 與 M 兩個旋鈕。

    Attributes:
        free_spin_count: 每次觸發給幾局 Free Spin
        win_multiplier: Free Spin 期間的贏分倍率
    """
    free_spin_count: int     # 每次觸發給幾局 Free Spin
    win_multiplier: float    # Free Spin 期間的贏分倍率(例如 3.0 = 三倍賠付)


@dataclass
class MarkovResult:
    """
    馬可夫鏈分析的彙總結果。

    Attributes:
        config: 使用的 Free Spin 參數設定
        transition_matrix: (N+1)×(N+1) 吸收轉移矩陣（狀態 i = 剩餘免費局數，0 為吸收態）
        expected_fs_spins: 一次觸發的平均 Free Spin 局數 E[FS]（由逐層遞迴精確求得）
        pi_normal: 長期處於一般模式的穩態比例
        pi_free: 長期處於 Free Spin 模式的穩態比例
        base_rtp: 付線理論 RTP（不含 Free Spin 貢獻）
        total_rtp: 整體 RTP = 付線 RTP + Free Spin 貢獻
        freespin_contribution: Free Spin 單獨貢獻的 RTP 增量
        trigger_prob: 實際生效的每局觸發機率 p（由捲軸 Scatter 分佈衍生）
        retrigger_prob: 實際生效的每局重置觸發機率 r（= trigger_prob）
    """
    config: FreespinConfig         # 此次分析使用的 Free Spin 參數設定
    transition_matrix: np.ndarray  # (N+1)×(N+1) 吸收轉移矩陣（狀態 i = 剩餘局數，0 為吸收態）
    pi_normal: float               # 長期處於一般模式的穩態比例
    pi_free: float                 # 長期處於 Free Spin 模式的穩態比例(= 1 - pi_normal)
    base_rtp: float                       # 付線理論 RTP（不含 Free Spin 貢獻）
    total_rtp: float = 0.0                # 整體 RTP = 付線 RTP + Free Spin 貢獻
    freespin_contribution: float = 0.0    # Free Spin 單獨貢獻的 RTP 增量
    trigger_prob: float = 0.0             # 實際生效的每局觸發機率 p（由捲軸 Scatter 分佈衍生，供報表顯示）
    retrigger_prob: float = 0.0           # 實際生效的每局重置觸發機率 r（= trigger_prob，共用同一捲軸與門檻）
    expected_fs_spins: float = 0.0        # 一次觸發的平均 Free Spin 局數 E[FS]（逐層遞迴精確值）


def build_transition_matrix(  # 建立「=N 重置」規則的 (N+1) 狀態吸收轉移矩陣
    config: FreespinConfig,
    retrigger_prob: float,
) -> np.ndarray:
    """
    建立「retrigger 時重置為 N」規則下的 (N+1)×(N+1) 吸收轉移矩陣。

    狀態 i = 玩完一局後的「剩餘免費局數」，範圍 0~N（0 為吸收態）。

    轉移矩陣 T 長相（範例 N=3、r=0.2；列＝由哪個狀態出發，欄＝跳到哪個狀態）：
    . 代表 0，每一列總和都 = 1。

                     k=0    k=1    k=2    k=3   ← 跳到 (to)
                  ┌────────────────────────────┐
    k=0 →         │   1      .      .      .   │  ⟲ 吸收態()
    k=1 →         │  0.8     .      .     0.2  │
    k=2 →         │   .     0.8     .     0.2  │
    k=3 →         │   .      .     0.8    0.2  │
                  └────────────────────────────┘


    第 k 列就是「玩完一局後剩 k 局時」下一步的去向機率分佈──
    往左下走 0.8 退一格(倒數)，往最右欄跳 0.2 回到滿格 N(重置)，
    第 0 列只有對角線的 1，代表 FS 已結束、卡在吸收態。

    Args:
        config: Free Spin 參數設定（提供 free_spin_count=N）
        retrigger_prob: FS 期間每局觸發「重置為 N」的機率 r（由捲軸 Scatter 衍生）

    Returns:
        轉移矩陣，shape (N+1, N+1)，dtype float64；每列總和為 1
    """
    n_free_spins = config.free_spin_count  # 每次觸發給幾局 Free Spin（N）
    retrig_p = retrigger_prob              # FS 期間每局重置觸發機率 r

    size = n_free_spins + 1                       # 狀態數 = N+1（剩餘局數 0~N）
    T = np.zeros((size, size))                    # 轉移矩陣，先全部歸零

    T[0][0] = 1.0                                 # 第 0 列：對角線填 1 = 吸收態(⟲)，其餘為 0
    for k in range(1, size):                      # 逐列填第 k 列（剩 k 局時的去向分佈）
        T[k][n_free_spins] += retrig_p            # 最右欄填 r：重置機率，跳回滿格 N
        T[k][k - 1] += (1 - retrig_p)             # 對角線下一格填 1-r，退 1 格到 k-1

    return T


def expected_fs_spins(  # 求平均 FS 局數 E[FS]
    config: FreespinConfig,
    retrigger_prob: float,
) -> float:
    """
    FS 從滿格 N 局開始，每局機率 r 重置回滿格、機率 q=1-r 倒數一格，要結束須
    連續 N 局都沒被重置。
    算出進入FS後，平均玩幾局。

    Args:
        config: Free Spin 參數設定（提供 free_spin_count=N）
        retrigger_prob: FS 期間每局重置觸發機率 r（須 0 ≤ r < 1）

    Returns:
        E[FS]：一次觸發平均玩幾局 Free Spin（含重置帶來的延長）
    """
    n_free_spins = config.free_spin_count   # 每次觸發給幾局 Free Spin（N）
    q = 1.0 - retrigger_prob                 # 倒數(不重置)的機率 q = 1 - r

    efs = 0.0                                 # E[FS] 起始累加器
    for _ in range(n_free_spins):             # 從 E_0 往外疊 N 層 → E_1, E_2, …, E_N
        efs = (efs + 1.0) / q                 # E_k=(E_{k-1}+1)/q
    return float(efs)                         # 疊滿 N 層即 E_N = E[FS]


def print_markov_report(result: "MarkovResult") -> None:  # 列印馬可夫鏈 Free Spin RTP 分析報告
    """
    把 MarkovResult 的分析結果以易讀的文字報表印到終端機。

    Args:
        result: calculate_freespin_rtp() 回傳的馬可夫鏈彙總結果
    """
    cfg = result.config  # 此次分析使用的 Free Spin 參數設定（N、M）

    print("=" * 60)
    print("  多線含 Free Spin 整體 RTP 報告（馬可夫鏈）")
    print("=" * 60)
    print(f"  每次觸發給局數 N     ：{cfg.free_spin_count} 局")              # N：單次觸發的免費局數
    print(f"  FS 賠付倍率 M        ：{cfg.win_multiplier:.2f}x")            # M：Free Spin 期間贏分倍率
    print(f"  觸發機率 p           ：{result.trigger_prob * 100:.4f}%")     # p：一般局每局觸發 FS 的機率
    print(f"  重置觸發機率 r       ：{result.retrigger_prob * 100:.4f}%")   # r：FS 期間每局重置回滿格的機率
    print(f"  平均 FS 局數 E[FS]   ：{result.expected_fs_spins:.4f} 局")    # 一次觸發平均玩幾局 FS
    print("-" * 60)
    print(f"  一般模式時間比例 π₀  ：{result.pi_normal * 100:.4f}%")        # 長期處於一般模式的穩態比例
    print(f"  Free Spin 時間比例 π₁：{result.pi_free * 100:.4f}%")         # 長期處於 Free Spin 的穩態比例
    print("-" * 60)
    print(f"  基礎付線 RTP         ：{result.base_rtp * 100:.4f}%")         # 不含 FS 的每線理論 RTP
    print(f"  Free Spin 貢獻       ：+{result.freespin_contribution * 100:.4f}%")  # FS 單獨貢獻的 RTP 增量
    print(f"  整體 RTP             ：{result.total_rtp * 100:.4f}%")        # 含 FS 的整體理論 RTP
    print("=" * 60)
