"""
google_oauth.py - Google 登入（OpenID Connect）id_token 驗證

前端用 Google Identity Services 讓玩家登入後，會拿到一段 id_token（JWT 格式，
由 Google 簽章）。本模組負責把這段 token 交給 google-auth 函式庫驗證：
    1. 驗章：用 Google 的公開憑證確認 token 真的由 Google 簽發、未被竄改
    2. 驗 aud：確認 token 是發給「我們這個 Client ID」的，不是別人的應用
    3. 驗 exp：確認 token 尚未過期（google-auth 自動檢查）

驗證通過後回傳玩家身分資訊（sub / email / name），供 auth 路由建立或登入帳號。
"""

import os

from google.auth.transport import requests as google_requests  # google-auth 抓 Google 憑證用的 HTTP 傳輸層
from google.oauth2 import id_token as google_id_token           # Google id_token 驗證工具

from dataclasses import dataclass

_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")  # 本應用的 Google OAuth Client ID，驗 aud 用，必須透過環境變數設定
_request = google_requests.Request()            # 共用的 HTTP request 物件，google-auth 用它去抓 Google 公開憑證


@dataclass
class GoogleIdentity:  # Google 驗證通過後回傳的玩家身分
    """
    驗證 Google id_token 成功後萃取出的玩家身分資訊。

    Args:
        sub:   Google 帳號唯一識別碼，跨登入永久不變，用來認帳號
        email: Google 帳號 email（已由 Google 驗證擁有權）
        name:  Google 個人資料顯示名稱，無則退回 email 的 @ 前段
    """

    sub: str    # Google 帳號唯一識別碼（id_token 的 sub），認帳號就靠它
    email: str  # Google 帳號 email，已由 Google 驗證擁有權
    name: str   # 顯示名稱，供 UI 顯示用


class GoogleAuthError(Exception):  # Google id_token 驗證失敗時拋出
    """Google id_token 驗證失敗（簽章錯誤、aud 不符、過期、email 未驗證等）。"""


def verify_google_id_token(token: str) -> GoogleIdentity:  # 驗證 Google id_token，回傳玩家身分
    """
    驗證前端送來的 Google id_token，成功則回傳玩家身分資訊。

    Args:
        token: 前端從 Google Identity Services 取得的 id_token（JWT 字串）

    Returns:
        GoogleIdentity，含 sub、email、name 三項已驗證的身分資訊

    Raises:
        GoogleAuthError: 未設定 Client ID、簽章/aud/exp 驗證失敗，或 email 未經 Google 驗證
    """
    if not _CLIENT_ID:  # 沒設 Client ID 就無法驗 aud，直接擋下避免誤放行
        raise GoogleAuthError("伺服器未設定 GOOGLE_CLIENT_ID，無法驗證 Google 登入")

    try:
        # verify_oauth2_token 一次做完：驗簽章、驗 aud（須等於 _CLIENT_ID）、驗 exp
        claims = google_id_token.verify_oauth2_token(token, _request, _CLIENT_ID)
    except ValueError as exc:  # google-auth 對任何驗證失敗都拋 ValueError，轉成本模組的錯誤型別
        raise GoogleAuthError("Google 登入驗證失敗") from exc

    # email_verified：Google 是否已確認此人擁有該 email。只有 True 才採信，避免假冒 email
    if not claims.get("email_verified", False):
        raise GoogleAuthError("此 Google 帳號的 email 尚未經 Google 驗證")

    email = claims.get("email", "")  # Google 帳號 email
    name = claims.get("name") or email.split("@")[0]  # 無顯示名稱時退回 email 的 @ 前段當名字

    return GoogleIdentity(
        sub=claims["sub"],  # Google 帳號唯一識別碼（驗證通過必有此欄）
        email=email,
        name=name[:50],     # 截到 50 字元，對齊 Player.username 欄位長度上限
    )
