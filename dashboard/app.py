"""
app.py - Streamlit 互動儀表板（多線版）

整合多線核心模組，提供可互動的遊戲數學分析介面。
內建 Free Spin 馬可夫模型，各分頁一律呈現含 Free Spin 的分析結果；
FS 參數（局數 N、賠付倍率 M、Scatter 觸發機率）由 Sidebar 與捲軸設定調整。

  Tab 1：理論 RTP — 付線貢獻表 + 圓餅圖；FS 模式顯示 Gauge + 敏感度曲線
  Tab 2：統計分析 — 波動性指標 + 報酬分佈圖
  Tab 3：RTP 收斂曲線 — 模擬 RTP 隨局數收斂至理論值
  Tab 4：玩家旅程 — 多線多玩家餘額走勢模擬

啟動: PYTHONPATH=. .venv/bin/streamlit run dashboard/app.py
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from core.markov import FreespinConfig, expected_fs_spins
from core.config import FS_FREE_SPIN_COUNT, FS_WIN_MULTIPLIER
from core.calculator import calculate_rtp, RTPResult, PAYTABLE
from core.reel import PAYLINES, PAYLINE_NAMES, _build_strip, REEL_CONFIG, REEL_SLIDER_MAX
from core.markov_freespin_rtp import calculate_freespin_rtp, scatter_trigger_prob
from simulator.analyzer import (
    ConvergencePoint,
    VolatilityStats,
    analyze_convergence,
    analyze_distribution,
    analyze_volatility,
)
from simulator.markov_sim import (
    FreespinVolatilityStats,
    analyze_freespin_convergence,
    analyze_freespin_distribution,
    analyze_freespin_volatility,
)
from simulator.session_ml import PlayerJourneyResult, simulate_player_journeys

# ── 頁面設定 ──────────────────────────────────────────────────────────────────

st.set_page_config(page_title="老虎機數學引擎（多線版）", layout="wide")
st.title("老虎機數學引擎 — 多線互動儀表板")

# ── Session State 初始化（捲軸套用設定，預設值 = REEL_CONFIG）────────────────────
if "applied_reel" not in st.session_state:
    st.session_state["applied_reel"] = dict(REEL_CONFIG)  # {符號: 格數}

# ── Sidebar 共用參數 ───────────────────────────────────────────────────────────

with st.sidebar:
    st.header("模擬設定")

    num_games = st.select_slider(
        "模擬局數",
        options=[100_000, 250_000, 500_000, 1_000_000],
        value=500_000,
    )
    seed = st.number_input("隨機種子", value=42, step=1)

    _applied: dict[str, int] = st.session_state["applied_reel"]  # 先讀取已套用值（expander 外也需要）
    _ar_total = sum(_applied.values())
    _is_applied_custom = _applied != dict(REEL_CONFIG)

    with st.expander("捲軸格數設定", expanded=False):
        st.caption("調整後按「套用」使 Tab 1–3 模擬使用新的捲軸配置")

        # 從 REEL_CONFIG 動態生成滑桿；新增符號只需更新 REEL_CONFIG 與 REEL_SLIDER_MAX
        _sliders: dict[str, int] = {
            sym: st.slider(sym, 0, REEL_SLIDER_MAX.get(sym, 20), REEL_CONFIG[sym], step=1, key=f"sb_{sym.lower()}")
            for sym in REEL_CONFIG
        }

        _s_total = sum(_sliders.values())
        _s_default_total = sum(REEL_CONFIG.values())
        st.caption(f"目前格數：{_s_total}　預設：{_s_default_total}")

        _apply_disabled = _s_total < 3  # 總格數不足 3 格時禁用套用按鈕
        if st.button("套用捲軸設定 ✓", disabled=_apply_disabled, use_container_width=True):
            st.session_state["applied_reel"] = dict(_sliders)
            _applied = dict(_sliders)
            _ar_total = sum(_applied.values())
            _is_applied_custom = _applied != dict(REEL_CONFIG)

        if _is_applied_custom:
            st.info(f"已套用自訂捲軸（總格數 {_ar_total}）")
        else:
            st.caption(f"使用預設捲軸（總格數 {_ar_total}）")

    with st.expander("Free Spin 設定", expanded=True):
        # trigger_prob 由已套用的捲軸帶自動計算，不再由使用者手動輸入
        _applied_strip  = _build_strip(_applied)
        trigger_prob    = scatter_trigger_prob([_applied_strip] * 5)  # P(≥3/5 軸出現 Scatter)
        _ar_total_fs    = sum(_applied.values())
        _p_single       = _applied.get("Scatter", 0) / _ar_total_fs if _ar_total_fs > 0 else 0  # 單軸 Scatter 近似機率
        st.caption(
            f"Scatter 格數 = {_applied.get('Scatter', 0)}　單軸機率 ≈ {_p_single:.4f}　"
            f"觸發機率（≥3/5 軸）= {trigger_prob:.6f}"
            f"（約每 {1/trigger_prob:,.0f} 局觸發一次）" if trigger_prob > 0 else "（Scatter 格數為 0，Free Spin 不會觸發）"
        )
        # retrigger 已改為 Scatter 觸發，機率 = scatter 觸發機率（自動計算，與上方相同）
        retrigger_prob  = trigger_prob
        st.caption(f"Retrigger 機率（Scatter 觸發）= {retrigger_prob:.6f}（自動，與觸發機率相同）")
        free_spin_count = st.slider("Free Spin 局數 N", 3, 20, FS_FREE_SPIN_COUNT)
        win_multiplier  = st.slider("賠付倍率 M",       1, 10, int(FS_WIN_MULTIPLIER))

        # 發散防護：重置式 retrigger（=N）下，唯有每局必續場（r ≥ 1）才會 FS 永不結束、
        # 吸收鏈 (I−Q) 奇異使 RTP 無定義；現實捲軸 r < 1，故此旗標幾乎恆為 False。
        fs_diverges = retrigger_prob >= 1.0  # True = 每局必續場(r≥1)，FS 期望局數發散（RTP 無定義）
        _fs_diverge_msg = (  # 各 FS 分頁發散時共用的提示文字
            "含 Free Spin 的分析已暫停：目前續場機率 r ≥ 1，FS 永不結束（RTP 無定義）。"
            "請降低 Scatter 格數。"
        )
        if fs_diverges:
            st.warning(
                f"⚠ 續場機率 r = {retrigger_prob:.4f} ≥ 1，{_fs_diverge_msg}"
            )

# ── 快取函式（避免每次拖 Slider 都重跑模擬）────────────────────────────────────


@st.cache_data(show_spinner="多線計算中...")
def cached_ml_rtp(reel_cfg: dict[str, int]) -> RTPResult:  # 快取多線理論 RTP（按捲軸格數 dict 快取）
    """
    快取多線理論 RTP，key = 捲軸格數 dict。

    Args:
        reel_cfg: {符號名稱: 格數}，從 REEL_CONFIG 或 Sidebar 滑桿取得

    Returns:
        RTPResult，含各付線 RTP 分解與中獎組合明細
    """
    strip = _build_strip(reel_cfg)
    return calculate_rtp(reel_strips=[strip] * 5)


@st.cache_data(show_spinner="多線模擬中，請稍候...")
def cached_ml_volatility(n: int, s: int, reel_cfg: dict[str, int]) -> VolatilityStats:  # 快取多線波動性統計（含捲軸 key）
    """
    快取多線波動性分析，key = (局數, 種子, 捲軸格數 dict)。

    Args:
        n: 模擬局數
        s: 隨機種子
        reel_cfg: {符號名稱: 格數}

    Returns:
        VolatilityStats，含命中率、模擬 RTP、標準差
    """
    strip = _build_strip(reel_cfg)
    return analyze_volatility(num_games=n, seed=s, reel_strips=[strip] * 5)


@st.cache_data(show_spinner="多線模擬中，請稍候...")
def cached_ml_distribution(n: int, s: int, reel_cfg: dict[str, int]) -> dict[int, int]:  # 快取多線賠付分佈（含捲軸 key）
    """
    快取多線賠付分佈，key = (局數, 種子, 捲軸格數 dict)。

    Args:
        n: 模擬局數
        s: 隨機種子
        reel_cfg: {符號名稱: 格數}

    Returns:
        dict，key = 賠付倍率，value = 出現次數
    """
    strip = _build_strip(reel_cfg)
    return analyze_distribution(num_games=n, seed=s, reel_strips=[strip] * 5)


@st.cache_data(show_spinner="多線模擬中，請稍候...")
def cached_ml_convergence(n: int, nc: int, s: int, reel_cfg: dict[str, int]) -> list[ConvergencePoint]:  # 快取多線 RTP 收斂曲線（含捲軸 key）
    """
    快取多線收斂曲線，key = (總局數, 取樣點數, 種子, 捲軸格數 dict)。

    Args:
        n: 總模擬局數
        nc: 取樣點數量
        s: 隨機種子
        reel_cfg: {符號名稱: 格數}

    Returns:
        list[ConvergencePoint]，各取樣點的局數與誤差
    """
    strip = _build_strip(reel_cfg)
    return analyze_convergence(num_games=n, checkpoints=nc, seed=s, reel_strips=[strip] * 5)


@st.cache_data
def cached_ml_freespin_rtp(n_fs: int, m: float, reel_cfg: dict[str, int]):  # 快取多線含 FS 的馬可夫理論 RTP（trigger/retrigger 由捲軸帶自動計算）
    """
    快取多線含 Free Spin 的理論 RTP，key = (N, M, 捲軸格數 dict)。
    trigger_prob 與 retrigger_prob 皆由捲軸帶 Scatter 分佈自動衍生，不需手動傳入。

    Args:
        n_fs: Free Spin 局數
        m: 贏分倍率
        reel_cfg: {符號名稱: 格數}

    Returns:
        MarkovResult，含穩態比例與整體 RTP
    """
    cfg_fs = FreespinConfig(free_spin_count=n_fs, win_multiplier=m)  # trigger/retrigger 皆由捲軸 Scatter 分佈衍生，非 config 欄位
    strip = _build_strip(reel_cfg)
    return calculate_freespin_rtp(cfg_fs, reel_strips=[strip] * 5)


@st.cache_data(show_spinner="多線 Free Spin 模擬中，請稍候...")
def cached_ml_fs_volatility(n_fs: int, m: float, n: int, s: int, reel_cfg: dict[str, int]) -> FreespinVolatilityStats:  # 快取多線含 FS 的波動性統計（含捲軸 key）
    """
    快取多線含 Free Spin 的波動性統計，key = (N, M, 局數, 種子, 捲軸格數 dict)。

    Args:
        n_fs: Free Spin 局數
        m: 贏分倍率
        n: 模擬局數（有效押注局）
        s: 隨機種子
        reel_cfg: {符號名稱: 格數}

    Returns:
        FreespinVolatilityStats，含命中率、模擬 RTP、標準差
    """
    cfg_fs = FreespinConfig(free_spin_count=n_fs, win_multiplier=m)  # trigger/retrigger 皆由捲軸 Scatter 分佈衍生，非 config 欄位
    strip = _build_strip(reel_cfg)
    return analyze_freespin_volatility(cfg_fs, num_paid_spins=n, seed=s, reel_strips=[strip] * 5)


@st.cache_data(show_spinner="多線 Free Spin 模擬中，請稍候...")
def cached_ml_fs_distribution(n_fs: int, m: float, n: int, s: int, reel_cfg: dict[str, int]) -> dict[int, int]:  # 快取多線含 FS 的有效報酬分佈（含捲軸 key）
    """
    快取多線含 Free Spin 的有效報酬分佈，key = (N, M, 局數, 種子, 捲軸格數 dict)。

    Args:
        n_fs: Free Spin 局數
        m: 贏分倍率
        n: 模擬局數（有效押注局）
        s: 隨機種子
        reel_cfg: {符號名稱: 格數}

    Returns:
        dict，key = 有效報酬倍率，value = 出現次數
    """
    cfg_fs = FreespinConfig(free_spin_count=n_fs, win_multiplier=m)  # trigger/retrigger 皆由捲軸 Scatter 分佈衍生，非 config 欄位
    strip = _build_strip(reel_cfg)
    return analyze_freespin_distribution(cfg_fs, num_paid_spins=n, seed=s, reel_strips=[strip] * 5)


@st.cache_data(show_spinner="多線 Free Spin 模擬中，請稍候...")
def cached_ml_fs_convergence(n_fs: int, m: float, n: int, nc: int, s: int, reel_cfg: dict[str, int]):  # 快取多線含 FS 的 RTP 收斂曲線（含捲軸 key）
    """
    快取多線含 Free Spin 的收斂曲線，key = (N, M, 總局數, 取樣點數, 種子, 捲軸格數 dict)。

    Args:
        n_fs: Free Spin 局數
        m: 贏分倍率
        n: 總模擬局數（有效押注局）
        nc: 取樣點數量
        s: 隨機種子
        reel_cfg: {符號名稱: 格數}

    Returns:
        list，各取樣點的 ConvergencePoint
    """
    cfg_fs = FreespinConfig(free_spin_count=n_fs, win_multiplier=m)  # trigger/retrigger 皆由捲軸 Scatter 分佈衍生，非 config 欄位
    strip = _build_strip(reel_cfg)
    return analyze_freespin_convergence(cfg_fs, total_paid_spins=n, checkpoints=nc, seed=s, reel_strips=[strip] * 5)


@st.cache_data
def sensitivity_trigger_ml(n_fs: int, m: float, reel_cfg: dict[str, int]) -> tuple[list, list, list]:  # 掃描多線 Scatter 格數敏感度（sweep scatter 1~8）
    """
    固定 N、M 及非 Scatter 符號格數，掃描 Scatter 格數 1~8，
    用真實捲軸帶計算每格數對應的觸發機率與整體 RTP。

    Args:
        n_fs: Free Spin 局數（固定）
        m: 贏分倍率（固定）
        reel_cfg: {符號名稱: 格數}（Scatter 格數作為 cache key，內部 sweep 覆蓋）

    Returns:
        (scatter_counts, probs, rtps)：Scatter 格數、觸發機率、整體 RTP（%）；
        續場機率 r ≥ 1（FS 永不結束、RTP 無定義）的點以 NaN 表示，曲線在此斷開；
        現實捲軸 r < 1，故 8 個點通常皆有限
    """
    base_cfg = {k: v for k, v in reel_cfg.items() if k != "Scatter"}  # 固定非 Scatter 符號
    scatter_counts = list(range(1, 9))  # 1~8 格，共 8 個點
    probs: list[float] = []
    rtps:  list[float] = []
    for sc in scatter_counts:
        strips = [_build_strip({**base_cfg, "Scatter": sc})] * 5  # 每個 scatter 格數建一組捲軸帶
        p_trig = scatter_trigger_prob(strips)                       # 從實際捲軸帶計算觸發機率
        probs.append(p_trig)
        cfg = FreespinConfig(free_spin_count=n_fs, win_multiplier=m)  # trigger/retrigger 皆由捲軸 Scatter 分佈衍生，非 config 欄位
        if p_trig >= 1.0:
            # r ≥ 1：每局必續場，重置式 FS 永不結束、吸收鏈 (I−Q) 奇異使 RTP 無定義；
            # 標 NaN 使曲線在此斷開（現實捲軸 r < 1，此區實際不會出現）
            rtps.append(float("nan"))
        else:
            rtps.append(calculate_freespin_rtp(cfg, reel_strips=strips).total_rtp * 100)
    return scatter_counts, probs, rtps


@st.cache_data(show_spinner="模擬玩家旅程中，請稍候...")
def cached_player_journeys(  # 快取玩家旅程模擬（按所有參數 key 快取）
    num_players: int,
    starting_balance: float,
    stop_loss: float,
    stop_win: float,
    max_spins: int,
    n_fs: int,
    m: float,
    s: int,
    reel_cfg: dict[str, int],
    _v: int = 7,  # 快取版本號，結構變動時遞增以強制 cache miss
) -> PlayerJourneyResult:
    """
    快取玩家旅程模擬，key = 所有參數組合。

    Args:
        num_players: 模擬玩家數
        starting_balance: 起始餘額
        stop_loss: 停損線
        stop_win: 停利線
        max_spins: 最大局數
        n_fs: FS 局數
        m: 贏分倍率
        s: 隨機種子
        reel_cfg: 捲軸格數設定，用於建立自訂捲軸帶
        _v: 內部版本號，勿手動傳入

    Returns:
        PlayerJourneyResult，含各玩家餘額走勢與彙總統計
    """
    # simulate_player_journeys 以真實 Scatter 結果判定觸發與續場，
    # config 只提供 free_spin_count 與 win_multiplier（trigger/retrigger 非 config 欄位）
    fs_cfg = FreespinConfig(free_spin_count=n_fs, win_multiplier=m)
    strip = _build_strip(reel_cfg)
    return simulate_player_journeys(
        num_players=num_players,
        starting_balance=starting_balance,
        stop_loss=stop_loss,
        stop_win=stop_win,
        max_spins=max_spins,
        fs_config=fs_cfg,
        seed=s,
        reel_strips=[strip] * 5,
    )



# ── FS 有效報酬分桶定義（Tab 2 使用）────────────────────────────────────────────
_BUCKETS: list[tuple[str, int, int | None]] = [
    ("0x（未中獎）",  0,   0),
    ("1–10x",        1,   10),
    ("11–50x",       11,  50),
    ("51–200x",      51,  200),
    ("201–500x",     201, 500),
    ("501x+",        501, None),
]

# ── 四個 Tab ──────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4 = st.tabs(
    ["📊 理論 RTP", "📈 統計分析", "📉 RTP 收斂曲線", "🎰 玩家旅程"]
)

# ─────────────────────────────────────────────────────────────────────────────
# Tab 1：理論 RTP
# ─────────────────────────────────────────────────────────────────────────────

with tab1:
    if fs_diverges:
        st.warning(_fs_diverge_msg)
    else:
        ml_fs_result = cached_ml_freespin_rtp(
            free_spin_count, float(win_multiplier), _applied
        )
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("基礎每線 RTP", f"{ml_fs_result.base_rtp * 100:.4f}%")
        col2.metric(
            "整體 RTP（含 Free Spin）",
            f"{ml_fs_result.total_rtp * 100:.4f}%",
            f"+{ml_fs_result.freespin_contribution * 100:.4f}pp 來自 Free Spin",
        )
        col3.metric("付線數", f"{len(PAYLINES)}")
        col4.metric("House Edge（含 FS）", f"{(1 - ml_fs_result.total_rtp) * 100:.4f}%")

        st.caption(f"穩態：一般模式 {ml_fs_result.pi_normal * 100:.2f}% / Free Spin {ml_fs_result.pi_free * 100:.2f}%")

        base_pct  = ml_fs_result.base_rtp * 100
        total_pct = ml_fs_result.total_rtp * 100

        fig_ml_gauge = go.Figure(go.Indicator(
            mode="gauge+number+delta",
            value=total_pct,
            number={"suffix": "%", "valueformat": ".2f"},
            delta={"reference": base_pct, "valueformat": ".2f", "suffix": "pp vs 基礎"},
            title={"text": "多線整體 RTP（含 Free Spin）"},
            gauge={
                "axis": {"range": [0, max(50, total_pct + 5)]},
                "bar": {"color": "#2196f3"},
                "steps": [
                    {"range": [0, base_pct],         "color": "#aec7e8"},  # 藍色：基礎 RTP 區段
                    {"range": [base_pct, total_pct], "color": "#ffbb78"},  # 橘色：FS 貢獻區段
                ],
                "threshold": {
                    "line": {"color": "red", "width": 2},
                    "thickness": 0.75,
                    "value": base_pct,  # 紅線標記基礎 RTP 位置
                },
            },
        ))
        st.plotly_chart(fig_ml_gauge, use_container_width=True)

        st.subheader("Scatter 格數敏感度分析（多線）")
        st.caption("固定 N、M，掃描 Scatter 格數 1~8，觀察 ≥3/5 軸觸發機率對整體 RTP 的影響")

        ml_sc_counts, ml_probs, ml_rtps = sensitivity_trigger_ml(free_spin_count, float(win_multiplier), _applied)

        df_ml_sens = pd.DataFrame({
            "Scatter 格數": ml_sc_counts,
            "觸發機率 p":   ml_probs,
            "整體 RTP (%)": ml_rtps,
        })
        fig_ml_sens = px.line(
            df_ml_sens,
            x="Scatter 格數",
            y="整體 RTP (%)",
            title="多線：Scatter 格數 vs 整體 RTP（觸發條件：≥3/5 軸）",
            markers=True,
            hover_data=["觸發機率 p"],
        )
        fig_ml_sens.add_vline(
            x=_applied.get("Scatter", 0),
            line_dash="dash",
            line_color="red",
            annotation_text=f"目前 scatter={_applied.get('Scatter', 0)}，p={trigger_prob:.4f}",
        )
        st.plotly_chart(fig_ml_sens, use_container_width=True)

        st.subheader("各賠率 RTP 貢獻分佈（每線）")
        st.caption("以基礎捲軸（不含 FS 加成）為準，長條為各賠率對每線 RTP 的貢獻（由大到小），折線為累積占比")
        _ml_rtp_base = cached_ml_rtp(_applied)  # 已套用捲軸的 RTP，不含 FS 乘數，用於取得組合明細
        _ml_pareto_data: dict[str, float] = {}
        for _c in _ml_rtp_base.combo_breakdown:
            _key = f"{_c.multiplier}x"
            _ml_pareto_data[_key] = _ml_pareto_data.get(_key, 0) + _c.rtp_contribution

        # 依 RTP 貢獻由大到小排序，計算累積占比（Pareto：凸顯少數賠率主導整體 RTP）
        df_ml_pareto = (
            pd.DataFrame({"賠率": list(_ml_pareto_data.keys()), "RTP 貢獻": list(_ml_pareto_data.values())})
            .sort_values("RTP 貢獻", ascending=False)
            .reset_index(drop=True)
        )
        _total_contrib = df_ml_pareto["RTP 貢獻"].sum()                                  # 全部賠率貢獻總和（≈ 每線 RTP）
        df_ml_pareto["貢獻 (pp)"] = df_ml_pareto["RTP 貢獻"] * 100                        # 各賠率對每線 RTP 的貢獻（百分點）
        df_ml_pareto["累積占比 (%)"] = df_ml_pareto["RTP 貢獻"].cumsum() / _total_contrib * 100  # 累積占整體 RTP 比例

        fig_ml_pareto = go.Figure()
        fig_ml_pareto.add_bar(                                  # 長條：各賠率 RTP 貢獻（左軸，百分點）
            x=df_ml_pareto["賠率"],
            y=df_ml_pareto["貢獻 (pp)"],
            name="RTP 貢獻（pp）",
            marker_color="#2196f3",
        )
        fig_ml_pareto.add_scatter(                             # 折線：累積占比（右軸，%）
            x=df_ml_pareto["賠率"],
            y=df_ml_pareto["累積占比 (%)"],
            name="累積占比 (%)",
            mode="lines+markers",
            marker_color="#ff7f0e",
            yaxis="y2",
        )
        fig_ml_pareto.add_hline(                               # 80% 參考線：標示主導 RTP 的賠率邊界（80/20 法則）
            y=80, line_dash="dash", line_color="gray",
            annotation_text="80%", yref="y2",
        )
        fig_ml_pareto.update_layout(
            title=f"各賠率 RTP 貢獻 Pareto（每線基礎合計 {_ml_rtp_base.rtp_per_line * 100:.4f}%）",
            xaxis={"title": "賠率", "categoryorder": "array", "categoryarray": list(df_ml_pareto["賠率"])},
            yaxis={"title": "RTP 貢獻（百分點）"},
            yaxis2={"title": "累積占比 (%)", "overlaying": "y", "side": "right", "range": [0, 105]},
            legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
        )
        st.plotly_chart(fig_ml_pareto, use_container_width=True)

    st.divider()

    col_pl, col_pt = st.columns(2)

    with col_pl:
        st.subheader("付線配置")
        st.caption("每條付線從五條捲軸各取一行符號（上=row0、中=row1、下=row2）")
        _row_label = ["上", "中", "下"]
        _grid_data = [
            {
                "付線": PAYLINE_NAMES[i],
                **{f"捲軸{j + 1}": _row_label[pd_def[j]] for j in range(len(pd_def))},
            }
            for i, pd_def in enumerate(PAYLINES)
        ]
        st.dataframe(pd.DataFrame(_grid_data), use_container_width=True, hide_index=True)

    with col_pt:
        st.subheader("賠付表")
        st.caption("Wild 可替換任意符號，自動選出最高賠率")
        _symbols = list(dict.fromkeys(e.symbol_name for e in PAYTABLE))  # 保留順序去重
        _counts  = sorted(set(e.required_count for e in PAYTABLE))
        _pt_lookup = {(e.symbol_name, e.required_count): e.multiplier for e in PAYTABLE}
        _pt_rows = [
            {
                "符號": sym,
                **{f"{n} 連": f"{_pt_lookup[(sym, n)]}x" if (sym, n) in _pt_lookup else "—" for n in _counts},
            }
            for sym in _symbols
        ]
        st.dataframe(pd.DataFrame(_pt_rows), use_container_width=True, hide_index=True)

# ─────────────────────────────────────────────────────────────────────────────
# Tab 2：統計分析
# ─────────────────────────────────────────────────────────────────────────────

with tab2:
    if fs_diverges:
        st.warning(_fs_diverge_msg)
    else:
        n_lines = len(PAYLINES)  # 付線數，動態讀取
        st.caption(f"每局有效報酬 = 基礎局 {n_lines} 線合計 + 觸發 FS 後所有 FS 局 {n_lines} 線合計（含倍率加成）")
        ml_fs_stats = cached_ml_fs_volatility(
            free_spin_count, float(win_multiplier), num_games, int(seed), _applied
        )

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("命中率（含 FS）", f"{ml_fs_stats.hit_rate * 100:.4f}%", f"每 {1/ml_fs_stats.hit_rate:.1f} 局中獎一次")
        col2.metric(
            "模擬 RTP（每線，含 FS）",
            f"{ml_fs_stats.simulated_rtp * 100:.4f}%",
            f"{(ml_fs_stats.simulated_rtp - ml_fs_stats.theoretical_rtp) * 100:+.4f}% vs 理論",
        )
        col3.metric("標準差（含 FS）", f"{ml_fs_stats.std_dev:.4f}", "FS 爆發顯著拉高波動")
        col4.metric("最大有效報酬", f"{ml_fs_stats.max_payout:.0f}x", f"{len(PAYLINES)} 線合計（含 FS）")

        st.subheader(f"有效報酬分佈（{len(PAYLINES)} 線合計）")
        ml_fs_dist = cached_ml_fs_distribution(
            free_spin_count, float(win_multiplier), num_games, int(seed), _applied
        )
        ml_fs_view = st.radio("顯示模式", ["含未中獎（0x）", "僅中獎局"], horizontal=True, key="ml_fs_dist_view")

        bucketed_ml_fs: dict[str, int] = {label: 0 for label, *_ in _BUCKETS}
        for payout, count in ml_fs_dist.items():
            for label, lo, hi in _BUCKETS:
                if payout >= lo and (hi is None or payout <= hi):
                    bucketed_ml_fs[label] += count
                    break

        if ml_fs_view == "僅中獎局":
            bucketed_ml_fs.pop("0x（未中獎）")

        df_ml_fs_dist = pd.DataFrame([
            {"區間": label, "出現次數": count, "頻率(%)": count / num_games * 100}
            for label, count in bucketed_ml_fs.items()
            if count > 0
        ])

        fig_ml_fs_dist = px.bar(
            df_ml_fs_dist,
            x="區間",
            y="頻率(%)",
            title=f"多線含 Free Spin 有效報酬分佈（{len(PAYLINES)} 線合計）",
            text="出現次數",
        )
        fig_ml_fs_dist.update_traces(texttemplate="%{text:,}", textposition="outside")
        st.plotly_chart(fig_ml_fs_dist, use_container_width=True)

# ─────────────────────────────────────────────────────────────────────────────
# Tab 3：RTP 收斂曲線
# ─────────────────────────────────────────────────────────────────────────────

with tab3:
    col_left, col_right = st.columns([3, 1])
    with col_right:
        num_checkpoints = st.slider("取樣點數量", 10, 50, 20)

    if fs_diverges:
        st.warning(_fs_diverge_msg)
    else:
        st.caption("含 Free Spin 的多線機台：方差更大，相同局數下收斂速度比無 FS 版本慢")
        with st.spinner("多線 Free Spin 模擬中，請稍候..."):
            ml_fs_series = cached_ml_fs_convergence(
                free_spin_count, float(win_multiplier),
                num_games, num_checkpoints, int(seed), _applied,
            )
        ml_fs_theoretical = ml_fs_series[0].theoretical_rtp

        df_ml_fs_conv = pd.DataFrame([
            {
                "局數": pt.num_games,
                "模擬 RTP (%)": pt.simulated_rtp * 100,
                "絕對誤差 (pp)": pt.abs_error,
                "達標": pt.abs_error < 0.1,
            }
            for pt in ml_fs_series
        ])

        fig_ml_fs_conv = px.line(
            df_ml_fs_conv,
            x="局數",
            y="模擬 RTP (%)",
            title="多線含 Free Spin 模擬 RTP 收斂曲線（每線標準化）",
            markers=True,
        )
        fig_ml_fs_conv.add_hline(
            y=ml_fs_theoretical * 100,
            line_dash="dash",
            line_color="red",
            annotation_text=f"理論 RTP {ml_fs_theoretical * 100:.4f}%",
        )
        fig_ml_fs_conv.add_hrect(
            y0=ml_fs_theoretical * 100 - 0.1,
            y1=ml_fs_theoretical * 100 + 0.1,
            fillcolor="red",
            opacity=0.08,
            annotation_text="±0.1pp 目標帶",
        )
        st.plotly_chart(fig_ml_fs_conv, use_container_width=True)

        fig_ml_fs_err = px.line(
            df_ml_fs_conv,
            x="局數",
            y="絕對誤差 (pp)",
            title="多線含 Free Spin 絕對誤差隨局數下降趨勢",
            markers=True,
        )
        fig_ml_fs_err.add_hline(
            y=0.1,
            line_dash="dash",
            line_color="orange",
            annotation_text="目標門檻 0.1pp",
        )
        st.plotly_chart(fig_ml_fs_err, use_container_width=True)

        st.subheader("收斂資料表")
        st.dataframe(df_ml_fs_conv, use_container_width=True)


# ─────────────────────────────────────────────────────────────────────────────
# Tab 4：玩家旅程
# ─────────────────────────────────────────────────────────────────────────────

with tab4:
    st.caption(
        "模擬多位玩家在多線機台的完整遊戲旅程，"
        "觀察停損、停利、最大局數三種停止條件下的餘額走勢與分佈。"
    )

    col_j1, col_j2, col_j3 = st.columns(3)
    with col_j1:
        j_num_players      = st.slider("模擬玩家數", 10, 500, 100, step=10)
        j_starting_balance = st.number_input(
            "起始餘額（單位：每線押注）", min_value=100.0, max_value=10000.0, value=1000.0, step=100.0
        )
    with col_j2:
        j_stop_loss = st.number_input(
            "停損線（低於此值即停）",
            min_value=0.0, max_value=float(j_starting_balance), value=0.0, step=50.0,
        )
        j_stop_win = st.number_input(
            "停利線（高於此值即停）",
            min_value=float(j_starting_balance), max_value=20000.0,
            value=float(j_starting_balance * 2), step=100.0,
        )
    with col_j3:
        j_max_spins = st.slider("每位玩家最大局數", 100, 2000, 500, step=100)
        j_seed      = st.number_input(
            "旅程隨機種子", min_value=0, max_value=9999, value=42, step=1, key="journey_seed"
        )

    if fs_diverges:
        st.warning(_fs_diverge_msg)
        st.stop()  # r ≥ 1 時跳過玩家旅程模擬（FS 永不結束，模擬無法收斂）

    with st.spinner("模擬玩家旅程中，請稍候..."):
        journey_result = cached_player_journeys(
            num_players=j_num_players,
            starting_balance=j_starting_balance,
            stop_loss=j_stop_loss,
            stop_win=j_stop_win,
            max_spins=j_max_spins,
            n_fs=free_spin_count,
            m=float(win_multiplier),
            s=int(j_seed),
            reel_cfg=_applied,
        )

    # ── 彙總指標 ──────────────────────────────────────────────────────────────
    _num_lines   = journey_result.num_lines                           # 付線數
    _bust_rate   = journey_result.bust_count / j_num_players * 100   # 爆倉率（觸停損）
    _win_rate    = journey_result.win_count  / j_num_players * 100   # 停利率（觸停利）
    _max_rate    = journey_result.max_count  / j_num_players * 100   # 達最大局數比例
    _avg_balance = sum(journey_result.final_balances) / j_num_players
    _avg_spins   = sum(journey_result.spin_counts)    / j_num_players

    # 模擬 RTP = 總回報 / 總押注；總回報 = 各局賠付合計 = 總押注 + 淨損益
    _total_wagered  = sum(sc * _num_lines for sc in journey_result.spin_counts)
    _total_returned = sum(
        sc * _num_lines - j_starting_balance + fb
        for fb, sc in zip(journey_result.final_balances, journey_result.spin_counts)
    )
    _sim_rtp = _total_returned / _total_wagered if _total_wagered > 0 else 0.0  # 模擬 RTP（每線標準化）

    col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
    col_m1.metric("爆倉率（觸停損）", f"{_bust_rate:.1f}%", f"{journey_result.bust_count} 位")
    col_m2.metric("停利率（觸停利）", f"{_win_rate:.1f}%",  f"{journey_result.win_count} 位")
    col_m3.metric("達上限率（滿局）", f"{_max_rate:.1f}%",  f"{journey_result.max_count} 位")
    col_m4.metric("平均局數",         f"{_avg_spins:.0f} 局")
    col_m5.metric(
        "模擬 RTP（每線）",
        f"{_sim_rtp * 100:.4f}%",
        f"{(_sim_rtp - journey_result.theoretical_rtp) * 100:+.4f}% vs 理論",
    )

    # ── 餘額走勢圖（抽樣前 30 位，避免圖表過於擁擠）──────────────────────────
    st.subheader("餘額走勢圖")
    _sample_n  = min(30, j_num_players)  # 最多顯示 30 條走勢
    _traj_rows = []
    for _pi in range(_sample_n):
        for _spin, _bal in enumerate(journey_result.balance_histories[_pi]):
            _traj_rows.append({"玩家": f"P{_pi + 1}", "局數": _spin, "餘額": _bal})
    df_traj = pd.DataFrame(_traj_rows)

    fig_traj = px.line(
        df_traj,
        x="局數",
        y="餘額",
        color="玩家",
        title=f"玩家餘額走勢（顯示前 {_sample_n} 位，共 {j_num_players} 位）",
        labels={"局數": "局數", "餘額": "餘額（單位：每線押注）"},
    )
    fig_traj.add_hline(
        y=j_starting_balance,
        line_dash="dash",
        line_color="gray",
        annotation_text=f"起始餘額 {j_starting_balance:.0f}",
    )
    fig_traj.add_hline(
        y=j_stop_win,
        line_dash="dot",
        line_color="green",
        annotation_text=f"停利線 {j_stop_win:.0f}",
    )
    if j_stop_loss > 0:
        fig_traj.add_hline(
            y=j_stop_loss,
            line_dash="dot",
            line_color="red",
            annotation_text=f"停損線 {j_stop_loss:.0f}",
        )
    fig_traj.update_traces(opacity=0.5, line=dict(width=1))
    fig_traj.update_layout(showlegend=False)
    st.plotly_chart(fig_traj, use_container_width=True)

    # ── 最終餘額分佈直方圖 ────────────────────────────────────────────────────
    st.subheader("最終餘額分佈")
    fig_hist = px.histogram(
        pd.DataFrame({"最終餘額": journey_result.final_balances}),
        x="最終餘額",
        nbins=40,
        title=f"最終餘額分佈（{j_num_players} 位玩家）",
        labels={"最終餘額": "最終餘額（單位：每線押注）", "count": "玩家數"},
    )
    fig_hist.add_vline(x=j_starting_balance, line_dash="dash", line_color="gray",  annotation_text="起始")
    fig_hist.add_vline(x=_avg_balance,       line_dash="solid", line_color="blue", annotation_text=f"均值 {_avg_balance:.0f}")
    st.plotly_chart(fig_hist, use_container_width=True)

    # ── 玩家局數分佈直方圖 ────────────────────────────────────────────────────
    st.subheader("玩家局數分佈")
    fig_spins = px.histogram(
        pd.DataFrame({"實際局數": journey_result.spin_counts}),
        x="實際局數",
        nbins=30,
        title=f"玩家局數分佈（{j_num_players} 位玩家）",
        labels={"實際局數": "玩家實際玩局數", "count": "玩家數"},
    )
    fig_spins.add_vline(x=_avg_spins, line_dash="solid", line_color="blue", annotation_text=f"均值 {_avg_spins:.0f}")
    st.plotly_chart(fig_spins, use_container_width=True)

    # ── Free Spin 統計（機台一律含 FS，故恆顯示）──────────────────────────────
    st.subheader("Free Spin 統計")

    _total_triggers   = sum(journey_result.fs_trigger_counts)    # 全體玩家觸發 FS 總次數
    _total_retriggers = sum(journey_result.fs_retrigger_counts)   # 全體玩家續場總次數
    _total_spins      = sum(journey_result.spin_counts)           # 全體玩家押注總局數
    _avg_triggers     = _total_triggers   / j_num_players         # 每位玩家平均觸發次數
    _avg_retriggers   = _total_retriggers / j_num_players         # 每位玩家平均續場次數
    _fs_rate_sim      = _total_triggers   / _total_spins if _total_spins > 0 else 0.0  # 模擬觸發率（每局）
    _retrig_rate      = _total_retriggers / _total_triggers if _total_triggers > 0 else 0.0  # 續場率（每次觸發）：每觸發一次 FS 平均續場幾次
    # 理論對照（重置模型）：每次觸發的期望續場次數 = 每局續場機率 r × 一次觸發的平均 FS 局數 E[FS]
    #   E[FS] 由 (N+1) 吸收鏈精確求得；每局以機率 r 續場，由期望值線性 → 期望續場次數 = r·E[FS]
    #   不可直接拿 retrigger_prob 對照 _retrig_rate：前者是「每局機率」、後者是「每次觸發的次數」，量綱不同
    _efs_for_retrig = expected_fs_spins(  # 一次觸發的平均 FS 局數 E[FS]（吸收鏈精確值）
        FreespinConfig(free_spin_count=free_spin_count, win_multiplier=win_multiplier),
        retrigger_prob,
    )
    _retrig_per_trigger = retrigger_prob * _efs_for_retrig  # 重置模型每次觸發期望續場次數 = r·E[FS]

    col_fs1, col_fs2, col_fs3, col_fs4 = st.columns(4)
    col_fs1.metric(
        "模擬觸發率（每局）",
        f"{_fs_rate_sim:.4f}",
        f"{_fs_rate_sim - trigger_prob:+.4f} vs 理論",  # 顯示與理論的真實差值（趨近 0 即模擬準確）
    )
    col_fs2.metric(
        "平均觸發次數（每位玩家）",
        f"{_avg_triggers:.2f} 次",
        f"總計 {_total_triggers:,} 次",
    )
    col_fs3.metric(
        "續場率（每次觸發後）",
        f"{_retrig_rate:.4f}",
        f"{_retrig_rate - _retrig_per_trigger:+.4f} vs 理論",  # 顯示與理論的真實差值（趨近 0 即模擬準確）
    )
    col_fs4.metric(
        "平均續場次數（每位玩家）",
        f"{_avg_retriggers:.2f} 次",
        f"總計 {_total_retriggers:,} 次",
    )

    col_fsc1, col_fsc2 = st.columns(2)

    with col_fsc1:
        st.caption("各玩家觸發 Free Spin 次數分佈")
        fig_fs_trig = px.histogram(
            pd.DataFrame({"觸發次數": journey_result.fs_trigger_counts}),
            x="觸發次數",
            nbins=max(1, max(journey_result.fs_trigger_counts)),
            title="觸發 Free Spin 次數分佈（每位玩家）",
            labels={"觸發次數": "觸發次數", "count": "玩家數"},
        )
        fig_fs_trig.add_vline(
            x=_avg_triggers,
            line_dash="solid",
            line_color="blue",
            annotation_text=f"均值 {_avg_triggers:.2f}",
        )
        st.plotly_chart(fig_fs_trig, use_container_width=True)

    with col_fsc2:
        # 只取有觸發 FS 的玩家（fs_trigger_counts > 0）
        _fs_earners = [
            e for e, t in zip(journey_result.fs_earnings, journey_result.fs_trigger_counts)
            if t > 0
        ]
        if _fs_earners:
            _avg_fs_earn = sum(_fs_earners) / len(_fs_earners)  # 有觸發 FS 的玩家平均獲益
            st.caption(f"進入 FS 的玩家 FS 期間總獲益分佈（{len(_fs_earners)} 位）")
            fig_fs_earn = px.histogram(
                pd.DataFrame({"FS 獲益": _fs_earners}),
                x="FS 獲益",
                nbins=30,
                title="FS 期間額外獲益分佈（僅有觸發 FS 的玩家）",
                labels={"FS 獲益": "FS 獲益（單位：每線押注）", "count": "玩家數"},
            )
            fig_fs_earn.add_vline(
                x=_avg_fs_earn,
                line_dash="solid",
                line_color="orange",
                annotation_text=f"均值 {_avg_fs_earn:.1f}",
            )
            st.plotly_chart(fig_fs_earn, use_container_width=True)
        else:
            st.info("本次模擬無玩家觸發 Free Spin，無法顯示獲益分佈。")
