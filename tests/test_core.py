"""
tests/test_core.py - core 層單元測試（多線 5×3 版）

針對 paytable.py、calculator.py、markov.py、markov_freespin_rtp.py
四個模組的關鍵函式，給定固定輸入，逐一驗證輸出是否符合預期。
"""

import pytest
import numpy as np

from core.paytable import PaylineEntry, _find_matching_rule, resolve_wild
from core.calculator import calculate_rtp, PAYTABLE
from core.markov import (
    FreespinConfig,
    build_transition_matrix,
    stationary_distribution,
)
from core.markov_freespin_rtp import calculate_freespin_rtp


# 本地測試用賠付表：包含 2-of-a-kind 與 3-of-a-kind 規則，供 calculator 測試使用
# 刻意不依賴任何模組常數，讓測試自包含且不受捲軸設定異動影響
_TEST_PAYTABLE: list[PaylineEntry] = [
    PaylineEntry(symbol_name="Seven",  required_count=3, multiplier=50),  # 最高獎
    PaylineEntry(symbol_name="BAR",    required_count=3, multiplier=10),  # 中等獎
    PaylineEntry(symbol_name="Cherry", required_count=3, multiplier=5),   # 低倍獎
    PaylineEntry(symbol_name="Lemon",  required_count=3, multiplier=3),   # 最低三連獎
    PaylineEntry(symbol_name="Seven",  required_count=2, multiplier=5),   # Seven 前兩軸中
    PaylineEntry(symbol_name="BAR",    required_count=2, multiplier=2),   # BAR 前兩軸中
    PaylineEntry(symbol_name="Cherry", required_count=2, multiplier=1),   # Cherry 前兩軸中
]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 一、paytable.py - PaylineEntry 測試
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestPaylineEntry:

    def test_建立PaylineEntry(self):  # 驗證 dataclass 欄位正確儲存
        """
        PaylineEntry 應正確儲存 symbol_name、required_count、multiplier。
        """
        entry = PaylineEntry(symbol_name="Seven", required_count=5, multiplier=500)
        assert entry.symbol_name == "Seven"
        assert entry.required_count == 5
        assert entry.multiplier == 500

    def test_多線賠付表無Wild(self):  # Wild 不應出現在賠付表，其邏輯由 calculator 層處理
        """
        PAYTABLE 中不應包含 Wild 符號規則。
        Why: Wild 的替換邏輯在 calculator 層處理，若賠付表有 Wild 條目，查找邏輯會混亂。
        """
        symbol_names = [e.symbol_name for e in PAYTABLE]
        assert "Wild" not in symbol_names

    def test_多線賠付表包含三四五連規則(self):  # 5×3 格式支援 3/4/5-of-a-kind
        """
        PAYTABLE 應同時包含 3、4、5-of-a-kind 規則（5 軸左起連線）。
        Why: 5 軸設計讓部分中獎（前 3 或前 4 軸）成為獨立獎項，豐富賠付結構。
        """
        required_counts = {e.required_count for e in PAYTABLE}
        assert required_counts == {3, 4, 5}

    def test_多線賠付表倍率降冪排列(self):  # calculator 查找時依序比對，排在越前面越優先命中最高獎
        """
        PAYTABLE 應按倍率由高到低排序。
        Why: _find_matching_rule 第一命中即回傳，確保取得最高獎而非最低獎。
        """
        multipliers = [e.multiplier for e in PAYTABLE]
        assert multipliers == sorted(multipliers, reverse=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 二、calculator.py - _find_matching_rule 測試
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestFindMatchingRule:

    def test_三連Seven命中最高獎(self):  # 三個 Seven = 最高獎 50 倍，最基本的正向驗證
        """
        (Seven, Seven, Seven) 應命中 Seven 3x 規則，倍率 50。
        """
        rule = _find_matching_rule(("Seven", "Seven", "Seven"), _TEST_PAYTABLE)
        assert rule is not None
        assert rule.symbol_name == "Seven"
        assert rule.required_count == 3
        assert rule.multiplier == 50

    def test_前兩軸相同命中二連獎(self):  # BAR BAR + 任何非BAR = 2-of-a-kind，倍率 2
        """
        (BAR, BAR, Cherry) 應命中 BAR 2x 規則，倍率 2。
        """
        rule = _find_matching_rule(("BAR", "BAR", "Cherry"), _TEST_PAYTABLE)
        assert rule is not None
        assert rule.symbol_name == "BAR"
        assert rule.required_count == 2

    def test_第一第三相同但第二不同不算中獎(self):  # 左起連線：第二軸斷鏈則後續不算
        """
        (Cherry, BAR, Cherry) 不符合任何規則，應回傳 None。
        Why: 本遊戲採左起連線，第二軸為 BAR 打斷 Cherry 序列。
        """
        rule = _find_matching_rule(("Cherry", "BAR", "Cherry"), _TEST_PAYTABLE)
        assert rule is None

    def test_Lemon無二連規則(self):  # _TEST_PAYTABLE 中 Lemon 只有 3x 規則
        """
        (Lemon, Lemon, Seven) 不應命中任何規則（Lemon 無 2x 設定）。
        """
        rule = _find_matching_rule(("Lemon", "Lemon", "Seven"), _TEST_PAYTABLE)
        assert rule is None

    def test_完全不同符號無獎(self):  # 三個都不同，既非 3x 也非 2x
        """
        (Seven, BAR, Cherry) 完全不符合任何規則，應回傳 None。
        """
        rule = _find_matching_rule(("Seven", "BAR", "Cherry"), _TEST_PAYTABLE)
        assert rule is None

    def test_三連Lemon命中低倍獎(self):  # Lemon 有 3x 規則，倍率 3
        """
        (Lemon, Lemon, Lemon) 應命中 Lemon 3x 規則，倍率 3。
        """
        rule = _find_matching_rule(("Lemon", "Lemon", "Lemon"), _TEST_PAYTABLE)
        assert rule is not None
        assert rule.symbol_name == "Lemon"
        assert rule.multiplier == 3

    def test_五連Seven命中最高獎(self):  # 5 軸全中 Seven → 500 倍頂獎
        """
        (Seven,Seven,Seven,Seven,Seven) 應命中 Seven 5x 規則，倍率 500。
        Why: 5 軸產線全中是頂獎，賠付表排在最前面，第一命中即回傳。
        """
        rule = _find_matching_rule(
            ("Seven", "Seven", "Seven", "Seven", "Seven"), PAYTABLE
        )
        assert rule is not None
        assert rule.required_count == 5
        assert rule.multiplier == 500

    def test_前四軸Seven命中四連獎(self):  # 前 4 軸 Seven、第 5 軸不同 → 4oak (100x)
        """
        (Seven,Seven,Seven,Seven,BAR) 應命中 Seven 4x 規則，倍率 100。
        Why: 左起前 4 個符號相同即命中 4-of-a-kind，第 5 軸不影響。
        """
        rule = _find_matching_rule(
            ("Seven", "Seven", "Seven", "Seven", "BAR"), PAYTABLE
        )
        assert rule is not None
        assert rule.required_count == 4
        assert rule.multiplier == 100


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 三、calculator.py - resolve_wild 測試
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestResolveWild:

    def test_無Wild原樣回傳(self):  # 沒有 Wild 就不用替換，直接回傳原組合
        """
        不含 Wild 的組合應原樣回傳，不做任何替換。
        """
        combo = ("Seven", "BAR", "Cherry")
        assert resolve_wild(combo, _TEST_PAYTABLE) == combo

    def test_Wild替換成最高獎(self):  # Wild + Seven + Seven → Seven 3x(50) 優於 Seven 2x(5)
        """
        (Wild, Seven, Seven) 應替換成 (Seven, Seven, Seven)，命中 50 倍三連。
        """
        result = resolve_wild(("Wild", "Seven", "Seven"), _TEST_PAYTABLE)
        assert result == ("Seven", "Seven", "Seven")

    def test_兩個Wild替換湊最佳三連(self):  # Wild Wild BAR → BAR BAR BAR = 10 倍，是最優解
        """
        (Wild, Wild, BAR) 應替換成 (BAR, BAR, BAR)，命中 BAR 3x 10 倍。
        Why: 兩個 Wild 都換成 BAR 可湊三連，比換成 Seven（無法與 BAR 配對）更高。
        """
        result = resolve_wild(("Wild", "Wild", "BAR"), _TEST_PAYTABLE)
        assert result == ("BAR", "BAR", "BAR")

    def test_Wild湊Cherry三連(self):  # Wild + Cherry + Cherry → Cherry 3x 5 倍
        """
        (Wild, Cherry, Cherry) 應替換成 (Cherry, Cherry, Cherry)。
        """
        result = resolve_wild(("Wild", "Cherry", "Cherry"), _TEST_PAYTABLE)
        assert result == ("Cherry", "Cherry", "Cherry")

    def test_Wild湊二連獎(self):  # Wild + Seven + Lemon → Seven Seven Lemon = Seven 2x(5)
        """
        (Wild, Seven, Lemon) Wild 替換成 Seven 可湊 Seven 2x（5 倍），是最優解。
        """
        result = resolve_wild(("Wild", "Seven", "Lemon"), _TEST_PAYTABLE)
        assert result == ("Seven", "Seven", "Lemon")

    def test_Wild無法湊獎以多線賠付表驗證(self):  # 5 軸：Wild + 四種不同符號，無法湊任何左起三連
        """
        (Wild, Seven, BAR, Cherry, Lemon) 在 PAYTABLE 中無法湊任何三連以上獎。
        Wild 僅在位置 0，其餘四軸各不相同，應回傳原始組合。
        """
        result = resolve_wild(("Wild", "Seven", "BAR", "Cherry", "Lemon"), PAYTABLE)
        assert result == ("Wild", "Seven", "BAR", "Cherry", "Lemon")

    def test_Wild湊五連獎(self):  # Wild + 4 個 Seven → 五連 Seven = 500 倍頂獎
        """
        (Wild, Seven, Seven, Seven, Seven) 應替換成五連 Seven，命中 500 倍頂獎。
        Why: Wild 在第一軸，其餘四軸全是 Seven → Wild 換 Seven → 5oak(500x)。
        """
        result = resolve_wild(
            ("Wild", "Seven", "Seven", "Seven", "Seven"), PAYTABLE
        )
        assert result == ("Seven", "Seven", "Seven", "Seven", "Seven")

    def test_Wild湊四連獎(self):  # Wild + 3 個 Seven + 1 個 BAR → 四連 Seven = 100 倍
        """
        (Wild, Seven, Seven, Seven, BAR) 應替換成四連 Seven（100 倍），而非三連（50 倍）。
        Why: Wild 在第一軸換成 Seven 後，前四軸全是 Seven → 4oak(100x) 優於 3oak(50x)。
        """
        result = resolve_wild(
            ("Wild", "Seven", "Seven", "Seven", "BAR"), PAYTABLE
        )
        assert result == ("Seven", "Seven", "Seven", "Seven", "BAR")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 四、calculator.py - calculate_rtp 測試
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestCalculateMultilineRtp:

    @pytest.fixture(autouse=True)
    def _result(self):  # 快取計算結果，避免每個測試重複枚舉
        """共用的多線 RTP 計算結果。"""
        self.result = calculate_rtp()

    def test_RTP落在合理區間(self):  # 多線 3/4/5-of-a-kind + Wild，RTP 應在 0~1 之間
        """
        多線理論 RTP 應大於 0 且小於 1.0。
        """
        assert 0.0 < self.result.rtp_per_line < 1.0

    def test_中獎組合機率皆合法(self):  # 每個組合的機率 = 各軸邊際機率之積，必在 (0,1]
        """
        所有中獎組合的出現機率應大於 0 且不超過 1。
        """
        assert all(0 < c.probability <= 1.0 for c in self.result.combo_breakdown)

    def test_中獎組合RTP貢獻加總等於每線RTP(self):  # combo_breakdown 以付線 0 為代表，各付線相同
        """
        combo_breakdown（付線 0 代表值）的 rtp_contribution 加總應等於 rtp_per_line。
        Why: 各捲軸行分佈相同（等機率停格），付線 0 的組合分佈與所有付線完全相同。
        """
        combo_sum = sum(c.rtp_contribution for c in self.result.combo_breakdown)
        assert abs(combo_sum - self.result.rtp_per_line) < 1e-10


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 五、markov.py - build_transition_matrix 測試
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.fixture
def default_config() -> FreespinConfig:  # 提供一組標準測試用 FS 設定，避免每個測試重複建立
    """標準測試用 Free Spin 設定（p=0.02, N=5, r=0.10, M=3）。"""
    return FreespinConfig(
        trigger_prob=0.02,
        free_spin_count=5,
        retrigger_prob=0.10,
        win_multiplier=3.0,
    )


class TestBuildTransitionMatrix:

    def test_為2x2巨觀矩陣(self, default_config):  # 新模型用 {一般, FS} 兩個巨觀狀態，矩陣固定 2×2
        """
        轉移矩陣形狀應為 (2, 2)，與 free_spin_count 無關。
        Why: 堆疊式 retrigger 讓剩餘局數無上限，改以 2 狀態巨觀鏈表示。
        """
        T = build_transition_matrix(default_config)
        assert T.shape == (2, 2)

    def test_每列機率加總為一(self, default_config):  # 馬可夫轉移矩陣的基本性質：每列代表從某狀態出發的所有可能轉移
        """
        轉移矩陣每一列（row）的機率加總必須等於 1.0。
        Why: 從任一狀態出發，必定轉移到某個狀態，機率和 = 1 是馬可夫矩陣的基本約束。
        """
        T = build_transition_matrix(default_config)
        row_sums = T.sum(axis=1)
        np.testing.assert_allclose(row_sums, 1.0, atol=1e-12)

    def test_一般狀態未觸發機率正確(self, default_config):  # T[0][0] = 1 - trigger_prob
        """
        T[0][0]（一般模式停留機率）應等於 1 - trigger_prob。
        """
        T = build_transition_matrix(default_config)
        expected = 1 - default_config.trigger_prob
        assert abs(T[0][0] - expected) < 1e-12

    def test_一般狀態觸發機率正確(self, default_config):  # T[0][1] = trigger_prob（一般 → FS）
        """
        T[0][1]（一般模式觸發 FS、進入 FS 巨觀狀態的機率）應等於 trigger_prob。
        """
        T = build_transition_matrix(default_config)
        expected = default_config.trigger_prob
        assert abs(T[0][1] - expected) < 1e-12

    def test_FS每局退出率正確(self, default_config):  # T[1][0] = q = (1 - N·r) / N
        """
        T[1][0]（FS 當局結束、回一般模式的機率）應等於 q = (1 - N·r) / N。
        Why: 堆疊式 retrigger 下，FS 平均局數為 N/(1-N·r)，其倒數即每局退出率 q。
        """
        T = build_transition_matrix(default_config)
        N = default_config.free_spin_count
        r = default_config.retrigger_prob
        expected_q = (1 - N * r) / N
        assert abs(T[1][0] - expected_q) < 1e-12
        assert abs(T[1][1] - (1 - expected_q)) < 1e-12  # FS 延續機率 = 1 - q

    def test_Nr超過一拋出例外(self):  # N·r ≥ 1 時 FS 期望局數發散，應拒絕
        """
        free_spin_count × retrigger_prob ≥ 1 時應拋出 ValueError。
        Why: 每局期望新增局數 ≥ 消耗局數，Free Spin 永不結束、RTP 無定義。
        """
        bad = FreespinConfig(trigger_prob=0.02, free_spin_count=10, retrigger_prob=0.2, win_multiplier=3.0)
        with pytest.raises(ValueError):
            build_transition_matrix(bad)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 六、markov.py - stationary_distribution 測試
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestStationaryDistribution:

    def test_穩態比例落在合法範圍(self, default_config):  # π_normal 是比例值，必定介於 0 到 1
        """
        pi_normal 應介於 0 和 1 之間（機率值的基本約束）。
        """
        pi = stationary_distribution(default_config)
        assert 0 < pi < 1

    def test_解析公式與手算一致(self, default_config):  # π₀ = (1-N·r) / ((1-N·r) + N×p)
        """
        stationary_distribution 的結果應與解析公式 (1-N·r)/((1-N·r)+N×p) 精確一致。
        Why: 堆疊式 retrigger 下，一次觸發期望 FS 局數 N/(1-N·r)，據此推得新穩態公式。
        """
        p = default_config.trigger_prob
        r = default_config.retrigger_prob
        N = default_config.free_spin_count

        expected = (1 - N * r) / ((1 - N * r) + N * p)  # 新模型一般模式穩態公式
        actual = stationary_distribution(default_config)
        assert abs(actual - expected) < 1e-12

    def test_觸發機率越高留在一般模式越少(self):  # trigger_prob ↑ → 更常進 FS → pi_normal ↓
        """
        trigger_prob 越高，玩家進入 FS 的頻率越高，一般模式的穩態比例應越低。
        """
        config_low_p  = FreespinConfig(trigger_prob=0.01, free_spin_count=5, retrigger_prob=0.0, win_multiplier=3.0)
        config_high_p = FreespinConfig(trigger_prob=0.10, free_spin_count=5, retrigger_prob=0.0, win_multiplier=3.0)

        pi_low  = stationary_distribution(config_low_p)
        pi_high = stationary_distribution(config_high_p)
        assert pi_low > pi_high


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 七、markov_freespin_rtp.py - calculate_freespin_rtp 測試
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestCalculateMultilineFreespinRtp:

    def test_Free_Spin讓RTP提升(self, default_config):  # win_multiplier=3 的 FS 一定讓整體 RTP > 基礎 RTP
        """
        win_multiplier > 1 的 Free Spin 應使整體 RTP 高於基礎多線每線 RTP。
        """
        result = calculate_freespin_rtp(default_config)
        assert result.total_rtp > result.base_rtp

    def test_FS貢獻等於總減基礎(self, default_config):  # freespin_contribution 應精確等於差值
        """
        freespin_contribution 應等於 total_rtp - base_rtp（欄位定義的一致性驗證）。
        """
        result = calculate_freespin_rtp(default_config)
        diff = result.total_rtp - result.base_rtp
        assert abs(result.freespin_contribution - diff) < 1e-12

    def test_穩態比例加總為一(self, default_config):  # pi_normal + pi_free = 1，是機率的基本要求
        """
        pi_normal + pi_free 應等於 1.0（兩個狀態互補）。
        """
        result = calculate_freespin_rtp(default_config)
        assert abs(result.pi_normal + result.pi_free - 1.0) < 1e-12

    def test_RTP落在合理範圍(self, default_config):  # 含 FS 的 RTP 應為正值且不超過 2 倍
        """
        含 Free Spin 的整體 RTP 應大於 0 且不超過 2.0（win_multiplier=3 帶來合理放大）。
        """
        result = calculate_freespin_rtp(default_config)
        assert 0.0 < result.total_rtp < 2.0

    def test_base_rtp與多線計算一致(self, default_config):  # base_rtp 應來自 calculate_rtp()
        """
        MarkovResult.base_rtp 應等於 calculate_rtp().rtp_per_line。
        Why: markov_freespin_rtp.py 從多線計算器取得 base_rtp，馬可夫公式在此基礎上放大。
        """
        result = calculate_freespin_rtp(default_config)
        ml_rtp = calculate_rtp()
        assert abs(result.base_rtp - ml_rtp.rtp_per_line) < 1e-10
