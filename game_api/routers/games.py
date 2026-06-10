"""
routers/games.py - 遊戲路由（多線 5×3 格式）

提供下注、旋轉與遊戲設定查詢：
    GET  /api/v1/games/config — 遊戲靜態設定（賠付表、付線、符號、FS 規則）
    POST /api/v1/games/spin   — 旋轉一局（押滿 5 線），前端驅動 Free Spin 模式
"""

from decimal import Decimal

from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy.orm import Session

from core.config import DEFAULT_FS_CONFIG, FS_MIN_SCATTER
from core.paytable import PAYTABLE
from core.reel import NUM_REELS, PAYLINE_NAMES, REEL_CONFIG
from game_api.database import get_db
from game_api.dependencies import get_current_player
from game_api.models import Player, SpinHistory
from game_api.schemas import (
    FreeSpinConfigResponse,
    GameConfigResponse,
    PaylineDef,
    PaytableEntry,
    SpinResponse,
)
from simulator.engine import spin, PAYLINES

router = APIRouter(prefix="/api/v1/games", tags=["games"])  # 所有端點自動加上 /api/v1/games 前綴

_NUM_LINES = Decimal(len(PAYLINES))  # 付線數（5），用於賠付換算
_FS_MULTIPLIER = Decimal(str(DEFAULT_FS_CONFIG.win_multiplier))  # Free Spin 賠付倍率，轉 Decimal 確保精度
_DEFAULT_BET = 10.0  # 預設押注金額（元），給前端作為下注初值


@router.get("/config", response_model=GameConfigResponse)  # 取得遊戲靜態設定（不需登入）
def get_game_config() -> GameConfigResponse:
    """
    回傳遊戲靜態設定（賠付表、付線、符號清單、FS 規則）。

    前端啟動時呼叫一次即可——資料在遊戲過程中不會改變。
    若後端調整捲軸或賠付，前端只需重新呼叫此端點即可同步。

    Returns:
        GameConfigResponse，含 reels/rows/symbols/paylines/paytable/free_spin/default_bet
    """
    paylines = [
        PaylineDef(index=i, name=PAYLINE_NAMES[i], positions=list(positions))  # 將 tuple 轉 list 方便 JSON 序列化
        for i, positions in enumerate(PAYLINES)
    ]

    paytable = [
        PaytableEntry(symbol=entry.symbol_name, count=entry.required_count, multiplier=entry.multiplier)
        for entry in PAYTABLE
    ]

    fs = FreeSpinConfigResponse(
        min_scatter=FS_MIN_SCATTER,                          # 觸發門檻（≥FS_MIN_SCATTER 軸 Scatter）
        free_spin_count=DEFAULT_FS_CONFIG.free_spin_count,
        win_multiplier=DEFAULT_FS_CONFIG.win_multiplier,
    )

    return GameConfigResponse(
        reels=NUM_REELS,                     # 捲軸數，從 core.reel 的唯一來源讀取
        rows=3,                              # 5×3 機台固定 3 行
        symbols=list(REEL_CONFIG.keys()),    # 符號清單（含 Blank、Wild、Scatter）
        reel_config=dict(REEL_CONFIG),       # 每符號格數，前端可顯示出現機率
        paylines=paylines,
        paytable=paytable,
        free_spin=fs,
        default_bet=_DEFAULT_BET,
    )


