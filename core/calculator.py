"""
calculator.py - 多線理論 RTP 計算模組（5×3 格式）

針對 5 軸 3 行老虎機，精確計算含 3/4/5-of-a-kind 的多線理論 RTP。

核心邏輯：
    1. 各捲軸獨立，每停格等機率 → 任一 5 軸符號組合機率 = 各軸邊際機率之積
    2. 對每條付線建立「符號機率向量」，外積展開得聯合機率張量（7^5 = 16,807 格）
    3. 與預先查表的賠付倍率張量逐元素相乘、求和 → 每線 RTP（向量化，毫秒級）
    4. Wild 替換後查賠付表，支援 3/4/5-of-a-kind；左起連線規則
"""

import numpy as np
from dataclasses import dataclass
from itertools import product as iter_product

from core.reel import REEL_STRIPS, PAYLINES, ReelStrip 
from core.paytable import PaylineEntry, resolve_wild, _find_matching_rule, PAYTABLE


@dataclass
class ComboResult:
    """
    多線中獎組合的 RTP 貢獻分析。

    Attributes:
        raw_combo: 原始符號組合（可能含 Wild）
        resolved_combo: Wild 替換後的有效符號組合
        multiplier: 賠付倍率（命中的最高規則）
        probability: 此組合在付線 0 的出現機率（各軸邊際機率之積）
        rtp_contribution: 此組合對每線 RTP 的貢獻 = 機率 × 倍率
    """
    raw_combo: tuple           # 原始符號組合（含 Wild）
    resolved_combo: tuple      # Wild 替換後的有效符號組合
    multiplier: int            # 賠付倍率
    probability: float         # 在付線 0 出現的機率（各軸邊際機率之積）
    rtp_contribution: float    # 對每線 RTP 的貢獻 = 機率 × 倍率


@dataclass
class RTPResult:
    """
    多線 RTP 計算的完整結果。

    Attributes:
        rtp_per_line: 平均每條付線的 RTP（押滿線時線數抵消，等於整體 RTP）
        combo_breakdown: 中獎組合明細（以付線 0 為代表）
    """
    rtp_per_line: float                 # 每線平均 RTP（= 整體 RTP，線數抵消）
    combo_breakdown: list[ComboResult]  # 中獎組合明細（付線 0 代表，各付線相同）


def _evaluate_payline(  # 評估單條付線的中獎倍率（含 Wild 替換）
    combo: tuple,
    paytable: list[PaylineEntry] = PAYTABLE,
) -> int:
    """
    對付線上的符號序列計算賠付倍率。

    先執行 Wild 替換（嘗試組成最高獎），再用左起連線規則查賠付表。

    Args:
        combo: 付線上的符號組合（依捲軸 0→N 排列，可能含 Wild）
        paytable: 賠付規則列表（按倍率由高到低排序）

    Returns:
        賠付倍率，未中獎為 0
    """
    resolved = resolve_wild(combo, paytable)           # Wild 替換為能組出最高獎的普通符號
    rule = _find_matching_rule(resolved, paytable)     # 左起連線查表，第一命中即最高獎
    return rule.multiplier if rule is not None else 0


