/**
 * game.js — 遊戲主邏輯（階段 3：含炫炮動畫）
 *
 * 負責：
 *   - 初始化 5 條捲軸（每軸 30 格的 strip 結構）
 *   - 載入遊戲設定（賠付表、付線、FS 規則）
 *   - SPIN：呼叫 API → 啟動 5 軸錯開停止的動畫 → 顯示中獎發光、贏分跳數
 *   - 押注金額 +/- 調整（FS 期間鎖定）
 *   - Free Spin 狀態顯示與三種事件浮層（觸發/Retrigger/結束）
 *   - Scatter 預期動畫：前兩軸出現 Scatter 時，第 3 軸後放慢「期待感」
 */

// ── 全域狀態 ──────────────────────────────────────────────────────
let gameConfig = null;   // /api/v1/games/config 的內容（首次進入遊戲頁時載入）
let isSpinning = false;  // 是否正在 spin（防止連點）
let currentBet = 10;     // 當前押注金額
const BET_STEPS = [5, 10, 25, 50, 100, 250, 500];  // 可選押注級距

// ── 符號 → 顯示 HTML 對應表 ──────────────────────────────────────
// 每個符號用不同的視覺呈現：emoji、文字、發光效果
const SYMBOL_HTML = {
  Blank:   '<span class="symbol-text symbol-blank">▪ ▪ ▪</span>',
  Cherry:  '<span class="symbol">🍒</span>',
  Lemon:   '<span class="symbol">🍋</span>',
  BAR:     '<span class="symbol-text symbol-bar">BAR</span>',
  Seven:   '<span class="symbol-text symbol-seven">7</span>',
  Wild:    '<span class="symbol-text symbol-wild">WILD</span>',
  Scatter: '<span class="symbol symbol-scatter">⭐</span>',
};

// ── 工具：取 DOM ─────────────────────────────────────────────────
const $g = (id) => document.getElementById(id);

// ── 捲軸動畫常數 ────────────────────────────────────────────────
const STRIP_LENGTH = 30;        // 每條捲軸 strip 含 30 個符號（足夠長到看不出循環）
const REELS = 5;                // 捲軸數
const ROWS = 3;                 // 行數

const SPIN_BASE_MS = 700;       // 第一軸 spin 時長
const SPIN_DELAY_MS = 180;      // 每軸延後的時間（製造由左到右停止的效果）

// ── 工具：建立單一符號 cell DOM ────────────────────────────────
function makeCell(symbol) {
  const cell = document.createElement("div");
  cell.className = "slot-cell";
  cell.dataset.symbol = symbol;
  cell.innerHTML = SYMBOL_HTML[symbol] || symbol;
  return cell;
}

// 隨機抽一個符號（用於 strip 中段填充；從 gameConfig.symbols 動態讀取）
function randomSymbol() {
  const pool = gameConfig?.symbols ?? ["Blank", "Cherry", "Lemon", "BAR", "Seven", "Wild", "Scatter"];
  return pool[Math.floor(Math.random() * pool.length)];
}

// ── 初始化 5 條捲軸（每軸一個 strip 容器，內含 30 個 cell） ────
function initGrid() {
  const grid = $g("slot-grid");
  grid.innerHTML = "";

  for (let col = 0; col < REELS; col++) {
    const reel = document.createElement("div");
    reel.className = "reel";
    reel.dataset.col = col;

    const window = document.createElement("div");
    window.className = "reel-window";

    const strip = document.createElement("div");
    strip.className = "reel-strip";

    // 起始狀態：strip 前 3 格是顯示用、之後 27 格是「滾動中的符號」
    // 預設前 3 格全 Blank（玩家還沒按 SPIN）
    strip.appendChild(makeCell("Blank"));
    strip.appendChild(makeCell("Blank"));
    strip.appendChild(makeCell("Blank"));
    for (let i = 3; i < STRIP_LENGTH; i++) {
      strip.appendChild(makeCell(randomSymbol()));
    }

    window.appendChild(strip);
    reel.appendChild(window);
    grid.appendChild(reel);
  }
}

