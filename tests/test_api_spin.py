"""
tests/test_api_spin.py - /spin 端點整合測試

使用 FastAPI TestClient + unittest.mock.patch 控制 spin 的回傳值，
強制製造各種場景（一般局、付線中獎、FS 觸發、FS 免費局），驗證賠付與狀態正確性。

FS 設計為前端驅動：
    - 一般局觸發 FS → free_spins_remaining = 10，回傳給前端
    - 前端繼續打 /spin → 後端見 free_spins_remaining > 0 → 免費局，賠付 × 3
    - 直到 free_spins_remaining 歸零回一般模式

不依賴真實 DB：SQLite in-memory + StaticPool，測試結束後自動清理。
"""

import pytest
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from game_api.main import app
from game_api.database import Base, get_db
from game_api.models import Player
from game_api.dependencies import get_current_player
from simulator.engine import SpinOutcome


# ── 測試用 DB（SQLite in-memory）────────────────────────────────────────────────
# StaticPool：強制所有連線共用同一個底層連接，避免 in-memory SQLite 各連線資料庫不共享的問題
_TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,  # 同一記憶體 DB 供所有 session 共用
)
_TestSession = sessionmaker(bind=_TEST_ENGINE, expire_on_commit=False)  # commit 後物件不失效，省去 refresh 再查


def _make_db_override(db):  # 建立綁定特定 session 的 get_db 覆蓋函式
    """
    回傳一個 generator 函式，讓 FastAPI 依賴注入時永遠使用同一個 session。

    必須與 fixture 共用 session，否則 player 物件所屬 session 和路由的 db 不同，
    跨 session 寫入會觸發 SQLAlchemy DetachedInstanceError。

    Args:
        db: 已開啟的 SQLAlchemy Session，由 client_with_player fixture 建立

    Returns:
        符合 FastAPI Depends 介面的 generator 函式
    """
    def override():  # 回傳固定 session，不另開新 session
        yield db
    return override


def _make_outcome(  # 建立受控的 SpinOutcome，供 mock 使用
    total_multiplier: int = 0,
    scatter_count: int = 0,
    free_spin_triggered: bool = False,
) -> SpinOutcome:
    """
    建立一個固定內容的 SpinOutcome，讓測試結果可預測。

    Args:
        total_multiplier:    付線合計賠付倍率
        scatter_count:       出現 Scatter 的捲軸數
        free_spin_triggered: 是否觸發 Free Spin

    Returns:
        SpinOutcome，供 patch('game_api.routers.games.spin') 使用
    """
    return SpinOutcome(
        stops=(0, 0, 0, 0, 0),
        grid=[["Blank"] * 5 for _ in range(3)],
        payline_multipliers=[total_multiplier, 0, 0, 0, 0],  # 只有付線 1 中獎，其餘 0
        total_multiplier=total_multiplier,
        scatter_count=scatter_count,
        free_spin_triggered=free_spin_triggered,
    )


@pytest.fixture(autouse=True)
def setup_db():  # 每個測試前建表、測試後刪表，確保案例互相隔離
    """
    每個測試案例前建立 SQLite 資料表，測試後刪除，確保各案例互相隔離。
    """
    Base.metadata.create_all(_TEST_ENGINE)
    yield
    Base.metadata.drop_all(_TEST_ENGINE)


@pytest.fixture()
def client_with_player():  # 建立 TestClient 並注入餘額 1000、free_spins_remaining=0 的測試玩家
    """
    建立 FastAPI TestClient，覆蓋 DB 與身份驗證依賴，注入測試玩家。

    Returns:
        (TestClient, Player) 元組，Player 餘額 1000、free_spins_remaining=0
    """
    db = _TestSession()  # 開啟測試 DB session
    player = Player(username="tester", password_hash="x", balance=1000.0, free_spins_remaining=0)  # 測試玩家，無剩餘 FS
    db.add(player)
    db.commit()
    db.refresh(player)  # 取回 DB 自動填入的 id

    app.dependency_overrides[get_db] = _make_db_override(db)          # 替換正式 DB，共用同一 session
    app.dependency_overrides[get_current_player] = lambda: player    # 跳過 JWT 驗證，直接注入測試玩家

    client = TestClient(app)  # FastAPI 測試客戶端（不需啟動伺服器）
    yield client, player

    app.dependency_overrides.clear()  # 還原所有依賴覆蓋
    db.close()


