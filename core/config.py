"""
core/config.py - 遊戲參數統一設定檔

所有模組（API、模擬器、Dashboard）的預設參數統一從這裡讀取，
避免各檔案各自硬編碼導致數值不一致。
"""

from core.markov import FreespinConfig


# ── Free Spin 機制參數 ──────────────────────────────────────────────────────────
FS_FREE_SPIN_COUNT: int = 10     # 每次觸發給幾局 Free Spin
FS_WIN_MULTIPLIER: float = 3.0   # Free Spin 期間的賠付倍率（3 倍）
FS_MIN_SCATTER: int = 3          # 觸發 Free Spin 所需的最少 Scatter 捲軸數

# retrigger 機制：FS 期間每一局出現 ≥ FS_MIN_SCATTER 個 Scatter 即追加局數，
DEFAULT_FS_CONFIG = FreespinConfig(  # 預設 Free Spin 設定，供 API 與模擬器共用
    free_spin_count=FS_FREE_SPIN_COUNT,  # 每次觸發給幾局（真正生效的設定）
    win_multiplier=FS_WIN_MULTIPLIER,    # FS 期間賠付倍率（真正生效的設定）
)

# ── 玩家旅程模擬預設參數 ────────────────────────────────────────────────────────
SIM_NUM_PLAYERS: int = 100          # 預設模擬玩家數
SIM_STARTING_BALANCE: float = 1000.0  # 預設起始餘額（單位：單線押注額）
SIM_STOP_LOSS: float = 0.0           # 預設停損線（餘額 ≤ 0 即停止）
SIM_STOP_WIN: float = 2000.0         # 預設停利線（餘額 ≥ 2000 即停止）
SIM_MAX_SPINS: int = 500             # 預設每位玩家最大局數