// ── 取得當前 cell 實際高度（含 gap），用於精準位移 ───────────
function getCellOffset() {
  const cell = document.querySelector(".slot-cell");
  if (!cell) return 126;  // 預設 120 + 6 gap
  const cellHeight = cell.getBoundingClientRect().height;
  return cellHeight + 6;  // 6 = .reel-strip 的 gap
}

// ── 捲軸滾動動畫 ────────────────────────────────────────────────
// 將最終要顯示的 3 個符號（top/mid/bot）放在 strip 末尾的最後 3 格，
// 然後把整個 strip 平移上去，視覺上就像是符號高速滑過後停在指定位置。
function spinSingleReel(col, topMidBot, durationMs, withAnticipation = false) {
  const reel = document.querySelector(`.reel[data-col="${col}"]`);
  const strip = reel.querySelector(".reel-strip");
  const offset = getCellOffset();

  // 1. 先把 strip 拉回原位（無動畫），準備重新滾動
  strip.classList.remove("spinning", "anticipation");
  strip.style.transition = "none";
  strip.style.transform = "translateY(0)";

  // 2. 重新填充 strip：前 3 格保留上一局結果（讓玩家看到動畫起點）；
  //    中間填隨機符號；最後 3 格放本局結果（top/mid/bot）
  // 簡化：直接重建整條 strip
  strip.innerHTML = "";
  // 前 3 格：本局起始畫面（隨機，因為動畫一開始就會被滾走）
  for (let i = 0; i < 3; i++) strip.appendChild(makeCell(randomSymbol()));
  // 中段：隨機符號
  for (let i = 3; i < STRIP_LENGTH - 3; i++) strip.appendChild(makeCell(randomSymbol()));
  // 最後 3 格：本局最終結果（top→mid→bot）
  strip.appendChild(makeCell(topMidBot[0]));
  strip.appendChild(makeCell(topMidBot[1]));
  strip.appendChild(makeCell(topMidBot[2]));

  // 3. 強制重排，確保下面的 transition 生效
  void strip.offsetHeight;

  // 4. 啟動動畫：滾動到 strip 末尾（顯示最後 3 格 = 本局結果）
  strip.style.setProperty("--spin-duration", `${durationMs}ms`);
  strip.classList.add(withAnticipation ? "anticipation" : "spinning");
  strip.style.transition = "";  // 改回用 CSS 設定的 transition
  const finalY = -(STRIP_LENGTH - 3) * offset;  // 滾動距離 = (30 - 3) × 每格高度
  strip.style.transform = `translateY(${finalY}px)`;

  // 5. 回傳 Promise：動畫結束時 resolve
  return new Promise((resolve) => {
    const effective = withAnticipation ? durationMs * 1.8 : durationMs;
    setTimeout(resolve, effective + 50);  // +50ms 緩衝避免提早觸發
  });
}

// ── 4-match 偵測：檢查指定 payline 在前 4 軸是否構成 4 連 ────────
// 規則：考慮 Wild 替換（Wild 可代替任意付線符號），Blank/Scatter 不算
function isPaylineFourMatch(finalGrid, paylineDef) {
  // 取前 4 軸在此 payline 上的符號
  const first4 = paylineDef.positions.slice(0, 4).map((row, col) => finalGrid[row][col]);

  // 找第一個非 Wild 的「基準符號」（Wild 自己會替換成基準符號）
  const base = first4.find((s) => s !== "Wild" && s !== "Blank" && s !== "Scatter");

  if (!base) {
    // 沒有非 Wild 符號：只有全 Wild 才算 4-match（4 個 Wild 等同最高賠付符號）
    return first4.every((s) => s === "Wild");
  }

  // 其餘 cell 必須是 base 或 Wild 才算 4-match
  return first4.every((s) => s === base || s === "Wild");
}

// 任一付線在前 4 軸構成 4-match → 第 5 軸需要 anticipation
function hasAnyFourMatch(finalGrid) {
  if (!gameConfig?.paylines) return false;
  return gameConfig.paylines.some((p) => isPaylineFourMatch(finalGrid, p));
}

