"""
models.py - ORM 資料表定義

使用 SQLAlchemy ORM 定義資料庫資料表結構。
包含：Player（玩家帳號與錢包）、SpinHistory（每局旋轉記錄）
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from game_api.database import Base


class Player(Base):  # 玩家資料表，對應 DB 的 players 資料表
    """
    玩家帳號資料表。

    每一列代表一個玩家，記錄帳號資訊與當前餘額。
    餘額使用 DECIMAL(12, 2) 避免浮點數精度問題（例如 100.00 不會變成 99.99999）。

    Args:
        id:                   玩家唯一識別碼，自動遞增
        username:             帳號名稱，不可重複
        password_hash:        bcrypt 雜湊後的密碼，不存明文
        balance:              錢包餘額，單位：元，精確到小數點後 2 位
        free_spins_remaining: 剩餘 Free Spin 局數（0 = 一般模式）
        fs_locked_bet:        FS 期間鎖定的押注金額（0 = 非 FS 狀態，防止 FS 中改押注作弊）
        created_at:           帳號建立時間，由資料庫自動填入
    """

    __tablename__ = "players"  # 對應 MySQL 中的資料表名稱

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)                       # 玩家唯一識別碼，自動遞增
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)              # 帳號名稱，不可重複
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)                    # bcrypt 雜湊後的密碼，不存明文
    balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)          # 錢包餘額，單位：元，精確到小數點後 2 位
    free_spins_remaining: Mapped[int] = mapped_column(Integer, nullable=False, default=0)        # 剩餘 Free Spin 局數（0 = 一般模式）
    fs_locked_bet: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)   # FS 期間鎖定的押注金額（0 = 非 FS 狀態，防止 FS 中改押注作弊）
    created_at: Mapped[datetime] = mapped_column(                                              # 帳號建立時間，由資料庫自動填入
        DateTime, server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # 物件的字串表示，方便 debug 時查看
        return f"Player(id={self.id}, username={self.username!r}, balance={self.balance})"


class SpinHistory(Base):  # 旋轉記錄資料表，對應 DB 的 spin_histories 資料表
    """
    每局旋轉的稽核記錄（多線 5×3 格式）。

    每次呼叫 POST /api/v1/games/spin 成功後寫入一列。
    stops 欄位以 "|" 分隔五個捲軸的停格位置，例如 "5|12|3|18|0"。
    payline_multipliers 以 "|" 分隔各付線倍率，例如 "0|5|0|0|0"（5 條付線）。

    Args:
        id:                  旋轉記錄唯一識別碼
        player_id:           對應玩家，外鍵指向 players.id
        bet_amount:          本局押注金額（元，押滿 5 線）
        stops:               五捲軸停格位置，格式 "5|12|3|18|0"
        payline_multipliers: 各付線賠付倍率，格式 "0|5|0|..."
        total_multiplier:    所有付線倍率總和（0 = 全未中獎）
        scatter_count:       出現 Scatter 的捲軸數（0–5）
        is_free_spin:        是否為 Free Spin 局（True = 免費，不扣押注）
        payout:              實際賠付金額
        balance_before:      旋轉前玩家餘額（稽核快照）
        balance_after:       旋轉後玩家餘額（稽核快照）
        created_at:          旋轉時間，由資料庫自動填入
    """

    __tablename__ = "spin_histories"  # 對應 MySQL 中的資料表名稱

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)             # 旋轉記錄唯一識別碼
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False)  # 對應玩家，外鍵指向 players.id
    bet_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)         # 本局押注金額（元，押滿 5 線）
    stops: Mapped[str] = mapped_column(String(20), nullable=False)                     # 五捲軸停格位置，格式 "5|12|3|18|0"
    payline_multipliers: Mapped[str] = mapped_column(String(50), nullable=False)       # 各付線賠付倍率，格式 "0|5|0|..."
    total_multiplier: Mapped[int] = mapped_column(Integer, nullable=False)             # 所有付線倍率總和（0 = 全未中獎）
    scatter_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)         # 出現 Scatter 的捲軸數（0–5）
    is_free_spin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)    # 是否為 Free Spin 局（True = 免費，不扣押注）
    payout: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)                 # 實際賠付金額
    balance_before: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)     # 旋轉前玩家餘額（稽核快照）
    balance_after: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)      # 旋轉後玩家餘額（稽核快照）
    created_at: Mapped[datetime] = mapped_column(                                     # 旋轉時間，由資料庫自動填入
        DateTime, server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # 物件的字串表示，方便 debug 時查看
        return (
            f"SpinHistory(id={self.id}, player_id={self.player_id}, "
            f"stops={self.stops!r}, total_multiplier={self.total_multiplier}x, payout={self.payout})"
        )