@pytest.fixture()
def client_with_fs_player():  # 建立 TestClient 並注入剩餘 5 局 FS 的測試玩家
    """
    建立 FastAPI TestClient，注入 free_spins_remaining=5 的玩家，用於測試 FS 免費局。

    Returns:
        (TestClient, Player) 元組，Player 餘額 1000、free_spins_remaining=5
    """
    db = _TestSession()  # 開啟測試 DB session
    player = Player(
        username="fs_tester",
        password_hash="x",
        balance=1000.0,
        free_spins_remaining=5,
        fs_locked_bet=10.0,   # 模擬「先前以 10 元觸發 FS」，此為鎖定的押注金額
    )
    db.add(player)
    db.commit()
    db.refresh(player)  # 取回 id

    app.dependency_overrides[get_db] = _make_db_override(db)
    app.dependency_overrides[get_current_player] = lambda: player

    client = TestClient(app)
    yield client, player

    app.dependency_overrides.clear()
    db.close()


# ── 測試案例 ────────────────────────────────────────────────────────────────────

def test_spin_no_win(client_with_player):  # 驗證未中獎時賠付為 0、餘額扣減正確
    """
    一般局未中獎：total_multiplier=0，payout 應為 0，餘額應減少 bet_amount。
    """
    client, _ = client_with_player
    outcome = _make_outcome(total_multiplier=0)

    with patch("game_api.routers.games.spin", return_value=outcome):
        resp = client.post("/api/v1/games/spin", data={"bet_amount": "10"})

    assert resp.status_code == 200
    body = resp.json()
    assert Decimal(body["payout"]) == Decimal("0")               # 未中獎無賠付
    assert Decimal(body["balance_after"]) == Decimal("990")      # 1000 - 10
    assert body["is_free_spin"] is False                         # 一般局
    assert body["free_spins_remaining"] == 0                     # 無剩餘 FS


def test_spin_payline_win(client_with_player):  # 驗證付線中獎時賠付計算正確
    """
    一般局付線中獎：total_multiplier=5（押注 10 元，5 條線）
    payout = 10 × 5 / 5 = 10 元，淨損益 = 0，餘額不變。
    """
    client, _ = client_with_player
    outcome = _make_outcome(total_multiplier=5)

    with patch("game_api.routers.games.spin", return_value=outcome):
        resp = client.post("/api/v1/games/spin", data={"bet_amount": "10"})

    assert resp.status_code == 200
    body = resp.json()
    assert Decimal(body["payout"]) == Decimal("10")              # 10 × 5 / 5 = 10
    assert Decimal(body["balance_after"]) == Decimal("1000")     # 回本
    assert body["is_free_spin"] is False


