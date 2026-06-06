/**
 * deposit.js — 儲值頁邏輯
 *
 * 功能：
 *   - 顯示當前餘額
 *   - 提供 4 個快速金額（100 / 500 / 1000 / 5000）
 *   - 自訂金額輸入
 *   - 送出儲值請求並更新餘額
 */

const QUICK_AMOUNTS = [100, 500, 1000, 5000];  // 快速儲值金額選項
let selectedQuickAmount = null;                 // 當前被選中的快速金額（null = 用自訂）

// ── 載入並顯示當前餘額 ──────────────────────────────────────────
function renderDepositBalance() {
  const balance = parseFloat(currentPlayer?.balance || 0);
  $g("deposit-balance-value").textContent = formatBalance(balance);
}

// ── 快速金額按鈕選擇 ────────────────────────────────────────────
function selectQuickAmount(amount) {
  selectedQuickAmount = amount;

  // 更新按鈕視覺：被選的按鈕加 active class
  document.querySelectorAll(".deposit-quick .btn").forEach((btn) => {
    btn.classList.toggle("active", parseInt(btn.dataset.amount) === amount);
  });

  // 自訂金額欄位清空（避免兩邊衝突）
  $g("deposit-custom-amount").value = "";
}

// ── 自訂金額輸入時取消快速選擇 ───────────────────────────────────
function onCustomAmountInput() {
  selectedQuickAmount = null;
  document.querySelectorAll(".deposit-quick .btn").forEach((btn) =>
    btn.classList.remove("active")
  );
}

// ── 送出儲值 ────────────────────────────────────────────────────
async function handleDeposit() {
  // 決定實際儲值金額：快速選擇優先，否則用自訂欄位
  let amount = selectedQuickAmount;
  if (amount === null) {
    amount = parseFloat($g("deposit-custom-amount").value);
  }

  if (!amount || amount <= 0) {
    showDepositMsg("請選擇或輸入有效的儲值金額", true);
    return;
  }

  const btn = $g("btn-deposit");
  btn.disabled = true;
  btn.textContent = "儲值中...";
  showDepositMsg("");

  try {
    const updated = await API.deposit(amount);
    currentPlayer = updated;       // 後端回傳完整的 Player，直接覆蓋本地物件
    renderDepositBalance();
    updateHeader();                // 同步 header 餘額顯示
    showDepositMsg(`✅ 儲值成功！加入 ${formatBalance(amount)} 金幣`, false);

    // 清空輸入並重置快速選擇
    $g("deposit-custom-amount").value = "";
    selectedQuickAmount = null;
    document.querySelectorAll(".deposit-quick .btn").forEach((b) =>
      b.classList.remove("active")
    );
  } catch (err) {
    showDepositMsg("儲值失敗：" + err.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = "確 認 儲 值";
  }
}

// ── 訊息顯示 ────────────────────────────────────────────────────
function showDepositMsg(text, isError = true) {
  const el = $g("deposit-msg");
  el.innerHTML = text
    ? `<div class="${isError ? "msg-error" : "msg-success"}">${text}</div>`
    : "";
}

// ── 頁面初始化（每次切到儲值頁時呼叫） ──────────────────────────
function initDepositPage() {
  renderDepositBalance();
  showDepositMsg("");
  $g("deposit-custom-amount").value = "";
  selectedQuickAmount = null;
  document.querySelectorAll(".deposit-quick .btn").forEach((b) =>
    b.classList.remove("active")
  );
}

// ── 綁定事件 ────────────────────────────────────────────────────
function bindDepositEvents() {
  document.querySelectorAll(".deposit-quick .btn").forEach((btn) => {
    btn.addEventListener("click", () => selectQuickAmount(parseInt(btn.dataset.amount)));
  });
  $g("deposit-custom-amount").addEventListener("input", onCustomAmountInput);
  $g("btn-deposit").addEventListener("click", handleDeposit);

  // Enter 鍵也能送出
  $g("deposit-custom-amount").addEventListener("keydown", (e) => {
    if (e.key === "Enter") handleDeposit();
  });
}
