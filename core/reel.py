"""
reel.py - 多線捲軸模組（5×3 格式）

定義 5 軸 3 行老虎機的有序捲軸帶（Reel Strip）與付線（Payline）配置。
停轉後可見上中下 3 行，共 5 條捲軸，形成 3×5 可見方格。
"""

from dataclasses import dataclass, field
from itertools import chain, zip_longest

@dataclass
class ReelStrip:
    """
    有序捲軸帶，每個停格位置對應一個符號。

    Attributes:
        symbols: 捲軸帶停格序列，長度 = total_stops（本專案預設 40 格）。
                 索引即停格位置，symbols[i] 是停在第 i 格時的上排符號。
                 環狀結構：超出末尾自動繞回（ window() 的 % total_stops）。
                 例：symbols = ['Blank','Cherry','Lemon','BAR','Cherry', ...]
    """
    symbols: list[str] = field(default_factory=list)  # 捲軸帶停格序列（有序，長度 = 總停格數）

    @property
    def total_stops(self) -> int:  # 捲軸總停格數
        return len(self.symbols)

    def window(self, stop: int, rows: int = 3) -> list[str]:  # 取得可見視窗符號
        """
        捲軸停在 stop 格後，玩家從視窗看到的 rows 個符號（由上到下）。

        捲軸帶是環狀結構，同一條捲軸的上中下三行是連續相鄰格，
        stop 決定上排，stop+1 決定中排，stop+2 決定下排，三行連動不獨立。
        % total_stops 讓索引超出末尾時自動繞回開頭。

        五條捲軸各自獨立停轉（各有自己的 stop），結果互不影響。

        Args:
            stop: 停格位置索引（0-indexed），對應上排符號
            rows: 可見行數，預設 3

        Returns:
            長度為 rows 的符號列表（預設 3 格），依「上→中→下」排列。
            result[0] = symbols[stop % N]       ← 上排（玩家視窗第一行）
            result[1] = symbols[(stop+1) % N]   ← 中排（付線 1 主線位置）
            result[2] = symbols[(stop+2) % N]   ← 下排（玩家視窗最後一行）
            例：stop=5、symbols=[...,'Cherry','Lemon','BAR',...] → ['Cherry','Lemon','BAR']

        """
        return [self.symbols[(stop + i) % self.total_stops] for i in range(rows)]


def _build_strip(counts: dict[str, int]) -> "ReelStrip":  # 從符號計數建立捲軸帶
    """
    將 {符號: 格數} 展開為交錯排列的捲軸帶。

    用 zip_longest 讓各符號均勻散佈在捲軸上，
    避免同一符號連續堆疊，符合實體捲軸的排列慣例。

    例：{"A": 3, "B": 2, "C": 1} →
        zip_longest: [A,B,C], [A,B], [A]
        chain:        A B C A B A

    Args:
        counts: {符號名稱: 出現格數} 的字典

    Returns:
        ReelStrip，已依 zip_longest 交錯排列
    """
    buckets = [[sym] * cnt for sym, cnt in counts.items()]
    symbols = [s for s in chain.from_iterable(zip_longest(*buckets)) if s is not None]
    return ReelStrip(symbols=symbols)

# ── 捲軸帶設計：改格數即可調整機率，_build_strip 自動展開 ──────────────────────
REEL_CONFIG: dict[str, int] = {
    "Blank":   4,
    "Cherry":  11,
    "Lemon":   11,
    "BAR":     6,
    "Seven":   6,
    "Wild":    1,
    "Scatter": 1,
}

REEL_SLIDER_MAX: dict[str, int] = {  # Dashboard 滑桿上限，新增符號時同步加入
    "Blank":   30,
    "Cherry":  20,
    "Lemon":   20,
    "BAR":     20,
    "Seven":   20,
    "Wild":    10,
    "Scatter": 10,
}

REEL_1 = _build_strip(REEL_CONFIG)  # 捲軸 1（最左）
REEL_2 = _build_strip(REEL_CONFIG)  # 捲軸 2
REEL_3 = _build_strip(REEL_CONFIG)  # 捲軸 3（中央）
REEL_4 = _build_strip(REEL_CONFIG)  # 捲軸 4
REEL_5 = _build_strip(REEL_CONFIG)  # 捲軸 5（最右）

REEL_STRIPS: list[ReelStrip] = [REEL_1, REEL_2, REEL_3, REEL_4, REEL_5]  # 五條捲軸帶，索引 0–4
NUM_REELS: int = len(REEL_STRIPS)  # 捲軸數，由實際捲軸條帶數量決定，改捲軸數時自動更新

# ── 5 條付線定義（5×3 格式標準配置）────────────────────────────────────────────
# 每條付線是 (捲軸0行, 捲軸1行, 捲軸2行, 捲軸3行, 捲軸4行)
# 行索引：0 = 上排、1 = 中排、2 = 下排
PAYLINES: list[tuple[int, int, int, int, int]] = [
    (1, 1, 1, 1, 1),  # 付線 1：中排（主線）
    (0, 0, 0, 0, 0),  # 付線 2：上排
    (2, 2, 2, 2, 2),  # 付線 3：下排
    (0, 1, 2, 1, 0),  # 付線 4：V 形（中間最低）
    (2, 1, 0, 1, 2),  # 付線 5：倒 V 形（中間最高）
]

PAYLINE_NAMES: list[str] = [
    "中排", "上排", "下排",
    "V形", "倒V形",
]  # 付線顯示名稱，與 PAYLINES 索引一一對應


# 啟動方式：PYTHONPATH=. .venv/bin/python core/reel.py
if __name__ == "__main__":
    None