def calculate_rtp(  # 計算多線理論 RTP（向量化，毫秒級）
    reel_strips: list[ReelStrip] = REEL_STRIPS,
    paylines: list[tuple] = PAYLINES,
    paytable: list[PaylineEntry] = PAYTABLE,
) -> RTPResult:
    """
    精確計算多線理論 RTP。

    算法分五個步驟：

        STEP 1｜前置：符號索引 & 各軸機率表
            收集所有符號建立「名稱 → 整數索引」映射；
            計算各軸每種符號在每行的出現機率。

        STEP 2｜賠付倍率張量 combo_payout_tensor，shape (7,7,7,7,7)
            遍歷所有 7^5 = 16,807 種符號組合，查賠付表得倍率，填入張量。
            不中獎的組合填 0。

        STEP 3｜各付線：機率張量 P 與該線 RTP
            機率張量 P，shape (7,7,7,7,7)
            因各軸獨立，P[i0,i1,i2,i3,i4] = 各軸在付線指定行出現對應符號的機率之總和。
            用外積（np.outer）從 5 個 shape (7,) 向量逐步展開得到。
            相乘求和：RTP = (combo_payout_tensor × P).sum()
            兩張量逐元素相乘再加總 = Σ(機率 × 賠率) = 此付線的期望賠付。

        STEP 4｜各付線 RTP 取平均 → 整體 RTP

        STEP 5｜（副產品）中獎組合明細

    Args:
        reel_strips: 捲軸帶列表（每條各有 total_stops 個停格）
        paylines: 付線定義列表（每條為各捲軸的行索引）
        paytable: 賠付規則列表（按倍率由高到低排序）

    Returns:
        RTPResult，含整體 RTP 與各付線 RTP 分解
    """
    reel_strips = reel_strips or REEL_STRIPS  # 顯式傳入 None 時兜底為預設捲軸帶（避免下游 len(None) 崩潰）
    num_reels = len(reel_strips)  # 捲軸數（5 軸）

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 1｜前置：符號索引 & 各軸機率表
    # ══════════════════════════════════════════════════════════════════════════
    #
    # ── STEP 1.1：收集所有出現在捲軸帶上的符號，建立索引映射 ──
    #  把所有符號名稱收集起來、排序後，給每個符號一個固定的整數編號。
    #
    #  符號共 7 種：
    #       0: BAR
    #       1: Blank
    #       2: Cherry
    #       3: Lemon
    #       4: Scatter
    #       5: Seven
    #       6: Wild
    #
    #   sym_idx 是一個 dict，讓你用符號名稱查到它的整數編號，例如：
    #       sym_idx['Seven'] → 5
    #       sym_idx['BAR']   → 0

    symbol_types = sorted(set(s for reel in reel_strips for s in reel.symbols))
    n_sym_types = len(symbol_types)                             # 符號種類數（含 Wild），例如 7
    sym_idx = {sym: i for i, sym in enumerate(symbol_types)}   # 符號名稱 → 整數索引

    # ── STEP 1.2：計算每條捲軸在每行的符號出現機率 ──────────────────────────────
    #
    # 老虎機每次旋轉時，每條捲軸會「隨機停在某個位置」，然後露出連續 3 個符號（上中下行）。
    # 某符號出現在某行的機率」= 該符號出現在那行的停格數 / 總停格數。
    #
    # sym_prob_all_reels 是一個 list，長度 = 捲軸數（5 條）。
    # 每個元素是一張 shape (n_sym_types, 3) 的表格，意思是：
    #
    #           行0     行1     行2
    #   BAR    0.150   0.150   0.150    ← BAR 出現在上/中/下行的機率各是多少
    #   Blank  0.100   0.100   0.100
    #   Cherry 0.275   0.275   0.275
    #   ...
    #
    # 關鍵性質：window() 是環狀取連續 3 格，捲軸跑遍所有停格時，
    # 上/中/下三行各自都「完整掃過整條捲軸帶一次、只是起點偏移」，
    # 因此三行的符號分佈必然完全相同（上表三欄數值一致即由此而來）。
    # 所以只算「單行」邊際機率向量，再廣播成三欄即可，不必逐行重算。
    #   單行某符號機率 = 該符號在捲軸帶上的格數 / 總停格數

    sym_prob_all_reels: list[np.ndarray] = []
    for reel in reel_strips:
        col = np.zeros(n_sym_types)              # 單行的符號機率向量，shape (符號種類數,)
        for sym in reel.symbols:                 # 跑過捲軸帶每一格（每格即一個符號名稱）
            # sym_idx[...] 把符號名稱轉成整數索引；每格貢獻 1/總停格數 的機率
            col[sym_idx[sym]] += 1.0 / reel.total_stops
        # 廣播成 shape (符號種類數, 3)：三行完全相同，維持下游 [:, pl[k]] 的取欄介面
        sym_prob_matrix = np.repeat(col.reshape(-1, 1), 3, axis=1)
        sym_prob_all_reels.append(sym_prob_matrix)

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 2｜賠付倍率張量 combo_payout_tensor
    #   遍歷所有 7^5 = 16,807 種符號組合，查賠付表，填入 shape (7,7,7,7,7) 的張量。
    #   不中獎填 0。
    # ══════════════════════════════════════════════════════════════════════════
    #
    # ── STEP 2.1：遍歷所有符號組合，建立「符號名稱 → 賠付倍率」的 dict ──
    #
    # 把 7 種符號排列組合成所有可能的 5 軸組合（7^5 = 16,807 種），
    # 每種組合丟進 _evaluate_payline() 查賠付，只保留有獎（倍率 > 0）的組合。
    #
    # combo_payout_dict 的結構範例：
    #   {
    #       ('Seven', 'Seven', 'Seven', 'Seven', 'Seven'): 500,
    #       ('Seven', 'Seven', 'Seven', 'Seven', 'BAR'):   0,   ← 這種不會存進去（m=0 被過濾掉）
    #       ('BAR',   'BAR',   'BAR',   'BAR',   'BAR'):   100,
    #       ('Wild',  'Seven', 'Seven', 'Seven', 'Seven'): 500, ← Wild 被替換成 Seven
    #       ...
    #   }

    combo_payout_dict: dict[tuple, int] = {}
    for raw_combo in iter_product(symbol_types, repeat=num_reels):
        m = _evaluate_payline(raw_combo, paytable)
        if m > 0:
            combo_payout_dict[raw_combo] = m

    # ── STEP 2.2：把 dict 轉成 numpy 張量 ──
    #
    # combo_payout_dict 和 combo_payout_tensor 儲存的是完全相同的資料（符號組合 → 賠付倍率），
    # 差別只在於「如何表示符號」：
    #   - combo_payout_dict：用符號名稱（字串），例如 ('Seven', 'Seven', ...) → 500
    #   - combo_payout_tensor：用整數索引，例如 (5, 5, 5, 5, 5) → 500.0
    #
    # combo_payout_tensor 是 shape (7, 7, 7, 7, 7) 的 5 維陣列，共 16,807 格。
    # 沒有中獎的組合格子填 0，有中獎的格子填賠付倍率。


    combo_payout_tensor = np.zeros([n_sym_types] * num_reels, dtype=np.float64)
    for raw_combo, m in combo_payout_dict.items():
        # 把符號名稱 tuple 逐一轉成整數索引 tuple
        # 例：('Seven', 'BAR', 'Cherry', 'Lemon', 'Wild') → (5, 0, 2, 3, 6)
        idx = tuple(sym_idx[s] for s in raw_combo)
        combo_payout_tensor[idx] = float(m)

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 3｜各付線：機率張量 P 與該線 RTP
    #   機率張量 P，shape (7,7,7,7,7)，每條付線各算一次
    #   P[i0,i1,i2,i3,i4] = 五軸在此付線指定行同時出現對應符號的聯合機率。
    #   因各軸獨立，聯合機率 = 各軸邊際機率之積，用外積展開一次算完。
    #
    #   相乘求和：RTP = (combo_payout_tensor × P).sum()
    #   逐元素相乘再加總 = Σ(機率 × 賠率) = 此付線的期望賠付。
    # ══════════════════════════════════════════════════════════════════════════
    #
    # ── STEP 3.1：取付線各軸的機率向量 ──
    #
    # 逐步拆解 sym_prob_all_reels[k][:, pl[k]] 每一步的形狀與內容：
    #
    # 先認清矩陣兩個維度的意義（兩維代表的東西不同，別搞混）：
    #   第一維（列）= 符號（7 種）； 第二維（欄）= 行（上0/中1/下2 共 3 種）
    #
    #   ① sym_prob_all_reels[k]  →「挑軸」
    #        → 第 k 軸的完整機率表，shape (n_sym_types, 3)
    #
    #   ② pl[k]  →「挑行」
    #        → 一個整數，付線在第 k 軸經過的行號（0=上行, 1=中行, 2=下行）
    #          例：pl=(1,1,1,1,1) 走中排 → pl[k]=1
    #
    #   ③ [:, pl[k]]  → pl[k]（管「行」維）    → 鎖定其中一行（不是各行，是單一一行）
    #                   鎖定「第 pl[k] 行」、取出該行上「全部 7 種符號」的機率，
    #                   結果由 (n_sym_types, 3) 降成 shape (n_sym_types,) 的一維向量
    #
    # 例如付線走「中排」（pl = (1,1,1,1,1)），符號順序 [BAR,Blank,Cherry,Lemon,Scatter,Seven,Wild]：
    #   reel_prob_vecs[0] = 捲軸0 中行的符號機率 = [0.150, 0.100, 0.275, 0.275, 0.025, 0.150, 0.025]
    #   reel_prob_vecs[1] = 捲軸1 中行的符號機率 = [...]
    #   ...
    
    payline_rtp: list[float] = []
    for pl in paylines:
        reel_prob_vecs = [sym_prob_all_reels[k][:, pl[k]] for k in range(num_reels)]

        # ── STEP 3.2：外積展開成聯合機率張量 P ──
        #
        # 逐步外積，把 5 個 shape (7,) 的向量擴展成 shape (7,7,7,7,7) 的聯合機率張量
        # P[i0, i1, i2, i3, i4] = 五軸同時出現符號 i0,i1,i2,i3,i4 的機率
        #
        # 外積是逐步展開的，因為 np.outer 只接受兩個一維向量：
        #   初始：P shape = (7,)           ← 捲軸0的機率向量
        #   k=1：P shape = (7, 7)          ← 捲軸0 × 捲軸1
        #   k=2：P shape = (7, 7, 7)       ← 捲軸0 × 捲軸1 × 捲軸2
        #   k=3：P shape = (7, 7, 7, 7)
        #   k=4：P shape = (7, 7, 7, 7, 7) ← 全部五軸的聯合機率張量，所有格子加總 = 1.0
        #
        # ravel() 的作用：np.outer 只接受兩個一維向量，
        #   所以每次都先把已經多維的 P 壓平成一維，做完外積後再 reshape 還原成正確維度。
        P: np.ndarray = reel_prob_vecs[0]
        for k in range(1, num_reels):
            P = np.outer(P.ravel(), reel_prob_vecs[k]).reshape([n_sym_types] * (k + 1))

        # ── STEP 3.3：與賠付張量相乘求和 → 此付線 RTP ──
        # combo_payout_tensor * P：兩個 shape 完全相同的張量逐元素相乘
        #   每個格子 = 該符號組合出現的機率 × 該組合的賠付倍率
        # .sum()：把所有格子加總 = 期望賠付 = 此付線 RTP
        payline_rtp.append(float((combo_payout_tensor * P).sum()))

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 4｜各付線 RTP 取平均 → 整體 RTP
    # ══════════════════════════════════════════════════════════════════════════
    rtp_per_line = sum(payline_rtp) / len(paylines)

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 5｜中獎明細：以付線 0 為代表，列出每個中獎組合的機率與 RTP 貢獻
    # ══════════════════════════════════════════════════════════════════════════
    #
    # 為什麼只用付線 0 代表所有付線？
    #   因為本專案的捲軸帶設計讓「每行的符號分佈完全相同」，
    #   不管付線走上排、中排還是下排，每個符號出現的機率都一樣。
    #   所以付線 0 的中獎組合機率分佈和其他付線完全相同，拿來當代表即可。
    #
    # ref_reel_prob_vecs 和 STEP 3.1 的 reel_prob_vecs 結構完全一樣，
    # 只是固定取付線 0 的行索引（ref_payline = paylines[0]）。
    ref_payline = paylines[0]
    ref_reel_prob_vecs = [sym_prob_all_reels[k][:, ref_payline[k]] for k in range(num_reels)]

    combo_breakdown: list[ComboResult] = []
    for raw_combo, m in combo_payout_dict.items():
        idx = tuple(sym_idx[s] for s in raw_combo)
        # 聯合機率 = 各軸邊際機率之積
        # ref_reel_prob_vecs[k][idx[k]] = 捲軸 k 在付線0指定行出現符號 idx[k] 的機率
        # np.prod([...]) 把五條捲軸的機率全部相乘 → 這個組合的聯合出現機率
        prob = float(np.prod([ref_reel_prob_vecs[k][idx[k]] for k in range(num_reels)]))
        resolved = tuple(resolve_wild(raw_combo, paytable))  # Wild 替換後的符號組合
        combo_breakdown.append(ComboResult(
            raw_combo=raw_combo,
            resolved_combo=resolved,
            multiplier=m,
            probability=prob,
            rtp_contribution=prob * m,  # 此組合對每線 RTP 的貢獻 = 機率 × 賠付倍率
        ))
    combo_breakdown.sort(key=lambda c: c.rtp_contribution, reverse=True)  # 依 RTP 貢獻由高到低排序

    return RTPResult(
        rtp_per_line=rtp_per_line,
        combo_breakdown=combo_breakdown,
    )


def print_rtp_report(result: RTPResult) -> None:  # 印出多線 RTP 報告
    """
    印出多線老虎機理論 RTP 與 House Edge。

    Args:
        result: calculate_rtp 的回傳值
    """
    print("=" * 60)
    print("  多線老虎機理論 RTP 計算報告")
    print("=" * 60)
    print(f"  {'每線平均 RTP':<30} {result.rtp_per_line * 100:>9.4f}%")
    print(f"  {'House Edge':<30} {(1 - result.rtp_per_line) * 100:>9.4f}%")
    print("=" * 60)


if __name__ == "__main__":
    result = calculate_rtp()
    print_rtp_report(result)