// ── 主 spin 動畫流程：5 軸由左到右錯開停止 ──────────────────────
async function animateSpin(finalGrid) {
  // finalGrid[row][col] = 符號名稱
  const promises = [];
  let scatterSoFar = 0;  // 已停下的軸出現幾個 Scatter（用於觸發第 3 軸後的 anticipation）

  // 預先檢查：本局是否有任何 payline 在前 4 軸 4-match（第 5 軸專屬 anticipation）
  const fourMatch = hasAnyFourMatch(finalGrid);

  for (let col = 0; col < REELS; col++) {
    const topMidBot = [finalGrid[0][col], finalGrid[1][col], finalGrid[2][col]];
    const hasScatter = topMidBot.includes("Scatter");

    // anticipation 條件（OR 在一起，任一成立即放慢）：
    //   (a) col ≥ 2 且前面已有 2 個 Scatter → Scatter 預期
    //   (b) col === 4 且本局有 payline 在前 4 軸構成 4-match → 4-match 預期
    const useAnticipation =
      (col >= 2 && scatterSoFar >= 2) ||
      (col === 4 && fourMatch);

    const duration = SPIN_BASE_MS + col * SPIN_DELAY_MS;

    promises.push(spinSingleReel(col, topMidBot, duration, useAnticipation));

    if (hasScatter) scatterSoFar++;
  }

  await Promise.all(promises);
}

// ── 中獎格數偵測：對單條 payline 算出實際中了幾連（3/4/5） ───────
// 演算法：賠付表已按倍率由高到低排序，逐條規則嘗試左起連線，第一條符合的即為本線贏法。
// 與後端 _find_matching_rule 邏輯一致（含 Wild 替換）。
function findWinningCount(symbols, paytable) {
  for (const rule of paytable) {
    let matches = true;
    for (let i = 0; i < rule.count; i++) {
      const s = symbols[i];
      if (s !== rule.symbol && s !== "Wild") {
        matches = false;
        break;
      }
    }
    if (matches) return rule.count;  // 找到第一條符合的規則，回傳連線數
  }
  return 0;  // 安全保護：API 說中獎但這裡找不到規則（不應發生）
}

// ── 中獎付線發光 ────────────────────────────────────────────────
// 只標記實際中獎的格數（左起 3/4/5 連），而非整條 payline 都發光
function highlightWinningLines(paylineMultipliers, finalGrid) {
  // 先清除上一局的 winning 標記
  document.querySelectorAll(".slot-cell.winning").forEach((c) => c.classList.remove("winning"));

  if (!gameConfig) return;

  paylineMultipliers.forEach((mult, idx) => {
    if (mult <= 0) return;  // 此付線未中獎
    const paylineDef = gameConfig.paylines[idx];
    if (!paylineDef) return;

    // 取本付線在 5 軸上的符號序列
    const lineSymbols = paylineDef.positions.map((row, col) => finalGrid[row][col]);

    // 算出實際中了幾連（3、4 或 5）
    const winCount = findWinningCount(lineSymbols, gameConfig.paytable);
    if (winCount === 0) return;  // 安全保護

    // 只標記前 winCount 個格子，後面沒貢獻中獎的不發光
    for (let col = 0; col < winCount; col++) {
      const row = paylineDef.positions[col];
      const strip = document.querySelector(`.reel[data-col="${col}"] .reel-strip`);
      if (!strip) continue;
      const cells = strip.children;
      const visibleCell = cells[cells.length - 3 + row];  // top=−3, mid=−2, bot=−1
      if (visibleCell) visibleCell.classList.add("winning");
    }
  });
}

// 整台機台閃一次金光（任何中獎都觸發）
function flashMachineWin() {
  const machine = document.querySelector(".slot-machine");
  machine.classList.remove("winning");
  void machine.offsetHeight;
  machine.classList.add("winning");
  setTimeout(() => machine.classList.remove("winning"), 1200);
}

