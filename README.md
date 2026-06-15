# 🎰 老虎機數學引擎（Slot Math Engine）

> 一個從**數學理論**到**可玩前端**的完整 5×3 多線老虎機專案：
> 理論 RTP 精確計算 → 蒙地卡羅模擬驗證 → FastAPI + MySQL 全端 → 原生前端遊戲。

### 🔗 線上 Demo（已部署於 Railway）

**https://web-production-26e50.up.railway.app/**

用 Google 帳號登入即可遊玩，首次登入自動建立帳號並贈送 1000 金幣。

<!-- ─────────────────────────────────────────────────────────────
     ⬇⬇⬇ 請在這裡放 1~2 張 GIF / 截圖（最重要，先抓住看的人）⬇⬇⬇
     建議：
       1. frontend 遊玩動圖（按 SPIN、中獎發光、Big Win 演出）
       2. Streamlit dashboard 拉滑桿、RTP 即時變化的截圖
     錄好後用：![遊戲畫面](docs/demo.gif)
─────────────────────────────────────────────────────────────── -->
<!-- ![遊戲畫面](docs/demo.gif) -->
<!-- ![分析儀表板](docs/dashboard.png) -->

---

## 這個專案展示了什麼

| 能力 | 具體內容 |
|------|----------|
| **Python** | 全程型別標註、PEP 8、dataclass、generator、NumPy 向量化計算 |
| **資料庫** | MySQL + SQLAlchemy ORM、交易管理、分頁查詢、稽核日誌、`Decimal` 金額精度 |
| **軟體工程** | 五層解耦架構、單一資料來源（改一處全自動連動）、46 個自動化測試 |
| **全端開發** | FastAPI（Google 登入 + JWT 認證）+ 原生 HTML/CSS/JS 前端，前後端同 port、無 CORS |
| **數學建模** | 理論 RTP 精確解（外積向量化）、馬可夫鏈 Free Spin 模型、蒙地卡羅驗證 |

---

## 技術重點

### 1. 理論 RTP 用「精確計算」而非估算
把全部 7⁵ = 16,807 種符號組合逐一精算。配合 NumPy 向量化運算,得到精確的理論值。

```
基礎理論 RTP    87.85%
```

### 2. Free Spin 用馬可夫鏈解析求解
用**馬可夫鏈**把 Free Spin 對整體 RTP 的影響用公式算出來，不靠模擬。觸發機率是**自動從捲軸的 Scatter 分佈推導**。

```
觸發機率        0.38%（由捲軸自動推導）
整體 RTP        97.97%   （Free Spin 貢獻 +10.11%）
```

### 3. 蒙地卡羅模擬獨立驗證理論值
另寫一套隨機模擬引擎，跑百萬局後與理論值對比， 用兩條完全獨立的路徑互相驗證數學正確性。

---

## 架構

```
┌─────────────────────────────────────────────┐
│            core/（數學核心，純計算）          │
│   config → reel → calculator → markov        │
└───────────────────┬─────────────────────────┘
                    │ 被三層共用（單一資料來源）
       ┌────────────┼─────────────┐
       ↓            ↓             ↓
   simulator/    game_api/    dashboard/
   （模擬驗證）  （遊戲後端）  （分析儀表板）
                    ↑
            frontend/ 透過 HTTP API 呼叫
```

> 改 `core/reel.py` 的一個數字（符號格數、付線、賠付），模擬器、API、前端、儀表板**全部自動跟著更新**。

完整架構、執行流程圖與數值調整指南見 **[PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md)**。

---

## 技術棧

- **後端**：FastAPI · SQLAlchemy · PyMySQL · python-jose（JWT）· google-auth（Google 登入驗證）
- **數學/模擬**：NumPy
- **儀表板**：Streamlit · Plotly · pandas
- **前端**：原生 HTML / CSS / JavaScript（無框架）
- **測試**：pytest · httpx

---

## 快速開始

