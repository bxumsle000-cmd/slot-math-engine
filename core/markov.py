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

  ✔ 重置規則下剩餘局數永遠落在 0~N 之間，只有 (N+1) 個狀態，
    故可建「有限狀態的精確吸收馬可夫鏈」，毋須任何抹平近似：
        狀態 i = 剩餘免費局數（0 = FS 結束，為吸收態）
        從「剩 k 局」玩一局：機率 r → 跳狀態 N（重置）；機率 1-r → 跳狀態 k-1
    平均 FS 局數 E[FS] 以吸收鏈的基本矩陣 (I-Q)^(-1) 精確求得。

  ✔ 收斂性：重置規則對任何 r < 1 都收斂（發散判據 r·S = 1-(1-r)^N 恆 < 1），
    不像「+N 堆疊」會有 N·r ≥ 1 的發散禁區。

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
        expected_fs_spins: 一次觸發的平均 Free Spin 局數 E[FS]（由吸收鏈精確求得）
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
    expected_fs_spins: float = 0.0        # 一次觸發的平均 Free Spin 局數 E[FS]（吸收鏈精確值）


def build_transition_matrix(  # 建立「=N 重置」規則的 (N+1) 狀態吸收轉移矩陣
    config: FreespinConfig,
    retrigger_prob: float,
) -> np.ndarray:
    """
    建立「retrigger 時重置為 N」規則下的 (N+1)×(N+1) 吸收轉移矩陣。

    狀態 i = 玩完一局後的「剩餘免費局數」，範圍 0~N：
        狀態 0    = 剩餘歸零，Free Spin 結束（吸收態，回一般模式）
        狀態 1~N  = 仍在 Free Spin，尚餘 i 局

    從「剩 k 局」(k≥1) 玩一局後的轉移：
        機率 r       → 重置為 N 局（跳到狀態 N）
        機率 (1-r)   → 正常倒數 1 局（跳到狀態 k-1，k=1 時即落入吸收態 0）

    重置使剩餘局數永遠 ≤ N，狀態有限可精確求解（不需 2 狀態巨觀近似）。

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

    T[0][0] = 1.0                                 # 狀態 0 為吸收態：FS 已結束，恆留原地

    for k in range(1, size):                      # 對每個 FS 中的狀態 k = 剩 k 局
        T[k][n_free_spins] += retrig_p            # 機率 r：重置為 N 局（跳到狀態 N）
        T[k][k - 1] += (1 - retrig_p)             # 機率 1-r：正常倒數到 k-1 局

    return T


def expected_fs_spins(  # 用吸收馬可夫基本矩陣求平均 FS 局數 E[FS]
    config: FreespinConfig,
    retrigger_prob: float,
) -> float:
    """
    以吸收馬可夫鏈的「基本矩陣」精確求出一次觸發的平均 Free Spin 局數 E[FS]。

    作法：取轉移矩陣中「暫態→暫態」的子矩陣 Q（剔除吸收態 0，即狀態 1~N），
    基本矩陣 M = (I - Q)^(-1)，其第 i 列總和 = 從狀態 i 出發到被吸收的期望步數。
    進入 Free Spin 時剩餘局數 = N（狀態 N），故 E[FS] 取「從狀態 N 出發」那一項。

    Args:
        config: Free Spin 參數設定（提供 free_spin_count=N）
        retrigger_prob: FS 期間每局重置觸發機率 r

    Returns:
        E[FS]：一次觸發平均玩幾局 Free Spin（含重置帶來的延長）
    """
    T = build_transition_matrix(config, retrigger_prob)  # 完整 (N+1)×(N+1) 吸收矩陣

    Q = T[1:, 1:]                                       # 暫態子矩陣（剔除吸收態 0，留狀態 1~N）
    identity = np.eye(Q.shape[0])                       # 與 Q 同維的單位矩陣 I
    fundamental = np.linalg.inv(identity - Q)           # 基本矩陣 M = (I - Q)^(-1)
    steps_to_absorb = fundamental.sum(axis=1)           # 每列總和 = 各起始狀態到吸收的期望步數

    return float(steps_to_absorb[-1])                   # 最後一項 = 從狀態 N（滿局）出發的 E[FS]


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
    print(f"    觸發機率     : {result.trigger_prob * 100:.2f}%(每局一般遊戲)")
    print(f"    每次給局數   : {cfg.free_spin_count} 局")
    print(f"    Retrigger 率 : {result.retrigger_prob * 100:.2f}%（重置為 N 局）")
    print(f"    贏分倍率     : {cfg.win_multiplier}x")
    print()
    print(f"  穩態分佈:")
    print(f"    一般模式     : {result.pi_normal * 100:.4f}% 的時間")
    print(f"    Free Spin    : {result.pi_free * 100:.4f}% 的時間")
    print(f"    平均每觸發一次 Free Spin, 可得 {result.expected_fs_spins:.1f} 局")
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