@router.post("/spin", response_model=SpinResponse, status_code=200)  # 旋轉成功回 200
def do_spin(  # 旋轉一局：判斷模式 → 旋轉 → 結算 → 寫入 DB
    bet_amount: Decimal = Form(Decimal("10"), gt=0, description="本局總押注金額（元），預設 10 元"),
    player: Player = Depends(get_current_player),  # JWT 驗證，自動取得當前玩家
    db: Session = Depends(get_db),
) -> SpinResponse:
    """
    旋轉一局多線老虎機（押滿 5 條付線）。

    前端驅動 Free Spin：觸發後 free_spins_remaining 寫入 Player，
    玩家每次按 SPIN 都呼叫此端點，後端依 free_spins_remaining 判斷當局是否免費。

    一般局流程：
        1. 確認餘額 ≥ bet_amount（不足 → 400）
        2. 旋轉，扣款，計算賠付
        3. 若觸發 FS（scatter_count ≥ 3）：free_spins_remaining = FS_FREE_SPIN_COUNT
                                          fs_locked_bet = 本局押注（鎖定，防作弊）

    Free Spin 局流程：
        1. 不扣款（免費）
        2. 使用 fs_locked_bet 計算賠付（忽略前端送的 bet_amount，防止 FS 中改押注作弊）
        3. 賠付 × win_multiplier
        4. free_spins_remaining -= 1
        5. 若 scatter_count ≥ FS_MIN_SCATTER：重置為 FS_FREE_SPIN_COUNT 局（retrigger，= N 非 +N）
           否則若 free_spins_remaining == 0：FS 結束，fs_locked_bet 清為 0

    Args:
        bet_amount: 本局押注金額（Form 欄位）；FS 局忽略此值，改用 player.fs_locked_bet
        player:     由 get_current_player 注入的 Player ORM 物件
        db:         資料庫 Session（由 FastAPI 依賴注入）

    Returns:
        SpinResponse，含旋轉結果、is_free_spin、awarded_new_fs、free_spins_remaining、賠付與餘額

    Raises:
        HTTPException 401: Token 無效或已過期（由 get_current_player 拋出）
        HTTPException 400: 餘額不足（僅一般局檢查）
    """
    balance_before = player.balance  # ORM 回傳 Decimal（Numeric 欄位），直接使用
    is_free_spin = player.free_spins_remaining > 0  # 剩餘 FS 局數 > 0 → 本局免費

    # 決定本局實際押注：FS 期間忽略前端送的 bet_amount，使用觸發時鎖定的金額（防作弊）
    if is_free_spin:
        effective_bet = player.fs_locked_bet  # 用觸發 FS 那刻的押注（Decimal），前端改值無效
    else:
        effective_bet = bet_amount  # 一般局：使用前端送的押注

    # 一般局才檢查餘額（FS 局免費，不扣款）
    if not is_free_spin and balance_before < effective_bet:
        raise HTTPException(status_code=400, detail=f"餘額不足（需要 {effective_bet}，目前 {balance_before}）")

    outcome = spin()  # 旋轉：隨機抽 5 軸停格、評估 5 條付線、偵測 Scatter

    # ── 賠付計算 ────────────────────────────────────────────────────────────────
    base_multiplier = Decimal(str(outcome.total_multiplier))  # 付線合計倍率
    if is_free_spin:
        payout = effective_bet * base_multiplier * _FS_MULTIPLIER / _NUM_LINES  # FS 局：賠付 × win_multiplier，不扣押注
        balance_after = balance_before + payout                                   # 不扣款，純加賠付
    else:
        payout = effective_bet * base_multiplier / _NUM_LINES  # 一般局：標準賠付公式
        balance_after = balance_before - effective_bet + payout  # 扣押注後加賠付

    # ── Free Spin 狀態更新 ──────────────────────────────────────────────────────
    awarded_new_fs = False  # 本局是否獲得新一輪 FS（觸發或 retrigger，給前端播放「FS!」橫幅用）
    if is_free_spin:
        player.free_spins_remaining -= 1  # 消耗一局 FS
        if outcome.free_spin_triggered:  # Scatter retrigger：任何 FS 局都可重置（fs_locked_bet 保持不變）
            player.free_spins_remaining = DEFAULT_FS_CONFIG.free_spin_count  # 重置為 N 局（= N，非 +N）
            awarded_new_fs = True
        elif player.free_spins_remaining == 0:  # 沒有 Scatter retrigger 且用完所有局數：FS 結束
            player.fs_locked_bet = 0  # 清掉鎖定押注，下一局玩家可自由調整
    elif outcome.free_spin_triggered:
        player.free_spins_remaining = DEFAULT_FS_CONFIG.free_spin_count  # 一般局觸發 FS：設定剩餘局數
        player.fs_locked_bet = effective_bet  # 鎖定觸發 FS 時的押注金額，FS 期間無法更改
        awarded_new_fs = True  # 一般局首次觸發

    player.balance = balance_after  # 寫回 ORM（Decimal，保留精度）

    history = SpinHistory(
        player_id=player.id,
        bet_amount=float(effective_bet),  # 記錄實際押注（FS 局 = 鎖定值）
        stops="|".join(str(s) for s in outcome.stops),                              # (5,12,3,18,0) → "5|12|3|18|0"
        payline_multipliers="|".join(str(m) for m in outcome.payline_multipliers),  # [0,5,0,...] → "0|5|0|..."
        total_multiplier=outcome.total_multiplier,
        scatter_count=outcome.scatter_count,
        is_free_spin=is_free_spin,
        payout=float(payout),
        balance_before=float(balance_before),
        balance_after=float(balance_after),
    )
    db.add(history)
    db.commit()
    db.refresh(history)  # 取回 DB 自動填入的 id 與 created_at

    return SpinResponse(
        spin_id=history.id,
        stops=list(outcome.stops),
        grid=outcome.grid,
        payline_multipliers=outcome.payline_multipliers,
        total_multiplier=outcome.total_multiplier,
        scatter_count=outcome.scatter_count,
        is_free_spin=is_free_spin,
        awarded_new_fs=awarded_new_fs,
        free_spins_remaining=player.free_spins_remaining,
        fs_locked_bet=Decimal(str(player.fs_locked_bet)),  # 給前端鎖定押注 UI
        bet_amount=effective_bet,                          # 本局實際使用的押注（FS 局 = 鎖定值）
        payout=payout,
        balance_before=balance_before,
        balance_after=balance_after,
    )
