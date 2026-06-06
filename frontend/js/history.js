/**
 * history.js — 旋轉歷史頁邏輯
 *
 * 功能：
 *   - 載入並顯示玩家旋轉記錄（分頁、依時間倒序）
 *   - 日期範圍篩選（from / to）
 *   - 上一頁 / 下一頁切換
 */

// ── 全域狀態 ──────────────────────────────────────────────────────
const historyState = {
  page: 1,             // 當前頁碼（從 1 開始）
  size: 20,            // 每頁筆數
  fromDate: null,      // 起始日期 (YYYY-MM-DD) 或 null
  toDate: null,        // 結束日期 (YYYY-MM-DD) 或 null
  totalPages: 1,       // 總頁數（從 API 取得後計算）
};

// ── 工具：將 ISO 時間字串轉成易讀格式 ──────────────────────────
function formatDateTime(iso) {
  const d = new Date(iso);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// ── 工具：依損益正負取得 CSS class 與符號 ──────────────────────
function netPlClass(netPl) {
  const n = parseFloat(netPl);
  if (n > 0) return "net-positive";
  if (n < 0) return "net-negative";
  return "net-zero";
}

function netPlText(netPl) {
  const n = parseFloat(netPl);
  if (n > 0) return `+${formatBalance(n)}`;          // 正數加 +
  if (n < 0) return `−${formatBalance(Math.abs(n))}`; // 負數用真減號
  return "0";
}

// ── 載入並渲染本頁資料 ──────────────────────────────────────────
async function loadHistoryPage() {
  const tbody = document.querySelector("#history-tbody");
  const emptyEl = $g("history-empty");
  const tableEl = $g("history-table");
  const paginationEl = $g("history-pagination");

  // 顯示載入中
  tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:40px;">載入中...</td></tr>`;

  try {
    // 呼叫 API（依目前篩選條件與頁碼）
    const data = await API.getSpinHistory(
      historyState.page,
      historyState.size,
      historyState.fromDate,
      historyState.toDate,
    );

    historyState.totalPages = Math.max(1, Math.ceil(data.total / data.size));  // 至少 1 頁避免顯示 0

    if (data.items.length === 0) {
      tableEl.classList.add("hidden");
      emptyEl.classList.remove("hidden");
      paginationEl.classList.add("hidden");
      return;
    }

    tableEl.classList.remove("hidden");
    emptyEl.classList.add("hidden");
    paginationEl.classList.remove("hidden");

    // 渲染每筆記錄
    tbody.innerHTML = data.items.map((item) => {
      const netCls = netPlClass(item.net_pl);
      const resultCls = item.total_multiplier > 0 ? "result-win" : "";
      // FS 免費局：押注欄加「免費」徽章，提示此筆押注並未實際扣款（損益已是純賠付）
      const fsBadge = item.is_free_spin
        ? ` <span class="fs-tag">免費</span>`
        : "";
      return `
        <tr>
          <td>${formatDateTime(item.created_at)}</td>
          <td>${formatBalance(item.bet_amount)}${fsBadge}</td>
          <td class="result-cell ${resultCls}" title="${item.result}">${item.result}</td>
          <td class="${netCls}">${netPlText(item.net_pl)}</td>
          <td>${formatBalance(item.balance_after)}</td>
          <td style="color:var(--text-dim);font-size:12px;">#${item.spin_id}</td>
        </tr>
      `;
    }).join("");

    // 更新分頁資訊與按鈕狀態
    $g("page-info").textContent = `${historyState.page} / ${historyState.totalPages}`;
    $g("btn-page-prev").disabled = historyState.page <= 1;
    $g("btn-page-next").disabled = historyState.page >= historyState.totalPages;
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--danger);padding:40px;">載入失敗：${err.message}</td></tr>`;
  }
}

// ── 篩選操作 ────────────────────────────────────────────────────
function applyHistoryFilter() {
  historyState.fromDate = $g("filter-from-date").value || null;
  historyState.toDate = $g("filter-to-date").value || null;
  historyState.page = 1;  // 篩選變動時回第一頁
  loadHistoryPage();
}

function clearHistoryFilter() {
  $g("filter-from-date").value = "";
  $g("filter-to-date").value = "";
  historyState.fromDate = null;
  historyState.toDate = null;
  historyState.page = 1;
  loadHistoryPage();
}

// ── 翻頁 ────────────────────────────────────────────────────────
function gotoPage(delta) {
  const newPage = historyState.page + delta;
  if (newPage < 1 || newPage > historyState.totalPages) return;
  historyState.page = newPage;
  loadHistoryPage();
}

// ── 頁面初始化（切到歷史頁時呼叫） ───────────────────────────────
function initHistoryPage() {
  historyState.page = 1;  // 每次進入歷史頁重置到第一頁
  loadHistoryPage();
}

// ── 綁定事件 ────────────────────────────────────────────────────
function bindHistoryEvents() {
  $g("btn-filter-apply").addEventListener("click", applyHistoryFilter);
  $g("btn-filter-clear").addEventListener("click", clearHistoryFilter);
  $g("btn-page-prev").addEventListener("click", () => gotoPage(-1));
  $g("btn-page-next").addEventListener("click", () => gotoPage(+1));
}
