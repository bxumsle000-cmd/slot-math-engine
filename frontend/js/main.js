/**
 * main.js — 進入點、路由與登入/註冊邏輯
 *
 * 採 SPA 風格：所有頁面都在同一個 HTML，透過 show/hide section 切換。
 * 路由由 URL hash 控制（#login / #game / #history / #deposit）。
 */

// ── 當前玩家資料（登入後填入） ────────────────────────────────────
let currentPlayer = null;

// ── DOM 取得（縮寫） ──────────────────────────────────────────────
const $ = (id) => document.getElementById(id);
const showMsg = (containerId, text, isError = true) => {
  const el = $(containerId);
  if (!el) return;
  el.innerHTML = text
    ? `<div class="${isError ? 'msg-error' : 'msg-success'}">${text}</div>`
    : "";
};

// ── 頁面切換 ─────────────────────────────────────────────────────
const PAGES = ["login", "register", "game", "history", "deposit"];
let currentPageName = null;  // 目前顯示中的頁面名稱（供 hashchange 判斷是否需要切換、避免重複 init）

// 依 URL hash 與登入狀態，解析出「實際應該顯示」的頁面
// 未登入：只允許 login／register，其餘一律導回 login
// 已登入：只允許 game／history／deposit，其餘一律導回 game
function resolvePageFromHash() {  // 解析 hash → 合法頁面名稱
  const target = window.location.hash.slice(1);
  if (!currentPlayer) {
    return target === "register" ? "register" : "login";
  }
  return PAGES.includes(target) && target !== "login" && target !== "register" ? target : "game";
}

function showPage(name) {
  currentPageName = name;  // 記錄目前頁面，hashchange 用來判斷是否真的要切換
  PAGES.forEach((p) => {
    const el = $(`page-${p}`);
    if (el) el.classList.toggle("hidden", p !== name);
  });

  // 同步 nav 高亮
  document.querySelectorAll(".nav-btn[data-page]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.page === name);
  });

  // 同步 URL hash（方便重整保留頁面）
  if (window.location.hash !== `#${name}`) {
    window.location.hash = name;
  }

  // 切到對應頁面時做初始化（必須已登入）
  if (currentPlayer) {
    if (name === "game") initGamePage();
    else if (name === "history") initHistoryPage();
    else if (name === "deposit") initDepositPage();
  }
}

// ── Header 顯示控制 ──────────────────────────────────────────────
function updateHeader() {
  const header = $("app-header");
  if (currentPlayer) {
    header.classList.remove("hidden");
    $("header-username").textContent = currentPlayer.username;
    $("header-balance").textContent = `💰 ${formatBalance(currentPlayer.balance)}`;
  } else {
    header.classList.add("hidden");
  }
}

function formatBalance(b) {
  return Number(b).toLocaleString("en-US", { maximumFractionDigits: 2 });  // 千分位
}

// ── 登入流程 ─────────────────────────────────────────────────────
async function handleLogin() {
  const username = $("login-username").value.trim();
  const password = $("login-password").value;

  if (!username || !password) {
    showMsg("login-msg", "請輸入帳號和密碼");
    return;
  }

  const btn = $("btn-login");
  btn.disabled = true;
  btn.textContent = "登入中...";

  try {
    await API.login(username, password);
    currentPlayer = await API.getMe();
    showMsg("login-msg", "");
    updateHeader();
    showPage("game");
  } catch (err) {
    showMsg("login-msg", err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "登 入";
  }
}

// ── 註冊流程 ─────────────────────────────────────────────────────
async function handleRegister() {
  const username = $("register-username").value.trim();
  const password = $("register-password").value;

  if (!username) {
    showMsg("register-msg", "請輸入帳號");
    return;
  }
  if (password.length < 6) {
    showMsg("register-msg", "密碼至少 6 字元");
    return;
  }

  const btn = $("btn-register");
  btn.disabled = true;
  btn.textContent = "註冊中...";

  try {
    await API.register(username, password, 1000);  // 新用戶贈送 1000 金幣
    showMsg("register-msg", "註冊成功，正在自動登入...", false);
    await API.login(username, password);
    currentPlayer = await API.getMe();
    updateHeader();
    showPage("game");
  } catch (err) {
    showMsg("register-msg", err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "註 冊";
  }
}

// ── 登出 ─────────────────────────────────────────────────────────
function handleLogout() {
  API.logout();
  currentPlayer = null;
  updateHeader();
  showPage("login");
}

// ── 已登入狀態的啟動流程（自動帶入玩家資料） ──────────────────────
async function bootIfLoggedIn() {
  if (!API.isLoggedIn()) {
    showPage("login");
    return;
  }
  try {
    currentPlayer = await API.getMe();
    updateHeader();
    // 依 URL hash 決定要顯示哪個內頁，預設 game
    showPage(resolvePageFromHash());
  } catch {
    // token 失效，回登入頁
    API.logout();
    showPage("login");
  }
}

// ── 綁定事件 ─────────────────────────────────────────────────────
function bindEvents() {
  $("btn-login").addEventListener("click", handleLogin);
  $("btn-register").addEventListener("click", handleRegister);
  $("btn-logout").addEventListener("click", handleLogout);

  $("link-to-register").addEventListener("click", () => showPage("register"));
  $("link-to-login").addEventListener("click", () => showPage("login"));

  // Enter 鍵送出表單
  ["login-username", "login-password"].forEach((id) =>
    $(id).addEventListener("keydown", (e) => e.key === "Enter" && handleLogin())
  );
  ["register-username", "register-password"].forEach((id) =>
    $(id).addEventListener("keydown", (e) => e.key === "Enter" && handleRegister())
  );

  // Header 導覽
  document.querySelectorAll(".nav-btn[data-page]").forEach((btn) => {
    btn.addEventListener("click", () => showPage(btn.dataset.page));
  });

  // 監聽 token 過期事件（從 api.js 派發）
  window.addEventListener("auth:expired", handleLogout);

  // 監聽瀏覽器上一頁／下一頁（hash 變動）：依 hash 解析目標頁並切換
  // 只有目標頁與目前頁不同時才呼叫 showPage，避免 showPage 自己寫 hash 造成的重複 init
  window.addEventListener("hashchange", () => {
    const target = resolvePageFromHash();
    if (target !== currentPageName) showPage(target);
  });

  // 靜音切換按鈕
  $("btn-mute").addEventListener("click", () => {
    Sound.init();
    const muted = Sound.toggleMute();
    $("btn-mute").textContent = muted ? "🔇" : "🔊";
  });

  // 同步靜音圖示（讀取 localStorage）
  if (localStorage.getItem("slot_muted") === "true") {
    $("btn-mute").textContent = "🔇";
  }

  // 全域按鈕點擊音（除了 SPIN 按鈕，它自己有 spinStart 音效）
  document.addEventListener("click", (e) => {
    const btn = e.target.closest("button");
    if (!btn || btn.id === "btn-spin" || btn.classList.contains("modal-close")) return;
    if (btn.disabled) return;
    Sound.init();
    Sound.click();
  }, true);
}

// ── 啟動 ─────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  bindEvents();
  bindGameEvents();     // 綁定遊戲頁的按鈕（SPIN、押注 +/-、賠付表）
  bindHistoryEvents();  // 綁定歷史頁的按鈕（篩選、翻頁）
  bindDepositEvents();  // 綁定儲值頁的按鈕（快速金額、確認）
  bootIfLoggedIn();
});