// ── 贏分跳數動畫 ────────────────────────────────────────────────
function animateWinAmount(finalAmount, bet) {
  const el = $g("last-win");
  const isBigWin = finalAmount >= bet * 10;  // 押注 10 倍以上算 Big Win

  el.classList.remove("counting", "big-win");

  if (finalAmount === 0) {
    el.textContent = "0";
    return;
  }

  // 從 0 跳到目標值，850ms 內完成，越接近終點越慢
  const startTime = performance.now();
  const duration = 850;

  function tick(now) {
    const t = Math.min((now - startTime) / duration, 1);
    const eased = 1 - Math.pow(1 - t, 3);  // easeOutCubic
    const current = finalAmount * eased;
    el.textContent = formatBalance(current);

    if (t < 1) {
      requestAnimationFrame(tick);
    } else {
      el.textContent = formatBalance(finalAmount);  // 確保最終值精準
      el.classList.add("counting");
      if (isBigWin) el.classList.add("big-win");
      setTimeout(() => el.classList.remove("counting"), 400);
    }
  }
  requestAnimationFrame(tick);
}

// ── 載入遊戲設定（首次進入遊戲頁呼叫） ──────────────────────────
async function loadConfig() {
  if (gameConfig) return gameConfig;  // 已載入過就直接回傳
  gameConfig = await API.getConfig();
  return gameConfig;
}

// ── 押注金額調整 ────────────────────────────────────────────────
let betLocked = false;  // FS 期間鎖定，無法調整押注

function setBet(amount) {
  // 找到最接近的級距
  const idx = BET_STEPS.indexOf(amount);
  if (idx === -1) return;
  currentBet = amount;
  $g("bet-value").textContent = amount;

  // 更新 +/- 按鈕：被鎖定時兩邊都 disable；否則依級距邊界
  const minusBtn = $g("bet-minus");
  const plusBtn = $g("bet-plus");
  if (betLocked) {
    minusBtn.disabled = true;
    plusBtn.disabled = true;
  } else {
    minusBtn.disabled = idx === 0;
    plusBtn.disabled = idx === BET_STEPS.length - 1;
  }
}

function adjustBet(delta) {
  if (betLocked) return;  // FS 期間禁止調整
  const idx = BET_STEPS.indexOf(currentBet);
  const newIdx = idx + delta;
  if (newIdx < 0 || newIdx >= BET_STEPS.length) return;
  setBet(BET_STEPS[newIdx]);
}

// 切換押注鎖定狀態（FS 期間鎖定到指定金額）
function lockBet(lockedAmount) {
  betLocked = true;
  currentBet = lockedAmount;
  $g("bet-value").textContent = lockedAmount;
  $g("bet-minus").disabled = true;
  $g("bet-plus").disabled = true;
  $g("bet-value").classList.add("locked");  // 視覺提示
}

function unlockBet() {
  betLocked = false;
  $g("bet-value").classList.remove("locked");
  setBet(currentBet);  // 重新計算 +/- 邊界
}

// ── FS 狀態顯示 ─────────────────────────────────────────────────
// 兩種狀態：
//   - hidden：非 FS 模式
//   - 顯示：FREE SPIN 進行中 + 副標提示 Scatter retrigger 規則
function updateFsBanner(remaining) {
  const banner = $g("fs-banner");
  const titleEl = $g("fs-banner-title");
  const hintEl = $g("fs-banner-hint");

  if (remaining > 0) {
    banner.classList.remove("hidden");
    banner.classList.remove("last-spin");
    $g("fs-count").textContent = remaining;

    const minScatter = gameConfig?.free_spin.min_scatter ?? 3;
    const fsCount = gameConfig?.free_spin.free_spin_count ?? 10;
    const winMultiplier = gameConfig?.free_spin.win_multiplier ?? 1;

    $g("fs-multiplier").textContent = `${winMultiplier}×`;
    titleEl.textContent = "FREE SPIN 進行中";
    hintEl.textContent = `出現 ${minScatter} 個 Scatter 可重置為 ${fsCount} 局`;
  } else {
    banner.classList.add("hidden");
    banner.classList.remove("last-spin");
  }
}

// ── 顯示中獎/訊息 ───────────────────────────────────────────────
function showGameMsg(text, type = "lose") {
  const msg = $g("game-msg");
  msg.className = `game-msg ${type}`;  // type: win / lose / error
  msg.textContent = text;
}

