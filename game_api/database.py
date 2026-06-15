"""
database.py - MySQL 連線設定

使用 SQLAlchemy 建立資料庫引擎與 Session 工廠。
提供 get_db() 依賴注入函式，讓每個 API 請求取得獨立連線，用完自動關閉。
"""

import os

import pymysql
from dotenv import load_dotenv

load_dotenv()  # 讀取專案根目錄的 .env，設定後可被 os.getenv 取用
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DB_HOST     = os.getenv("DB_HOST",     "172.22.240.1")  # Windows host IP（MySQL 裝在 Windows，從 WSL2 連過去）
DB_PORT     = int(os.getenv("DB_PORT") or "3306")        # MySQL 埠號；空字串或未設都退回 3306（避免 int("") 崩潰）
DB_USER     = os.getenv("DB_USER",     "root")           # MySQL 帳號
DB_PASSWORD = os.getenv("DB_PASSWORD", "")               # MySQL 密碼，必須透過環境變數設定
DB_NAME     = os.getenv("DB_NAME",     "slot_game")      # 目標資料庫名稱

# 連線字串決定順序：
# 1. 雲端平台（如 Railway）注入單一的 DATABASE_URL → 直接採用，只需設一個變數，最不易出錯。
# 2. 本機開發沒有 DATABASE_URL → 用上面的 DB_* 參數自行拼出連線字串。
_RAW_DATABASE_URL = os.getenv("DATABASE_URL")  # 雲端提供的完整連線字串；本機沒設時為 None
if _RAW_DATABASE_URL:
    # Railway 的 MYSQL_URL 開頭是 mysql://，但 SQLAlchemy 需指定 driver，
    # 故把 scheme 補成 mysql+pymysql:// 。
    DATABASE_URL = _RAW_DATABASE_URL.replace("mysql://", "mysql+pymysql://", 1)  # 只換開頭第一個
else:
    # MySQL 連線字串：格式為 mysql+pymysql://帳號:密碼@主機:埠號/資料庫名稱
    DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"


def _ensure_database_exists() -> None:  # 啟動時確保資料庫存在，不存在就自動建立
    """
    先不帶資料庫名稱連線到 MySQL，執行 CREATE DATABASE IF NOT EXISTS。
    這樣第一次啟動不需要手動建資料庫。
    """
    conn = pymysql.connect(  # 不指定 db，只連到 MySQL server
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
    )
    try:
        with conn.cursor() as cursor:  # with 區塊結束時自動關閉 cursor，免手動 cursor.close()（即使中途拋例外也保證關）
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` CHARACTER SET utf8mb4"
            )  # IF NOT EXISTS：資料庫已存在時跳過，不會報錯
    finally:
        conn.close()  # 這條連線只用來建資料庫，用完立刻關掉


# 雲端平台（如 Railway）的 MySQL 資料庫已預先建好，且帳號通常沒有 CREATE DATABASE 權限。
# 偵測到 RAILWAY_ENVIRONMENT 變數時就跳過自動建庫，避免啟動時權限錯誤導致崩潰。
# 本機開發沒有這個變數，行為照舊（自動建庫）。
if os.getenv("RAILWAY_ENVIRONMENT") is None:  # None = 不在 Railway 雲端，視為本機環境
    _ensure_database_exists()  # 模組載入時立刻執行（main.py import database 時觸發）

# pool_pre_ping=True：每次取用連線前先確認存活
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# Session 工廠：每次呼叫 SessionLocal() 產生一個新的資料庫 Session

# autocommit=False：手動提交交易
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)  

class Base(DeclarativeBase):  # 所有 ORM 模型的基底類別，models.py 的 class 都繼承這個
    pass


def get_db():  # FastAPI 依賴注入：每個請求取得一個 DB Session，結束後自動關閉
    """
    FastAPI 依賴注入函式，提供資料庫 Session。

    使用 yield 讓 FastAPI 在請求結束後自動執行 finally 區塊，
    確保連線一定會被釋放，不會造成連線池耗盡。

    Yields:
        Session：SQLAlchemy 資料庫連線物件
    """
    db: Session = SessionLocal()  # 從連線池取得一條連線
    try:
        yield db  # 把 Session 交給路由函式使用
    finally:
        db.close()  # 請求結束（成功或例外）後釋放連線回連線池
