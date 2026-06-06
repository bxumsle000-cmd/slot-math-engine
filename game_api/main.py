"""
main.py - FastAPI 應用程式進入點

啟動時自動建立資料表，掛載所有路由。
所有業務端點統一前綴 /api/v1，方便前後端對接與後續版本升級。

啟動指令：PYTHONPATH=. .venv/bin/uvicorn game_api.main:app --reload
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from game_api.database import Base, engine
from game_api.routers import auth, games, players

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"  # 專案根目錄下的 frontend/

# 啟動時自動建立所有在 models.py 定義的資料表（若已存在則跳過）
Base.metadata.create_all(bind=engine)  # CREATE TABLE IF NOT EXISTS

app = FastAPI(
    title="老虎機遊戲 API",
    description="玩家管理、下注結算、稽核日誌（多線 5×3 格式）",
    version="0.3.0",  # 語意化版本 MAJOR.MINOR.PATCH：主版本(不相容改動).次版本(新增功能).修訂號(修 bug)；開頭 0 代表開發期、API 尚未保證穩定
)


@app.get("/health", tags=["system"])  # 健康檢查端點，給部署/監控/前端啟動檢查用
def health() -> dict[str, str]:
    """
    健康檢查端點。前端啟動時可呼叫確認 API 可達。

    Returns:
        {"status": "ok"} 表示服務正常運行
    """
    return {"status": "ok"}


# 全部業務端點掛在 /api/v1 之下，路徑前綴統一
app.include_router(auth.router)     # /api/v1/auth/*
app.include_router(players.router)  # /api/v1/players/*
app.include_router(games.router)    # /api/v1/games/*

# ── 前端靜態資源（API 路由註冊完才掛，確保 /api/* 優先匹配）────────────────────
# 訪問 http://localhost:8000 即可開啟前端，與 API 同 port，無 CORS 問題。
@app.get("/", include_in_schema=False)  # 根路徑回傳 index.html
def serve_index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")

app.mount("/css", StaticFiles(directory=FRONTEND_DIR / "css"), name="css")
app.mount("/js",  StaticFiles(directory=FRONTEND_DIR / "js"),  name="js")
