"""
routers/auth.py - 登入端點

提供 token 取得功能：
    POST /auth/login — 驗證帳號密碼，回傳 JWT access token
"""

from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy.orm import Session

from game_api.password import verify_password
from game_api.database import get_db
from game_api.dependencies import create_access_token
from game_api.models import Player
from game_api.schemas import TokenResponse

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])  # 所有端點自動加上 /api/v1/auth 前綴


@router.post("/login", response_model=TokenResponse)  # 登入成功回 200
def login(  # 驗證帳密，回傳 JWT token
    username: str = Form(..., description="玩家帳號"),
    password: str = Form(..., description="登入密碼"),
    db: Session = Depends(get_db),
) -> TokenResponse:
    """
    驗證帳號密碼，回傳 JWT access token。

    Args:
        username: 玩家帳號（Form 欄位）
        password: 登入密碼（Form 欄位）
        db:       資料庫 Session（依賴注入）

    Returns:
        TokenResponse，含 access_token 與 token_type

    Raises:
        HTTPException 401: 帳號或密碼錯誤（不區分兩者，防枚舉攻擊）
    """
    player = db.query(Player).filter(Player.username == username).first()  # 以帳號名稱查玩家

    # 帳號不存在與密碼錯誤回傳相同訊息，防止攻擊者透過錯誤訊息判斷帳號是否存在
    if player is None or not verify_password(password, player.password_hash):
        raise HTTPException(status_code=401, detail="帳號或密碼錯誤")

    token = create_access_token(player_id=player.id, username=player.username)  # 產生含過期時間的 JWT

    return TokenResponse(access_token=token, token_type="bearer")
