"""
markov_freespin_rtp.py - 多線 Free Spin 馬可夫鏈模型

在多線捲軸帶架構上套用 Free Spin 狀態機，計算整體理論 RTP。
馬可夫鏈的轉移矩陣與穩態解析公式完全沿用 core/markov.py；
唯一差異是 base_rtp 改從 core/calculator.py 取得（每線標準化 RTP）。

這正是模組化設計的價值：狀態機數學與底層 spin 函式彼此解耦，
替換 base_rtp 來源就能讓 Free Spin 模型支援任意遊戲架構。
"""

from math import comb

from core.config import FS_MIN_SCATTER
from core.markov import (
    FreespinConfig,
    MarkovResult,
    build_transition_matrix,
    expected_fs_spins,
)
from core.calculator import calculate_rtp
from core.reel import REEL_STRIPS, ReelStrip


def scatter_trigger_prob(reel_strips: list[ReelStrip], min_scatter: int = FS_MIN_SCATTER) -> float:  # 從捲軸帶計算 Scatter 觸發機率
    """
    計算至少 min_scatter 條捲軸的可見視窗（3 行）包含 Scatter 的機率。

    遍歷捲軸 0 的所有停格，算出每個停格是否在視窗中出現 Scatter，
    再用二項分佈計算「5 軸中至少 min_scatter 軸同時觸發」的機率。

    ⚠ 假設「所有捲軸帶相同」：只取 reel_strips[0] 算單軸機率 p_single，
      再以二項分佈（每軸同機率）推估。本專案的捲軸一律為 [同一 strip] × 5，故此假設成立。
      若未來改成異質捲軸（各軸 Scatter 分佈不同），此函式會失準——
      需改用 Poisson-binomial（逐軸不同 p）才正確。
      （註：core/calculator.py 的 RTP 計算已支援異質捲軸，兩者通用性不對稱，異動捲軸設計時請留意。）

    Args:
        reel_strips: 捲軸帶列表（假設所有捲軸帶相同，僅取第一條代表計算）
        min_scatter: 觸發所需最少捲軸數，預設 3

    Returns:
        Free Spin 觸發機率（浮點數）
    """
    reel = reel_strips[0]          # 所有捲軸帶相同，取第一條代表計算
    n = len(reel_strips)           # 捲軸總數（5）

    # 計算單一捲軸視窗包含 Scatter 的停格數
    scatter_stop_count = sum(
        1 for stop in range(reel.total_stops)
        if "Scatter" in reel.window(stop)
    )
    p_single = scatter_stop_count / reel.total_stops  # P(單軸視窗出現 Scatter)
    p_fail   = 1 - p_single                           # P(單軸視窗不出現 Scatter)

    # 二項分佈累積：至少 min_scatter 軸同時出現 Scatter 的機率
    trigger_prob = 0.0
    for k in range(min_scatter, n + 1):         # k：同時出現 Scatter 的軸數
        ways  = comb(n, k)                      # 從 n 軸選 k 軸的組合數
        hit   = p_single ** k                   # k 軸全部命中的機率
        miss  = p_fail   ** (n - k)             # 其餘 (n-k) 軸全部未命中的機率
        trigger_prob += ways * hit * miss       # P(恰好 k 軸出現 Scatter)
    return trigger_prob


def calculate_freespin_rtp(  # 計算多線含 Free Spin 的整體理論 RTP
    config: FreespinConfig,
    reel_strips: list[ReelStrip] = REEL_STRIPS,
) -> MarkovResult:
    """
    計算多線機台加入 Free Spin 後的整體理論 RTP。

    觸發機率與重置觸發機率「都」由捲軸帶的 Scatter 分佈自動衍生，且兩者相等
    （本遊戲一般局與 FS 共用同一條捲軸、同樣 ≥3 Scatter 條件）。
    因此 p、r 不是 config 的欄位，而是在此算出後以參數傳入馬可夫函式，
    config 只有 free_spin_count（N）與 win_multiplier（M）兩個可調旋鈕——
    這確保數學模型與實際捲軸行為一致，retrigger 不是可獨立調整的旋鈕。

    RTP 公式（更新-回報定理；p·E[FS] = FS 局數 / 一般局數 的長期比例）：
        total_rtp = base_rtp × (1 + p · E[FS] · win_multiplier)
    其中 E[FS] 由「=N 重置」的 (N+1) 狀態吸收鏈精確求得（見 expected_fs_spins）。

    Args:
        config: Free Spin 參數設定（free_spin_count=N、win_multiplier=M）
        reel_strips: 自訂捲軸帶列表（None 表示使用預設 REEL_STRIPS）

    Returns:
        MarkovResult，欄位定義與單線版本相同（可直接交給 dashboard 顯示），
        其 trigger_prob／retrigger_prob 為本函式由捲軸衍生的實際生效值
    """
    reel_strips = reel_strips or REEL_STRIPS  # 顯式傳入 None 時兜底為預設捲軸帶（scatter_trigger_prob 與 calculate_rtp 都需要）
    base_rtp = calculate_rtp(reel_strips=reel_strips).rtp_per_line  # 每線標準化 RTP

    # 觸發機率由捲軸帶 Scatter 分佈衍生；重置觸發機率 = 同一個觸發機率
    # （FS 與一般局共用捲軸、條件相同），兩者以參數傳入馬可夫函式，非 config 欄位
    derived_trigger_prob = scatter_trigger_prob(reel_strips)  # 衍生觸發機率 p（= 重置觸發機率 r）

    T = build_transition_matrix(config, derived_trigger_prob)          # (N+1)×(N+1) 吸收轉移矩陣（狀態 i=剩餘局數）
    expected_fs = expected_fs_spins(config, derived_trigger_prob)      # 精確平均 FS 局數 E[FS]（吸收鏈）

    fs_per_base = derived_trigger_prob * expected_fs     # p·E[FS] = FS局數 / 一般局數 的長期比例
    pi_normal = 1 / (1 + fs_per_base)                    # 一般模式時間比例（更新-回報）
    pi_free = 1 - pi_normal                              # Free Spin 模式時間比例（互補）

    total_rtp = base_rtp * (1 + fs_per_base * config.win_multiplier)  # 含 FS 倍率 M 的整體 RTP
    freespin_contribution = total_rtp - base_rtp          # Free Spin 單獨貢獻的 RTP 增量

    return MarkovResult(
        config=config,
        transition_matrix=T,
        pi_normal=pi_normal,
        pi_free=pi_free,
        base_rtp=base_rtp,
        total_rtp=total_rtp,
        freespin_contribution=freespin_contribution,
        trigger_prob=derived_trigger_prob,    # 實際生效的觸發機率（衍生值）
        retrigger_prob=derived_trigger_prob,  # 實際生效的重置觸發機率（= 觸發機率）
        expected_fs_spins=expected_fs,        # 一次觸發平均 FS 局數 E[FS]
    )


if __name__ == "__main__":
    from core.markov import print_markov_report
    from core.config import DEFAULT_FS_CONFIG

    result = calculate_freespin_rtp(DEFAULT_FS_CONFIG)
    print("多線版本（base_rtp 來自多線捲軸帶，trigger_prob 由 Scatter 自動計算）：")
    print_markov_report(result)