// ── 處理 spin 結果（動畫結束後呼叫） ────────────────────────────
function handleSpinResult(result) {
  // 餘額更新（同步 header）
  currentPlayer.balance = parseFloat(result.balance_after);
  currentPlayer.free_spins_remaining = result.free_spins_remaining;
  currentPlayer.fs_locked_bet = parseFloat(result.fs_locked_bet);
  updateHeader();

  // 本局贏分（跳數動畫）
  const payout = parseFloat(result.payout);
  const bet = parseFloat(result.bet_amount);
  animateWinAmount(payout, bet);

  // 中獎付線發光（只標記實際中獎格數，不是整條 payline）
  highlightWinningLines(result.payline_multipliers, result.grid);
  if (payout > 0) flashMachineWin();

  // FS 狀態
  updateFsBanner(result.free_spins_remaining);

  // 押注鎖定：FS 進行中時鎖定到 fs_locked_bet，FS 結束時解鎖
  const lockedBet = parseFloat(result.fs_locked_bet);
  if (result.free_spins_remaining > 0 && lockedBet > 0) {
    lockBet(lockedBet);
  } else {
    unlockBet();
  }

  // ── 訊息顯示（三種 FS 狀態各有不同訊息與彈窗） ─────────────────
  const fsCount = gameConfig.free_spin.free_spin_count;

  if (result.awarded_new_fs && !result.is_free_spin) {
    // 情境 1：一般局首次觸發 FS
    showGameMsg(`🎉 觸發 FREE SPIN！獲得 ${fsCount} 局免費！`, "win");
    showFsOverlay("🎰 FREE SPIN!", `獲得 ${fsCount} 局免費旋轉`, "trigger");
    Sound.freeSpinTrigger();
  } else if (result.awarded_new_fs && result.is_free_spin) {
    // 情境 2：FS 中 retrigger（重置為 N 局，非累加）
    showGameMsg(`🔄 RETRIGGER！局數重置為 ${fsCount} 局！`, "win");
    showFsOverlay("🔄 RETRIGGER!", `Free Spin 局數重置為 ${fsCount} 局`, "retrigger");
    Sound.retrigger();
  } else if (result.is_free_spin && result.free_spins_remaining === 0) {
    // 情境 3：FS 最後一局結束（沒 retrigger）
    showGameMsg("🏁 Free Spin 結束，回到一般模式", "lose");
    showFsOverlay("🏁 FREE SPIN END", "回到一般模式", "end");
    Sound.fsEnd();
  } else if (payout > 0) {
    const numLines = gameConfig.paylines.length;  // 付線數（5），用於換算成玩家直觀倍率
    const winLines = result.payline_multipliers
      // 顯示換算後倍率 = 原始倍率 ÷ 付線數，與賠付表 modal 一致（x3 → x0.6）
      .map((m, i) => m > 0 ? `付線${i + 1} (${m / numLines}×)` : null)
      .filter(Boolean)
      .join("，");
    // FS 局：付線倍率為基礎值，但 payout 已乘 win_multiplier，於訊息補上優惠倍率提示
    const fsBonus = result.is_free_spin
      ? `，X${gameConfig.free_spin.win_multiplier} 優惠倍率`
      : "";
    showGameMsg(`💰 ${winLines}${fsBonus} 贏得 ${formatBalance(payout)} 金幣！`, "win");
    Sound.win();
  } else if (result.is_free_spin) {
    showGameMsg("本局 Free Spin 未中獎", "lose");
  } else {
    showGameMsg("再接再厲！", "lose");
  }

  // Big Win 全螢幕演出（達 10× 押注以上才觸發；含自己的音效）
  // 延遲一下讓贏分跳數先動起來再蓋上 overlay
  if (payout > 0) {
    setTimeout(() => showBigWin(payout, bet), 600);
  }
}