```bash
# 1. 建立虛擬環境並安裝套件
python -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. 設定環境變數（複製 .env 範例後填入）
#    DB_HOST / DB_PORT / DB_USER / DB_PASSWORD / DB_NAME  ← MySQL 連線
#    JWT_SECRET                                           ← 本站 JWT 簽章金鑰
#    GOOGLE_CLIENT_ID                                     ← Google OAuth Client ID（登入用）
#    並將同一組 Client ID 填進 frontend/js/main.js 的 GOOGLE_CLIENT_ID

# 2-1. 到 Google Cloud Console 申請 OAuth 2.0 Client ID（網頁應用程式），
#      在 Authorized JavaScript origins 加入 http://localhost:8000 與 http://127.0.0.1:8000

# 3. 啟動後端（自動建資料庫與資料表）
PYTHONPATH=. .venv/bin/uvicorn game_api.main:app --reload
#    瀏覽器開 http://localhost:8000，用 Google 帳號登入即可遊玩（前後端同 port）
#    首次登入會自動建立帳號並贈送 1000 金幣

# 4. 啟動分析儀表板
PYTHONPATH=. .venv/bin/streamlit run dashboard/app.py
```

### 部署（Railway）

專案內含 `Procfile`，可直接部署到 Railway：

```
web: uvicorn game_api.main:app --host 0.0.0.0 --port $PORT
```

線上版本：**https://web-production-26e50.up.railway.app/**
（環境變數 DB_* / JWT_SECRET / GOOGLE_CLIENT_ID 在 Railway 後台設定；Google OAuth 的 Authorized JavaScript origins 需加入該網域）

### 直接看數學引擎（不需資料庫）

```bash
# 理論 RTP 精確計算報告
PYTHONPATH=. .venv/bin/python core/calculator.py

# 含 Free Spin 的整體 RTP（馬可夫鏈）
PYTHONPATH=. .venv/bin/python core/markov_freespin_rtp.py

# 百萬局蒙地卡羅模擬（與理論值對比）
PYTHONPATH=. .venv/bin/python simulator/engine.py
```

---

## 測試

```bash
PYTHONPATH=. .venv/bin/pytest tests/ -v
```

- `tests/test_core.py`（36 項）：賠付規則、Wild 替換、RTP 計算、馬可夫鏈穩態
- `tests/test_api_spin.py`（10 項）：`/spin` 端點、Free Spin 狀態流轉、**防作弊鎖押注**、餘額不足處理（SQLite in-memory，不依賴真實資料庫）

---

## 專案結構

```
core/        數學核心層（理論計算，純函式無副作用）
simulator/   蒙地卡羅模擬層（隨機驗證理論值）
game_api/    FastAPI 後端（MySQL + Google 登入 + JWT + 稽核日誌）
frontend/    原生前端遊戲介面
dashboard/   Streamlit 互動分析儀表板
tests/       自動化測試
```
---

## 其他設計摘要

- **安全性**：Google 登入（OpenID Connect，後端驗證 id_token 的簽章 / aud / exp / email_verified）、登入與驗票解耦（Google 只負責認人，後續一律用本站 JWT）、JWT 認證（24 小時有效期）、Free Spin 期間鎖定押注金額（防止 FS 中改注作弊）、敏感資訊(DB 密碼、JWT 金鑰、Google Client ID)集中於 .env,不進版控

- **RESTful API 設計**：路徑統一 `/api/v1` 版本前綴、語意化狀態碼（200 成功 / 400 餘額不足 / 401 未授權 / 422 欄位驗證失敗）、Pydantic 自動驗證輸入、回應格式統一 JSON

- **可維護性 / 架構**：五層解耦（`core` 為純函式、無副作用、不依賴上層）、遊戲參數集中於 `core/config.py` 與 `core/reel.py` 、`spin()` 同時供 API 與分析層共用、前端賠付表與付線由 `/config` 動態取得

```