def test_spin_triggers_free_spin(client_with_player):  # 驗證 FS 觸發後 free_spins_remaining 與 fs_locked_bet 被設定
    """
    一般局觸發 Free Spin（scatter_count=3）：
    free_spins_remaining 應被設為 DEFAULT_FS_CONFIG.free_spin_count（10），
    fs_locked_bet 應被設為觸發那局的押注金額（防 FS 中改押注作弊）。
    """
    client, player = client_with_player
    outcome = _make_outcome(total_multiplier=0, scatter_count=3, free_spin_triggered=True)

    with patch("game_api.routers.games.spin", return_value=outcome):
        resp = client.post("/api/v1/games/spin", data={"bet_amount": "10"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["awarded_new_fs"] is True                        # 一般局觸發 FS
    assert body["free_spins_remaining"] == 10                    # 觸發後設定 10 局 FS
    assert body["is_free_spin"] is False                         # 觸發那局本身仍是一般局（扣款）
    assert Decimal(body["balance_after"]) == Decimal("990")      # 觸發局照常扣押注
    assert Decimal(body["fs_locked_bet"]) == Decimal("10")       # 觸發時的押注金額被鎖定


def test_free_spin_no_deduction(client_with_fs_player):  # 驗證 FS 局不扣款，賠付乘以 win_multiplier
    """
    Free Spin 局：fs_locked_bet=10，total_multiplier=4，win_multiplier=3.0
    payout = 10 × 4 × 3 / 5 = 24 元，不扣押注，餘額純加 24。
    """
    client, _ = client_with_fs_player
    outcome = _make_outcome(total_multiplier=4)

    with patch("game_api.routers.games.spin", return_value=outcome):
        resp = client.post("/api/v1/games/spin", data={"bet_amount": "10"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["is_free_spin"] is True                          # 應為免費局
    assert Decimal(body["payout"]) == Decimal("24")              # 10 × 4 × 3 / 5 = 24
    assert Decimal(body["balance_after"]) == Decimal("1024")     # 1000 + 24（不扣押注）
    assert body["free_spins_remaining"] == 4                     # 5 - 1 = 4


def test_free_spin_bet_is_locked(client_with_fs_player):  # 防作弊：FS 中改押注不會影響賠付計算
    """
    安全性測試：fs_locked_bet=10，但前端送 bet_amount=500（嘗試作弊獲得更多賠付）。
    後端必須忽略前端值，仍以鎖定的 10 元計算。
    payout 應為 24（10×4×3/5），不是 1200（500×4×3/5）。
    """
    client, _ = client_with_fs_player
    outcome = _make_outcome(total_multiplier=4)

    with patch("game_api.routers.games.spin", return_value=outcome):
        resp = client.post("/api/v1/games/spin", data={"bet_amount": "500"})  # 嘗試提高押注

    assert resp.status_code == 200
    body = resp.json()
    assert Decimal(body["bet_amount"]) == Decimal("10")          # 後端回傳實際使用的押注（鎖定值）
    assert Decimal(body["payout"]) == Decimal("24")              # 仍以 10 元計算，非 500
    assert Decimal(body["fs_locked_bet"]) == Decimal("10")       # 鎖定值維持 10


def test_fs_locked_bet_cleared_when_fs_ends(client_with_fs_player):  # FS 真正結束時 fs_locked_bet 清為 0
    """
    FS 最後一局用完且無 Scatter retrigger，fs_locked_bet 應重置為 0。

    outcome.free_spin_triggered = False 確保不觸發 Scatter retrigger（新機制）。
    """
    client, player = client_with_fs_player

    # outcome 無 scatter，不會 retrigger；跑 5 次（從 fs_remaining=5 一路打到 0）
    outcome = _make_outcome(total_multiplier=0, scatter_count=0, free_spin_triggered=False)
    with patch("game_api.routers.games.spin", return_value=outcome):
        for _ in range(5):
            resp = client.post("/api/v1/games/spin", data={"bet_amount": "10"})

    body = resp.json()
    assert body["free_spins_remaining"] == 0                     # FS 已結束
    assert Decimal(body["fs_locked_bet"]) == Decimal("0")        # 鎖定押注被清空
    assert body["is_free_spin"] is True                          # 這「最後一局」本身仍是 FS 局


def test_spin_insufficient_balance(client_with_player):  # 驗證餘額不足時回傳 400
    """
    餘額不足：押注 2000 元，餘額只有 1000 元，應回 400。
    FS 局不做此檢查，僅一般局檢查。
    """
    client, _ = client_with_player
    resp = client.post("/api/v1/games/spin", data={"bet_amount": "2000"})
    assert resp.status_code == 400
    assert "餘額不足" in resp.json()["detail"]


def test_spin_response_structure(client_with_player):  # 驗證回應 JSON 包含所有必要欄位
    """
    回應結構驗證：每次 /spin 回應都必須包含 is_free_spin 與 free_spins_remaining。
    """
    client, _ = client_with_player
    outcome = _make_outcome(total_multiplier=0)

    with patch("game_api.routers.games.spin", return_value=outcome):
        body = client.post("/api/v1/games/spin", data={"bet_amount": "10"}).json()

    for field in ["spin_id", "stops", "grid", "payline_multipliers", "total_multiplier",
                  "scatter_count", "is_free_spin", "awarded_new_fs",
                  "free_spins_remaining", "fs_locked_bet",
                  "bet_amount", "payout", "balance_before", "balance_after"]:
        assert field in body, f"回應缺少欄位：{field}"  # 逐一確認所有欄位存在


def test_health_endpoint():  # 驗證 /health 健康檢查端點可用
    """
    /health 端點不需登入，回傳 {"status": "ok"}，部署/監控/前端啟動檢查使用。
    """
    client = TestClient(app)  # 不需任何依賴覆蓋，直接打
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_game_config_endpoint():  # 驗證 /api/v1/games/config 回傳完整遊戲設定
    """
    /config 端點回傳賠付表、付線、符號清單與 FS 設定，前端啟動時讀取一次。
    """
    client = TestClient(app)  # 此端點不需登入
    body = client.get("/api/v1/games/config").json()

    # 基本結構
    assert body["reels"] == 5
    assert body["rows"] == 3
    assert "Scatter" in body["symbols"]
    assert body["reel_config"]["Scatter"] == 1                   # 目前設定 Scatter 為 1 格

    # 付線：5 條，每條 5 個位置
    assert len(body["paylines"]) == 5
    assert body["paylines"][0]["name"] == "中排"
    assert body["paylines"][0]["positions"] == [1, 1, 1, 1, 1]

    # 賠付表：包含 Seven 5 連 500x（最高獎）
    has_jackpot = any(
        e["symbol"] == "Seven" and e["count"] == 5 and e["multiplier"] == 500
        for e in body["paytable"]
    )
    assert has_jackpot, "賠付表應包含 Seven×5 = 500x"

    # FS 設定（retrigger 改為 Scatter 觸發，續場機率為捲軸衍生值，故不對外曝露佔位欄位）
    assert body["free_spin"]["min_scatter"] == 3
    assert body["free_spin"]["free_spin_count"] == 10
    assert body["free_spin"]["win_multiplier"] == 3.0
    assert "retrigger_prob" not in body["free_spin"]  # 已移除無意義的佔位欄位