// ── 大型 FS 通知浮層（觸發、retrigger、結束） ────────────────────
// 半透明覆蓋全螢幕，2 秒後自動淡出
function showFsOverlay(title, subtitle, kind) {
  // 移除已存在的浮層，避免堆疊
  document.querySelectorAll(".fs-overlay").forEach((el) => el.remove());

  const overlay = document.createElement("div");
  overlay.className = `fs-overlay fs-overlay--${kind}`;  // kind: trigger / retrigger / end
  overlay.innerHTML = `
    <div class="fs-overlay-title">${title}</div>
    <div class="fs-overlay-subtitle">${subtitle}</div>
  `;
  document.body.appendChild(overlay);

  // 觸發進場動畫（強制 reflow 後加 class）
  requestAnimationFrame(() => overlay.classList.add("visible"));

  // 2 秒後淡出並移除
  setTimeout(() => {
    overlay.classList.remove("visible");
    setTimeout(() => overlay.remove(), 400);  // 等淡出動畫結束
  }, 2000);
}

// ── SPIN 按鈕點擊 ───────────────────────────────────────────────
async function handleSpin() {
  if (isSpinning) return;  // 防止連點
  isSpinning = true;
  const spinBtn = $g("btn-spin");
  spinBtn.disabled = true;
  spinBtn.textContent = "旋轉中...";

  // 清除上一局的中獎標記，避免動畫期間還亮著
  document.querySelectorAll(".slot-cell.winning").forEach((c) => c.classList.remove("winning"));
  $g("last-win").classList.remove("counting", "big-win");

  try {
    Sound.init();           // 首次互動時初始化 AudioContext（瀏覽器要求）
    Sound.spinStart();      // 啟動音

    // 平行進行：(1) API 呼叫 (2) 捲軸動畫
    const spinPromise = API.spin(currentBet);
    const result = await spinPromise;

    // 啟動 5 軸滾動動畫；每軸停止時播放 reelStop 音效
    await animateSpinWithSound(result.grid);

    // 動畫結束 → 顯示中獎、跳數、發光等
    handleSpinResult(result);
  } catch (err) {
    showGameMsg(err.message, "error");
  } finally {
    isSpinning = false;
    spinBtn.disabled = false;
    spinBtn.textContent = "SPIN";
  }
}

// ── animateSpin 包裝：在每軸停下時插入音效 ──────────────────────
async function animateSpinWithSound(finalGrid) {
  // 每軸停止時間 = SPIN_BASE_MS + col * SPIN_DELAY_MS（與 spinSingleReel 一致）
  // 在那個時間點觸發對應音效
  for (let col = 0; col < REELS; col++) {
    const duration = SPIN_BASE_MS + col * SPIN_DELAY_MS;
    setTimeout(() => Sound.reelStop(col), duration);
  }
  await animateSpin(finalGrid);
}

// ── 賠付表彈窗（modal 版） ───────────────────────────────────────
function showPaytable() {
  openPaytableModal();  // 委派給 modal.js
}

// ── 遊戲頁初始化（每次切到 game 頁時呼叫） ──────────────────────
async function initGamePage() {
  if (!gameConfig) {
    try {
      await loadConfig();
    } catch (err) {
      showGameMsg("無法載入遊戲設定：" + err.message, "error");
      return;
    }
  }

  initGrid();
  setBet(currentBet);

  // 顯示玩家當前 FS 剩餘與押注鎖定（重整頁面後恢復狀態）
  const fsRemaining = currentPlayer?.free_spins_remaining || 0;
  const lockedBet = parseFloat(currentPlayer?.fs_locked_bet || 0);
  updateFsBanner(fsRemaining);
  if (fsRemaining > 0 && lockedBet > 0) {
    lockBet(lockedBet);
  } else {
    unlockBet();
  }
}

// ── 綁定遊戲頁事件 ───────────────────────────────────────────────
function bindGameEvents() {
  $g("btn-spin").addEventListener("click", handleSpin);
  $g("bet-plus").addEventListener("click", () => adjustBet(+1));
  $g("bet-minus").addEventListener("click", () => adjustBet(-1));
  $g("link-paytable").addEventListener("click", showPaytable);

  // 空白鍵也能 spin（提升手感）
  document.addEventListener("keydown", (e) => {
    if (e.code === "Space" && !$g("page-game").classList.contains("hidden")) {
      // 只有遊戲頁可見時才響應空白鍵
      if (document.activeElement.tagName !== "INPUT") {
        e.preventDefault();
        handleSpin();
      }
    }
  });
}
