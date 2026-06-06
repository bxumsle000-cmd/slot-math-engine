"""
routers/players.py - 玩家 CRUD 路由

提供玩家建立、查詢、儲值與歷史記錄查詢功能：
    POST /players            — 建立新玩家
    GET  /players/me         — 查詢當前登入玩家（需 JWT）
    GET  /players/me/spins   — 查詢旋轉歷史（需 JWT，支援分頁與日期篩選）
    POST /players/me/deposit — 儲值（需 JWT）
"""

from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from game_api.password import hash_password
from game_api.database import get_db
from game_api.dependencies import get_current_player
from game_api.models import Player, SpinHistory
from game_api.schemas import (
    PlayerResponse,
    SpinHistoryItem,
    SpinHistoryResponse,
)
from simulator.engine import PAYLINES

_NUM_LINES = len(PAYLINES)  # 付線數（5），用於把原始倍率換算成玩家直觀倍率

# 所有端點自動加上 /api/v1/players 前綴
router = APIRouter(prefix="/api/v1/players", tags=["players"])

# 建立成功回 201 Created
@router.post("", response_model=PlayerResponse, status_code=201)  
def create_player(  # 建立新玩家帳號
    username: str = Form(..., min_length=1, max_length=50, description="帳號名稱"),
    password: str = Form(..., min_length=6, description="登入密碼（至少 6 字元）"),
    initial_balance: Decimal = Form(Decimal("0"), ge=0, description="初始儲值金額（元）"),
    db: Session = Depends(get_db),
) -> Player:
    """
    建立新玩家。

    Args:
        username:        帳號名稱（Form 欄位），1～50 字元
        password:        登入密碼（Form 欄位），至少 6 字元，存 DB 前會雜湊
        initial_balance: 初始儲值金額（Form 欄位），預設 0，不可負數
        db:              資料庫 Session（由 FastAPI 依賴注入）

    Returns:
        建立成功的 Player 物件

    Raises:
        HTTPException 409: username 已存在
    """
    player = Player(
        username=username,
        password_hash=hash_password(password),  # 明文密碼 → bcrypt 雜湊，不存原始密碼
        balance=initial_balance,
    )
    db.add(player)  # 把物件加入 Session，標記為「待新增」

    try:
        db.commit()  # 提交交易，INSERT 正式寫入 MySQL
    except IntegrityError:  # username UNIQUE 衝突時 MySQL 會拋出此例外
        db.rollback()  # 撤銷本次交易，Session 恢復乾淨狀態
        raise HTTPException(status_code=409, detail="帳號名稱已存在")

    db.refresh(player)  # 從 DB 重新讀取，取得 MySQL 自動填入的 id 與 created_at
    return player


@router.get("/me", response_model=PlayerResponse)  # 查詢當前登入玩家（由 JWT 識別）
def get_me(  # 從 JWT token 取得當前玩家資料
    current_player: Player = Depends(get_current_player),
) -> Player:
    """
    查詢當前登入玩家的資料。身份由 JWT Bearer token 決定，不需傳 id。

    Args:
        current_player: 由 get_current_player 注入的 Player ORM 物件

    Returns:
        當前登入的 Player 物件
    """
    return current_player


