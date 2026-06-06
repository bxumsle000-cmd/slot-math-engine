"""
schemas.py - Pydantic 請求／回應模型

定義 API 的輸入驗證與輸出格式。
Pydantic 會在收到請求時自動檢查欄位型別與條件，不合格直接回 422。
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class TokenResponse(BaseModel):  # POST /auth/login 的回應格式
    """
    JWT token 回應格式。

    Args:
        access_token: JWT 字串，有效期 24 小時
        token_type:   固定為 "bearer"，符合 OAuth2 規範
    """

    access_token: str  # JWT 字串，前端存起來，後續請求放在 Authorization: Bearer <token>
    token_type: str    # 固定值 "bearer"，告知前端如何帶在 header


class SpinResponse(BaseModel):  # POST /api/v1/games/spin 的回應格式
    """
    多線旋轉結果回應（5×3 格式，5 條付線）。

    Args:
        spin_id:              本局旋轉在 DB 的唯一 id（供後續查詢或稽核）
        stops:                五捲軸的停格位置（0-indexed），前端據此播放捲軸動畫
        grid:                 3×5 可見符號方格，grid[行][捲軸]，行 0=上、1=中、2=下
        payline_multipliers:  各付線賠付倍率列表（長度 = 付線數），0 表示該線未中獎
        total_multiplier:     所有付線倍率總和（押滿線的本局總賠付倍率）
        scatter_count:        出現 Scatter 的捲軸數（0–5）
        is_free_spin:         本局是否為 Free Spin 局（True = 免費，賠付已乘 win_multiplier）
        awarded_new_fs:       本局是否獲得新一輪 FS 局數（一般局觸發 OR FS 內 retrigger 命中）
        free_spins_remaining: 本局結算後剩餘的 FS 局數（0 = 已回到一般模式）
        fs_locked_bet:        FS 期間鎖定的押注金額（0 = 非 FS 狀態，前端可據此鎖定押注 UI）
        bet_amount:           本局實際使用的押注金額（FS 局 = fs_locked_bet，一般局 = 玩家輸入）
        payout:               實際賠付金額
        balance_before:       旋轉前餘額
        balance_after:        旋轉後餘額
    """

    spin_id: int                       # 本局旋轉在 DB 的唯一 id（供後續查詢或稽核）
    stops: list[int]                   # 五捲軸停格位置，例如 [5, 12, 3, 18, 0]
    grid: list[list[str]]              # 3×5 可見符號方格，grid[行][捲軸]
    payline_multipliers: list[int]     # 各付線賠付倍率，長度 = 5（付線數）
    total_multiplier: int              # 所有付線倍率總和（0 = 全線未中獎）
    scatter_count: int                 # 出現 Scatter 的捲軸數（0–5）
    is_free_spin: bool                 # 本局是否為 Free Spin 局（True = 免費，賠付已乘 win_multiplier）
    awarded_new_fs: bool               # 本局是否獲得新一輪 FS 局數（一般局觸發 OR FS 內 retrigger 命中）
    free_spins_remaining: int          # 本局結算後剩餘的 FS 局數（0 = 已回到一般模式）
    fs_locked_bet: Decimal             # FS 期間鎖定的押注金額（0 = 非 FS 狀態，前端可據此鎖定押注 UI）
    bet_amount: Decimal                # 本局實際使用的押注金額（FS 局 = fs_locked_bet，一般局 = 玩家輸入）
    payout: Decimal                    # 實際賠付金額
    balance_before: Decimal            # 旋轉前餘額
    balance_after: Decimal             # 旋轉後餘額

    model_config = {"from_attributes": True}  # 允許從 ORM 物件直接轉換


class SpinHistoryItem(BaseModel):  # GET /players/me/spins 單筆旋轉記錄格式
    """
    單筆旋轉歷史記錄（多線格式）。

    net_pl = balance_after - balance_before：正數為贏，負數為輸。
    一般局淨損益 = payout - bet_amount；FS 局免費（押注不扣），淨損益 = payout。
    驗算等式：balance_before + net_pl = balance_after（一般局與 FS 局皆成立）。

    Args:
        spin_id:          旋轉記錄唯一識別碼（供客服查詢用）
        created_at:       旋轉時間
        bet_amount:       押注金額（元，= 每線押注 × 付線數）；FS 局為觸發時鎖定值（實際未扣款）
        is_free_spin:     本局是否為 Free Spin 免費局（True = 不扣押注，前端據此標記「免費」）
        total_multiplier: 本局所有付線倍率總和（0 = 全未中獎）
        result:           中獎描述，例如 "付線1: 5x, 付線3: 10x（合計 15x）"，未中獎為 "未中獎"
        net_pl:           本局損益 = balance_after - balance_before（正＝贏，負＝輸）
        balance_before:   旋轉前餘額（稽核快照）
        balance_after:    旋轉後餘額（稽核快照）
    """

    spin_id: int              # 旋轉記錄唯一識別碼（供客服查詢用）
    created_at: datetime      # 旋轉時間
    bet_amount: Decimal       # 押注金額（元，= 每線押注 × 付線數）；FS 局為鎖定值（實際未扣款）
    is_free_spin: bool        # 本局是否為 Free Spin 免費局（True = 不扣押注）
    total_multiplier: int     # 本局所有付線倍率總和（0 = 全未中獎）
    result: str               # 中獎描述，例如 "付線1: 5x, 付線3: 10x（合計 15x）"，未中獎為 "未中獎"
    net_pl: Decimal           # 本局損益 = balance_after - balance_before（正＝贏，負＝輸）
    balance_before: Decimal   # 旋轉前餘額（稽核快照）
    balance_after: Decimal    # 旋轉後餘額（稽核快照）

    model_config = {"from_attributes": True}  # 允許從 ORM 物件直接轉換


class SpinHistoryResponse(BaseModel):  # GET /players/me/spins 分頁回應格式
    """
    旋轉歷史的分頁回應，包含本頁資料與分頁資訊。

    Args:
        items: 本頁的旋轉記錄列表
        page:  當前頁碼（從 1 開始）
        size:  每頁筆數
        total: 符合篩選條件的總筆數
    """

    items: list[SpinHistoryItem]  # 本頁旋轉記錄
    page: int                     # 當前頁碼
    size: int                     # 每頁筆數
    total: int                    # 總筆數（用於前端計算總頁數）


class PaylineDef(BaseModel):  # 單條付線的定義
    """
    單條付線定義：行索引序列 + 顯示名稱。

    前端可用 positions 在畫面上畫出付線軌跡。

    Args:
        index:     付線編號（0-indexed）
        name:      顯示名稱，例如 "中排"、"V形"
        positions: 每條捲軸對應的行索引，0=上排、1=中排、2=下排，ex:V形= [0,1,2,1,0]
    """

    index: int                  # 付線編號（0-indexed）
    name: str                   # 顯示名稱，例如 "中排"、"V形"
    positions: list[int]        # 每條捲軸對應的行索引，0=上排、1=中排、2=下排，ex:V形= [0,1,2,1,0]


class PaytableEntry(BaseModel):  # 單筆賠付規則
    """
    賠付表中的一筆規則。

    Args:
        symbol:     符號名稱
        count:      所需連線數（3、4、5）
        multiplier: 賠付倍率
    """

    symbol: str                 # 符號名稱
    count: int                  # 所需連線數（3、4、5）
    multiplier: int             # 賠付倍率


class FreeSpinConfigResponse(BaseModel):  # Free Spin 設定回應格式
    """
    Free Spin 規則設定，前端用此顯示「免費局 10 局、3 倍賠付」等資訊。

    Args:
        min_scatter:     觸發所需 Scatter 條數（≥）
        free_spin_count: 每次觸發給幾局
        win_multiplier:  FS 期間賠付倍率
    """

    min_scatter: int            # 觸發所需 Scatter 條數（≥）
    free_spin_count: int        # 每次觸發給幾局
    win_multiplier: float       # FS 期間賠付倍率


class GameConfigResponse(BaseModel):  # GET /api/v1/games/config 的回應格式
    """
    遊戲靜態設定，給前端取得賠付表、付線、符號清單與 Free Spin 規則。

    前端啟動時呼叫一次即可（資料不會在遊戲過程中改變）。

    Args:
        reels:       捲軸數（5）
        rows:        行數（3）
        symbols:     所有符號清單，例如 ["Blank", "Cherry", ...]
        reel_config: 每個符號在單條捲軸上的格數，前端可顯示機率
        paylines:    所有付線定義（5 條）
        paytable:    賠付規則列表（由高到低）
        free_spin:   Free Spin 設定
        default_bet: 預設押注金額（前端可作為下注初值）
    """

    reels: int                              # 捲軸數（5）
    rows: int                               # 行數（3）
    symbols: list[str]                      # 所有符號清單，例如 ["Blank", "Cherry", ...]
    reel_config: dict[str, int]             # 每個符號在單條捲軸上的格數，前端可顯示機率
    paylines: list[PaylineDef]              # 所有付線定義（5 條）
    paytable: list[PaytableEntry]           # 賠付規則列表（由高到低）
    free_spin: FreeSpinConfigResponse       # Free Spin 設定
    default_bet: float                      # 預設押注金額（前端可作為下注初值）


class PlayerResponse(BaseModel):  # 玩家相關端點的回應格式
    """
    玩家資料回應格式，對應 Player ORM 物件。

    model_config 的 from_attributes=True 讓 Pydantic 可以直接讀取
    SQLAlchemy ORM 物件的屬性，不需要手動轉成 dict。

    Args:
        id:                   玩家唯一識別碼
        username:             帳號名稱
        balance:              當前餘額（元）
        free_spins_remaining: 剩餘 Free Spin 局數（0 = 一般模式）
        fs_locked_bet:        FS 期間鎖定的押注金額（0 = 非 FS 狀態）
        created_at:           帳號建立時間
    """

    id: int  # 玩家唯一識別碼
    username: str  # 帳號名稱
    balance: Decimal  # 當前餘額（元）
    free_spins_remaining: int  # 剩餘 Free Spin 局數（0 = 一般模式）
    fs_locked_bet: Decimal  # FS 期間鎖定的押注金額（0 = 非 FS 狀態）
    created_at: datetime  # 帳號建立時間

    model_config = {"from_attributes": True}  # 允許從 ORM 物件直接轉換，SQLAlchemy 2.0 必要設定
