/**
 * modal.js — 賠付表彈窗（取代 alert）
 *
 * 顯示完整賠付表 + 付線視覺化（5×3 mini grid 顯示每條付線軌跡）。
 * 從 gameConfig 取得資料，所以呼叫前必須確保 gameConfig 已載入。
 */

// ── 開啟賠付表 modal ───────────────────────────────────────────
function openPaytableModal() {
  if (!gameConfig) return;

  // 移除舊 modal
  document.querySelectorAll(".modal-backdrop").forEach((el) => el.remove());

  // 賠付表：依符號分組，每符號一列
  // 顯示玩家實際獲得的倍率 = 原始倍率 ÷ 付線數，讓玩家直觀理解
  const numLines = gameConfig.paylines.length;
  const symbolGroups = {};
  gameConfig.paytable.forEach((e) => {
    if (!symbolGroups[e.symbol]) symbolGroups[e.symbol] = {};
    symbolGroups[e.symbol][e.count] = e.multiplier / numLines;
  });

  const paytableRows = Object.entries(symbolGroups).map(([sym, counts]) => `
    <tr>
      <td class="paytable-symbol">${SYMBOL_HTML[sym] || sym}</td>
      <td>${counts[3] ? counts[3] + "×" : "—"}</td>
      <td>${counts[4] ? counts[4] + "×" : "—"}</td>
      <td>${counts[5] ? counts[5] + "×" : "—"}</td>
    </tr>
  `).join("");

  // 付線視覺化：每條付線一個 3×5 mini grid，標記出走的格子
  const paylineDiagrams = gameConfig.paylines.map((line) => {
    const cells = [];
    for (let row = 0; row < 3; row++) {
      for (let col = 0; col < 5; col++) {
        const isOn = line.positions[col] === row;
        cells.push(`<div class="mini-cell ${isOn ? "on" : ""}"></div>`);
      }
    }
    return `
      <div class="payline-item">
        <div class="payline-name">付線 ${line.index + 1}：${line.name}</div>
        <div class="mini-grid">${cells.join("")}</div>
      </div>
    `;
  }).join("");

  // FS 規則
  const fs = gameConfig.free_spin;

  // 組裝完整 modal
  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  backdrop.innerHTML = `
    <div class="modal-box">
      <div class="modal-header">
        <h2>🎰 賠付表與遊戲規則</h2>
        <button class="modal-close" id="modal-close">×</button>
      </div>

      <div class="modal-body">

        <section class="modal-section">
          <h3>付線賠付倍率（單條付線）</h3>
          <table class="paytable">
            <thead>
              <tr>
                <th>符號</th>
                <th>3 連</th>
                <th>4 連</th>
                <th>5 連</th>
              </tr>
            </thead>
            <tbody>${paytableRows}</tbody>
          </table>
          <p class="modal-note">
            本局賠付 = 押注 × 贏分倍率（已含押 ${numLines} 線計算）
          </p>
        </section>

        <section class="modal-section">
          <h3>${gameConfig.paylines.length} 條付線</h3>
          <div class="payline-grid">${paylineDiagrams}</div>
        </section>

        <section class="modal-section">
          <h3>Free Spin 規則</h3>
          <ul class="modal-list">
            <li>觸發條件：可見方格出現 <strong>${fs.min_scatter} 軸或以上</strong>的 ⭐ Scatter</li>
            <li>免費局數：<strong>${fs.free_spin_count} 局</strong></li>
            <li>續場（Retrigger）：Free Spin 期間再出現 <strong>${fs.min_scatter} 軸或以上</strong>的 ⭐ Scatter，剩餘局數<strong>重置為 ${fs.free_spin_count} 局</strong>（非累加）</li>
            <li>FS 期間賠付：<strong>${fs.win_multiplier}× 倍率</strong></li>
            <li>Wild（彩虹）可替代任何符號（Scatter 除外）以組成最高獎</li>
          </ul>
        </section>

      </div>
    </div>
  `;
  document.body.appendChild(backdrop);

  // 進場動畫
  requestAnimationFrame(() => backdrop.classList.add("visible"));

  // 關閉事件：點 X、點背景、按 ESC
  // 注意：close 一定要先解除 ESC 監聽器，否則不論用哪種方式關閉都會殘留 listener
  const onEsc = (e) => {
    if (e.key === "Escape") close();
  };
  const close = () => {
    document.removeEventListener("keydown", onEsc);  // 無論從 X／背景／ESC 關閉都解除，避免監聽器洩漏
    backdrop.classList.remove("visible");
    setTimeout(() => backdrop.remove(), 300);
  };
  $g("modal-close").addEventListener("click", close);
  backdrop.addEventListener("click", (e) => {
    if (e.target === backdrop) close();  // 只在點背景時關閉，點內容不關
  });
  document.addEventListener("keydown", onEsc);
}
