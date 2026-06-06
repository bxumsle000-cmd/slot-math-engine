/**
 * sound.js — 音效系統（Web Audio API 程式生成，不依賴音效檔案）
 *
 * 設計理念：用 OscillatorNode + GainNode 即時合成各種效果音，
 * 配合 ADSR envelope 控制音量起落，做出按鈕、轉軸、中獎等聲音。
 *
 * 提供靜音開關（localStorage 持久化）。
 */

const SOUND_MUTED_KEY = "slot_muted";  // 靜音狀態的 localStorage key

const Sound = {
  ctx: null,            // AudioContext，延遲建立（瀏覽器要求 user gesture 後才能啟動）
  muted: false,         // 是否靜音
  masterGain: null,     // 主音量節點

  // 初始化音訊系統（必須在使用者第一次互動後呼叫）
  init() {
    if (this.ctx) return;  // 已初始化過
    this.ctx = new (window.AudioContext || window.webkitAudioContext)();
    this.masterGain = this.ctx.createGain();
    this.masterGain.gain.value = 0.4;  // 主音量降低避免太吵
    this.masterGain.connect(this.ctx.destination);
    this.muted = localStorage.getItem(SOUND_MUTED_KEY) === "true";
  },

  toggleMute() {
    this.muted = !this.muted;
    localStorage.setItem(SOUND_MUTED_KEY, this.muted ? "true" : "false");
    return this.muted;
  },

  // ── 基礎工具：播放一個帶 ADSR envelope 的音調 ─────────────────
  // freq: 頻率(Hz)、duration: 總時長(秒)、type: 波形、volume: 0~1、startOffset: 延遲開始(秒)
  _tone(freq, duration, type = "sine", volume = 0.3, startOffset = 0) {
    if (this.muted || !this.ctx) return;
    const t0 = this.ctx.currentTime + startOffset;

    const osc = this.ctx.createOscillator();
    osc.type = type;
    osc.frequency.value = freq;

    const gain = this.ctx.createGain();
    gain.gain.setValueAtTime(0, t0);                                      // 起點靜音
    gain.gain.linearRampToValueAtTime(volume, t0 + 0.005);                // Attack 5ms
    gain.gain.exponentialRampToValueAtTime(0.001, t0 + duration);         // Release

    osc.connect(gain);
    gain.connect(this.masterGain);
    osc.start(t0);
    osc.stop(t0 + duration);
  },

  // 頻率掃過（從 freqStart 到 freqEnd），常用於 FS 觸發等上揚音
  _sweep(freqStart, freqEnd, duration, type = "sine", volume = 0.3, startOffset = 0) {
    if (this.muted || !this.ctx) return;
    const t0 = this.ctx.currentTime + startOffset;

    const osc = this.ctx.createOscillator();
    osc.type = type;
    osc.frequency.setValueAtTime(freqStart, t0);
    osc.frequency.exponentialRampToValueAtTime(Math.max(freqEnd, 1), t0 + duration);  // 防止 0Hz

    const gain = this.ctx.createGain();
    gain.gain.setValueAtTime(0, t0);
    gain.gain.linearRampToValueAtTime(volume, t0 + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.001, t0 + duration);

    osc.connect(gain);
    gain.connect(this.masterGain);
    osc.start(t0);
    osc.stop(t0 + duration);
  },

  // ── 各種效果音 ─────────────────────────────────────────────────

  // 按鈕點擊：高頻短促「叮」
  click() {
    this._tone(800, 0.08, "square", 0.15);
  },

  // SPIN 開始：低沉啟動聲
  spinStart() {
    this._sweep(100, 220, 0.4, "sawtooth", 0.2);
  },

  // 捲軸停止：每軸一聲咔，col 越大音調越高（由低到高累積期待）
  reelStop(col) {
    const freq = 180 + col * 40;  // col=0 → 180Hz, col=4 → 340Hz
    this._tone(freq, 0.1, "triangle", 0.25);
  },

  // 中獎鈴聲：兩個和諧音同響
  win() {
    this._tone(660, 0.3, "sine", 0.3);       // E5
    this._tone(880, 0.3, "sine", 0.25);      // A5（高八度）
    this._tone(1320, 0.3, "triangle", 0.15, 0.05);  // E6 高泛音
  },

  // FS 觸發：上揚合成音 + 三連音
  freeSpinTrigger() {
    this._sweep(220, 880, 0.6, "sine", 0.3);
    this._tone(660, 0.15, "sine", 0.3, 0.3);
    this._tone(880, 0.15, "sine", 0.3, 0.45);
    this._tone(1100, 0.4, "sine", 0.3, 0.6);
  },

  // Retrigger：兩段上揚（比首次觸發更激動）
  retrigger() {
    this._sweep(440, 1320, 0.4, "sine", 0.3);
    this._sweep(660, 1760, 0.4, "sine", 0.3, 0.2);
  },

  // FS 結束：下行收尾
  fsEnd() {
    this._sweep(660, 220, 0.5, "sine", 0.25);
  },

  // Big Win 等級的慶祝音：和弦上升 + 多次連發
  bigWin(level = 1) {
    // level 1=NICE, 2=BIG, 3=HUGE, 4=MEGA
    const notes = [523, 659, 784, 1047];  // C E G C（大三和弦 + 八度）
    const count = 2 + level;               // 1→3 次, 4→6 次
    for (let i = 0; i < count; i++) {
      const offset = i * 0.15;
      notes.forEach((n, idx) => {
        this._tone(n * (1 + i * 0.1), 0.35, "sine", 0.25, offset + idx * 0.02);
      });
    }
  },
};
