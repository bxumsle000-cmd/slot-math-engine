"""
dependencies.py - FastAPI 依賴注入：JWT 驗證

提供 get_current_player 依賴，供需要登入才能使用的端點注入。
JWT 設定常數集中在此，不散落各路由。
"""

import os
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from game_api.database import get_db
from game_api.models import Player

_SECRET_KEY = os.getenv("JWT_SECRET", "dev-secret-change-in-production")  # 簽章金鑰，正式環境請透過環境變數設定
_ALGORITHM = "HS256"          # HMAC-SHA256，對稱式簽章，適合單一服務
_EXPIRE_MINUTES = 60 * 24     # Token 有效期：24 小時

_bearer = HTTPBearer()  # 從 Authorization: Bearer <token> header 取出 token


def create_access_token(player_id: int, username: str) -> str: # 產生帶過期時間的 JWT
    """
    產生 JWT access token。

    Args:
        player_id: 玩家 DB id，存入 payload 的 sub 欄位
        username:  玩家帳號，存入 payload 方便 debug

    Returns:
        簽章後的 JWT 字串
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=_EXPIRE_MINUTES)  # 過期時間 = 現在 + 24hr
    payload = {
        "sub": str(player_id),  # subject：token 代表的玩家 id（JWT 慣例用 str）
        "username": username,   # 額外資訊，方便 log 追蹤
        "exp": expire,          # expiration：jose 自動驗證此欄位
    }
    return jwt.encode(payload, _SECRET_KEY, algorithm=_ALGORITHM)


def get_current_player(  # 驗證 Bearer token，回傳對應的 Player ORM 物件
    auth: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Player:
    """
    FastAPI 依賴：從 Authorization header 取出 JWT，驗證後回傳對應玩家。

    Args:
        auth: FastAPI 自動從 Authorization: Bearer <token> 解析
        db:   資料庫 Session（依賴注入）

    Returns:
        驗證通過的 Player ORM 物件

    Raises:
        HTTPException 401: token 無效、過期或玩家不存在
    """
    _invalid = HTTPException(status_code=401, detail="Token 無效或已過期")  # 統一錯誤，不透露細節

    try:
        payload = jwt.decode(auth.credentials, _SECRET_KEY, algorithms=[_ALGORITHM])
        player_id = int(payload["sub"])  # sub 存為 str，還原成 int 查 DB
    except (JWTError, KeyError, ValueError):
        raise _invalid

    # SQL: SELECT * FROM players WHERE id = %s;  -- 主鍵查詢（db.get 走主鍵，命中 identity map 可能不發 SQL）
    player = db.get(Player, player_id)  # 主鍵查詢，確認玩家仍存在於 DB
    if player is None:
        raise _invalid

    return player