@router.get("/me/spins", response_model=SpinHistoryResponse)  # 查詢旋轉歷史（需 JWT）
def get_spins(  # 查詢當前玩家的旋轉歷史，支援分頁與日期篩選
    current_player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, description="頁碼，從 1 開始"),
    size: int = Query(20, ge=1, le=100, description="每頁筆數，最大 100"),
    from_date: date | None = Query(None, description="開始日期（含），格式 YYYY-MM-DD"),
    to_date: date | None = Query(None, description="結束日期（含），格式 YYYY-MM-DD"),
) -> SpinHistoryResponse:
    """
    查詢當前登入玩家的旋轉歷史記錄，由新到舊排序。

    Args:
        current_player: 由 get_current_player 注入的 Player ORM 物件
        db:        資料庫 Session（依賴注入）
        page:      頁碼，從 1 開始
        size:      每頁筆數，最大 100
        from_date: 篩選起始日期（含，台灣時間 00:00:00）
        to_date:   篩選結束日期（含，台灣時間 23:59:59）

    Returns:
        SpinHistoryResponse，含本頁記錄與分頁資訊
    """
    query = (
        db.query(SpinHistory)
        .filter(SpinHistory.player_id == current_player.id)  # 只查自己的記錄
    )

    if from_date:
        query = query.filter(
            SpinHistory.created_at >= datetime(from_date.year, from_date.month, from_date.day, 0, 0, 0)
        )  # 起始日期 00:00:00
    if to_date:
        query = query.filter(
            SpinHistory.created_at <= datetime(to_date.year, to_date.month, to_date.day, 23, 59, 59)
        )  # 結束日期 23:59:59

    total = query.count()  # 符合篩選條件的總筆數（分頁前）
    records = (
        query
        .order_by(SpinHistory.created_at.desc())  # 由新到舊
        .offset((page - 1) * size)                # 跳過前幾頁
        .limit(size)                               # 只取本頁筆數
        .all()
    )

    items = [
        SpinHistoryItem(
            spin_id=r.id,
            created_at=r.created_at,
            bet_amount=r.bet_amount,
            is_free_spin=r.is_free_spin,           # FS 局標記，前端據此顯示「免費」並理解押注未扣
            total_multiplier=r.total_multiplier,
            result=_format_result(r),              # 中獎描述或"未中獎"
            net_pl=r.balance_after - r.balance_before,  # 損益 = 餘額變動（FS 局免費不扣押注，此式恆正確）
            balance_before=r.balance_before,
            balance_after=r.balance_after,
        )
        for r in records
    ]

    return SpinHistoryResponse(items=items, page=page, size=size, total=total)


def _format_result(r: SpinHistory) -> str:  # 將 DB 的多線結果格式化成可讀字串
    """
    依 total_multiplier 與 payline_multipliers 產生可讀的中獎描述。

    未中獎回傳 "未中獎"；有中獎則列出各付線倍率，例如 "付線1: 5x, 付線3: 10x（合計 15x）"。
    """
    if r.total_multiplier == 0:
        return "未中獎"
    multipliers = [int(m) for m in r.payline_multipliers.split("|")]  # "0|5|0|..." → [0, 5, 0, ...]
    # 顯示換算後倍率 = 原始倍率 ÷ 付線數，與賠付表、動畫文字一致（x3 → x0.6）
    # 用 :g 去掉多餘小數（2.0 顯示為 2，0.6 維持 0.6）
    winning_lines = [
        f"付線{i + 1}: {m / _NUM_LINES:g}x"  # 單線換算後倍率
        for i, m in enumerate(multipliers)
        if m > 0
    ]
    total_display = r.total_multiplier / _NUM_LINES  # 合計換算後倍率
    return ", ".join(winning_lines) + f"（合計 {total_display:g}x）"



@router.post("/me/deposit", response_model=PlayerResponse)  # 儲值成功回 200
def deposit(  # 玩家儲值：從 JWT 識別身份 → 加值 → 更新餘額
    amount: Decimal = Form(..., gt=0, description="儲值金額（元），必須大於 0"),
    current_player: Player = Depends(get_current_player),  # JWT 驗證，取得當前登入玩家
    db: Session = Depends(get_db),
) -> Player:
    """
    儲值（增加餘額）。玩家身份由 JWT 決定，不需在 URL 帶 id。

    Args:
        amount:         儲值金額（Form 欄位），必須大於 0
        current_player: 由 get_current_player 注入的當前登入玩家
        db:             資料庫 Session（由 FastAPI 依賴注入）

    Returns:
        儲值後的 Player 物件（含更新後的 balance）

    Raises:
        HTTPException 401: Token 無效或已過期（由 get_current_player 拋出）
    """
    current_player.balance += amount  # 舊餘額（Decimal）+ 儲值金額，保留精度
    db.commit()        # 寫入更新後的餘額
    db.refresh(current_player)  # 從 DB 重新讀取，確保回傳值與 DB 一致
    return current_player
