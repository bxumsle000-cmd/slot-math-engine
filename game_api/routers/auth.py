"""
routers/auth.py - 登入端點（Google 登入）

提供 token 取得功能：
    POST /auth/google — 驗證 Google id_token，回傳本站 JWT access token

身分一律來自 Google 登入（OpenID Connect）：前端拿到 Google 簽發的 id_token，
後端驗證通過後，用 google_sub 找帳號（沒有就建一個），再簽發本站自己的 JWT。
後續所有 API 仍靠本站 JWT 驗證（get_current_player）。
"""

from decimal import Decimal

from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from game_api.database import get_db
from game_api.dependencies import create_access_token
from game_api.google_oauth import GoogleAuthError, verify_google_id_token
from game_api.models import Player
from game_api.schemas import TokenResponse

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])  # 所有端點自動加上 /api/v1/auth 前綴

_NEW_PLAYER_BALANCE = Decimal("1000")  # 新玩家首次 Google 登入時贈送的初始金幣


@router.post("/google", response_model=TokenResponse)  # 登入成功回 200
def login_with_google(  # 驗證 Google id_token，回傳本站 JWT token
    id_token: str = Form(..., description="Google Identity Services 回傳的 id_token"),
    db: Session = Depends(get_db),
) -> TokenResponse:
    """
    驗證 Google id_token，回傳本站 JWT access token。

    流程：驗證 Google token → 用 google_sub 找玩家 → 找不到就自動建新玩家
    （贈送初始金幣）→ 簽發本站 JWT。

    Args:
        id_token: 前端從 Google 登入取得的 id_token（Form 欄位）
        db:       資料庫 Session（依賴注入）

    Returns:
        TokenResponse，含 access_token 與 token_type

    Raises:
        HTTPException 401: Google id_token 驗證失敗（簽章/aud/exp 錯誤或 email 未驗證）
    """
    try:
        identity = verify_google_id_token(id_token)  # 驗證並萃取 sub / email / name
    except GoogleAuthError:
        # 不回傳細節，避免洩漏驗證邏輯；驗證失敗一律視為未授權
        raise HTTPException(status_code=401, detail="Google 登入失敗")

    # SQL: SELECT * FROM players WHERE google_sub = %s LIMIT 1;
    player = db.query(Player).filter(Player.google_sub == identity.sub).first()  # 以 Google sub 認帳號

    if player is None:  # 第一次用這個 Google 帳號登入 → 自動建立玩家
        # SQL: INSERT INTO players (google_sub, email, username, balance)
        #      VALUES (%s, %s, %s, %s);  
        player = Player(
            google_sub=identity.sub,    # Google 帳號唯一識別碼，之後登入靠它認人
            email=identity.email,       # Google 驗證過的 email
            username=identity.name,     # 顯示名稱（取自 Google 個人資料）
            balance=_NEW_PLAYER_BALANCE,  # 新玩家贈送初始金幣
        )
        db.add(player)
        try:
            db.commit()  # 正式寫入新玩家
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="此 Google 帳號 email 已被使用")
        # SQL: SELECT * FROM players WHERE id = LAST_INSERT_ID();  -- 取回 DB 自動產生的 id 與 created_at
        db.refresh(player)  # 取回 DB 自動產生的 id 與 created_at

    token = create_access_token(player_id=player.id, username=player.username)  # 產生含過期時間的本站 JWT

    return TokenResponse(access_token=token, token_type="bearer")
