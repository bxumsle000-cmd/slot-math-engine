/**
 * api.js — 封裝所有後端 API 呼叫
 *
 * 所有 API 路徑統一前綴 /api/v1，token 自動從 localStorage 取出帶入 Authorization。
 * 401 (token 過期/無效) 時自動清除 token 並導向登入頁。
 */

const API_BASE = "";  // 空字串＝同源：前端由後端同一 port 提供，fetch 自動打同一台，永不撞 port、無 CORS 問題

// ── Token 管理 ────────────────────────────────────────────────────────────────
const TOKEN_KEY = "slot_token";  // localStorage 中存 JWT 的 key

function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}

function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

// ── 共用 fetch 包裝 ────────────────────────────────────────────────────────────
async function request(path, options = {}) {
  const headers = options.headers || {};
  const token = getToken();
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;  // 自動帶 JWT
  }

  const resp = await fetch(API_BASE + path, { ...options, headers });

  // 401: token 過期或無效 → 清掉 token 並通知頁面跳轉
  if (resp.status === 401) {
    clearToken();
    window.dispatchEvent(new CustomEvent("auth:expired"));
    throw new Error("登入已過期，請重新登入");
  }

  const data = await resp.json().catch(() => ({}));

  // 非 2xx：拋出後端的錯誤訊息
  if (!resp.ok) {
    const detail = data.detail || `HTTP ${resp.status}`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }

  return data;
}

// 將物件轉成 application/x-www-form-urlencoded 格式（FastAPI Form 端點要這格式）
function toFormBody(obj) {
  return Object.entries(obj)
    .map(([k, v]) => encodeURIComponent(k) + "=" + encodeURIComponent(v))
    .join("&");
}

// ── 端點封裝 ──────────────────────────────────────────────────────────────────
const API = {
  // 認證
  async loginWithGoogle(idToken) {
    // 把 Google 回傳的 id_token 送給後端驗證；後端驗章後簽發本站 JWT 回來
    const data = await request("/api/v1/auth/google", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: toFormBody({ id_token: idToken }),
    });
    setToken(data.access_token);  // 登入成功立刻存本站 JWT
    return data;
  },

  logout() {
    clearToken();
  },

  isLoggedIn() {
    return !!getToken();
  },

  // 玩家
  async getMe() {
    return request("/api/v1/players/me");
  },

  async deposit(amount) {
    return request("/api/v1/players/me/deposit", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: toFormBody({ amount }),
    });
  },

  async getSpinHistory(page = 1, size = 20, fromDate = null, toDate = null) {
    let url = `/api/v1/players/me/spins?page=${page}&size=${size}`;
    if (fromDate) url += `&from_date=${fromDate}`;     // 起始日期（YYYY-MM-DD，含）
    if (toDate)   url += `&to_date=${toDate}`;          // 結束日期（YYYY-MM-DD，含）
    return request(url);
  },

  // 遊戲
  async getConfig() {
    return request("/api/v1/games/config");
  },

  async spin(betAmount) {
    return request("/api/v1/games/spin", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: toFormBody({ bet_amount: betAmount }),
    });
  },
};
