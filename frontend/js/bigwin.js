/**
 * bigwin.js — Big Win 全螢幕演出
 *
 * 依「贏分 / 押注」倍數分 4 個等級，等級越高演出越誇張：
 *   - 10×  NICE WIN   紅色脈動
 *   - 30×  BIG WIN    金色光環
 *   - 50×  HUGE WIN   彩虹光圈 + 粒子
 *   - 100× MEGA WIN   滿版粒子噴發 + 持續閃爍
 */

// ── Big Win 等級門檻（贏分 / 押注 的倍數）─────────────────────────
const BIG_WIN_LEVELS = [
  { threshold: 100, name: "MEGA WIN",  cls: "mega",   particles: 60, duration: 3500, level: 4 },
  { threshold: 50,  name: "HUGE WIN",  cls: "huge",   particles: 40, duration: 3000, level: 3 },
  { threshold: 30,  name: "BIG WIN",   cls: "big",    particles: 25, duration: 2500, level: 2 },
  { threshold: 10,  name: "NICE WIN",  cls: "nice",   particles: 15, duration: 2000, level: 1 },
];

// 判斷贏分是否達到 Big Win 等級
function getBigWinLevel(payout, bet) {
  if (bet <= 0 || payout <= 0) return null;
  const ratio = payout / bet;
  return BIG_WIN_LEVELS.find((lvl) => ratio >= lvl.threshold) || null;
}

// ── 顯示 Big Win 演出（會自動播放音效）──────────────────────────
function showBigWin(payout, bet) {
  const config = getBigWinLevel(payout, bet);
  if (!config) return false;  // 未達 Big Win 等級

  // 移除可能殘留的舊演出
  document.querySelectorAll(".bigwin-overlay").forEach((el) => el.remove());

  // 建立浮層 DOM
  const overlay = document.createElement("div");
  overlay.className = `bigwin-overlay bigwin-${config.cls}`;
  overlay.innerHTML = `
    <div class="bigwin-particles" id="bigwin-particles-${Date.now()}"></div>
    <div class="bigwin-content">
      <div class="bigwin-title">${config.name}</div>
      <div class="bigwin-amount" id="bigwin-amount">0</div>
    </div>
  `;
  document.body.appendChild(overlay);

  // 觸發粒子（隨等級數量增加）
  spawnParticles(overlay.querySelector(".bigwin-particles"), config.particles);

  // 進場
  requestAnimationFrame(() => overlay.classList.add("visible"));

  // 數字跳動
  animateBigWinAmount(overlay.querySelector("#bigwin-amount"), payout, 1500);

  // 播放音效
  Sound.bigWin(config.level);

  // 自動消失
  setTimeout(() => {
    overlay.classList.remove("visible");
    setTimeout(() => overlay.remove(), 500);
  }, config.duration);

  return true;
}

// ── 在容器內噴發 N 個隨機粒子 ─────────────────────────────────
function spawnParticles(container, count) {
  for (let i = 0; i < count; i++) {
    const p = document.createElement("div");
    p.className = "bigwin-particle";

    // 隨機外觀
    const angle = Math.random() * 360;                       // 噴射方向
    const distance = 200 + Math.random() * 400;              // 飛行距離（px）
    const delay = Math.random() * 600;                       // 起始延遲（ms）
    const size = 8 + Math.random() * 16;                     // 大小（px）
    const colors = ["#ffd700", "#ff4dc4", "#00e5ff", "#ff0844"];  // 賭場色盤
    const color = colors[Math.floor(Math.random() * colors.length)];

    // 用 CSS 變數傳遞參數，由 animation keyframes 使用
    p.style.setProperty("--angle", `${angle}deg`);
    p.style.setProperty("--distance", `${distance}px`);
    p.style.setProperty("--delay", `${delay}ms`);
    p.style.setProperty("--size", `${size}px`);
    p.style.setProperty("--color", color);

    container.appendChild(p);
  }
}

// ── Big Win 金額跳動（比一般跳數更慢、更張揚）───────────────────
function animateBigWinAmount(el, finalAmount, duration) {
  const startTime = performance.now();
  function tick(now) {
    const t = Math.min((now - startTime) / duration, 1);
    const eased = 1 - Math.pow(1 - t, 4);  // easeOutQuart，越尾段越慢
    el.textContent = formatBalance(finalAmount * eased);
    if (t < 1) requestAnimationFrame(tick);
    else el.textContent = formatBalance(finalAmount);  // 確保最終值精準
  }
  requestAnimationFrame(tick);
}
