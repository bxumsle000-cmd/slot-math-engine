"""
paytable.py - 賠付規則資料結構與符號解析工具

定義付線賠付規則的資料型別（PaylineEntry）、Wild 替換邏輯，
以及多線賠付表（PAYTABLE）。
供多線計算器（core/calculator.py）與多線模擬引擎（simulator/engine.py）共用。
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class PaylineEntry:
    """
    一條付線賠付規則。

    Attributes:
        symbol_name: 目標符號名稱，例如 "Seven"、"BAR"
        required_count: 需要幾個相同符號（2 = 前兩軸相同，3 = 三軸全中）
        multiplier: 中獎賠付倍率（押 1 元拿回幾元）
    """
    symbol_name: str    # 目標符號名稱，例如 "Seven"、"BAR"
    required_count: int  # 需要幾個左起連線（3 = 前三軸全中，4 = 前四軸，5 = 全線全中）
    multiplier: int      # 中獎賠付倍率（押 1 元拿回幾元）


def _find_matching_rule(  # 查找命中的賠付規則（左起連線，泛用任意符號數）
    combo: tuple,
    paytable: list[PaylineEntry],
) -> Optional[PaylineEntry]:
    """
    對一個不含 Wild 的符號組合，查找最高命中的賠付規則。

    左起連線規則：前 required_count 個符號必須完全相同。
    例：5 軸組合 (A,A,A,B,B) 命中 3-of-a-kind；(A,A,A,A,B) 命中 4-of-a-kind。
    賠付表已按倍率由高到低排序，第一個命中即為最高獎。

    Args:
        combo: 無 Wild 的符號組合，長度任意（2、3、4、5 軸皆可）
        paytable: 賠付規則列表（已按倍率由高到低排序）

    Returns:
        命中的賠付規則；未中獎回傳 None
    """
    for rule in paytable:
        n = rule.required_count  # 需要左起幾個符號相同才算中獎
        if len(combo) >= n and all(s == rule.symbol_name for s in combo[:n]):  # 左起 n 個全等
            return rule

    return None


def resolve_wild(  # Wild 替換為最佳符號
    combo: tuple,
    paytable: list[PaylineEntry],
) -> tuple:
    """
    將組合中的 Wild 替換成最有利的普通符號。

    策略：嘗試賠付表中每個規則的目標符號，取能湊出最高倍率的替換方案。
    若組合中沒有 Wild，直接原樣回傳。

    Args:
        combo: 符號的原始組合（可能含 Wild），長度任意
        paytable: 賠付規則列表（已按倍率由高到低排序）

    Returns:
        Wild 替換後的組合 tuple，例如 ("Seven", "Seven", "Seven", "Seven", "Seven")
    """
    if "Wild" not in combo:
        return combo  # 無 Wild，不需替換，直接回傳

    best_combo = combo
    best_multiplier = 0

    for rule in paytable:
        candidate = tuple(
            rule.symbol_name if s == "Wild" else s for s in combo  # 把每個 Wild 都換成此規則的目標符號
        )
        win = _find_matching_rule(candidate, paytable)
        if win is not None and win.multiplier > best_multiplier:  # 取倍率最高的替換方案
            best_multiplier = win.multiplier
            best_combo = candidate

    return best_combo


# ── 多線賠付表（3/4/5-of-a-kind，按倍率由高到低排列）────────────────────────────
# 左起連線：前 N 個符號完全相同即中獎，Blank 無賠付規則。
# 倍率由高到低排列確保 _find_matching_rule 第一命中即為最佳獎項。
PAYTABLE: list[PaylineEntry] = [
    PaylineEntry(symbol_name="Seven",  required_count=5, multiplier=500),  # 五連 Seven：頂獎
    PaylineEntry(symbol_name="Seven",  required_count=4, multiplier=100),  # 四連 Seven
    PaylineEntry(symbol_name="BAR",    required_count=5, multiplier=100),  # 五連 BAR
    PaylineEntry(symbol_name="Seven",  required_count=3, multiplier=50),   # 三連 Seven
    PaylineEntry(symbol_name="Cherry", required_count=5, multiplier=50),   # 五連 Cherry
    PaylineEntry(symbol_name="BAR",    required_count=4, multiplier=25),   # 四連 BAR
    PaylineEntry(symbol_name="Lemon",  required_count=5, multiplier=25),   # 五連 Lemon
    PaylineEntry(symbol_name="BAR",    required_count=3, multiplier=10),   # 三連 BAR
    PaylineEntry(symbol_name="Cherry", required_count=4, multiplier=10),   # 四連 Cherry
    PaylineEntry(symbol_name="Cherry", required_count=3, multiplier=5),    # 三連 Cherry
    PaylineEntry(symbol_name="Lemon",  required_count=4, multiplier=5),    # 四連 Lemon
    PaylineEntry(symbol_name="Lemon",  required_count=3, multiplier=3),    # 三連 Lemon：最低賠付
]
