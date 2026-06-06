"""
simulator/session_ml.py - 多線玩家旅程模擬模組（5×3 格式）

模擬多位玩家在多線老虎機上的完整遊戲旅程：
每局押 num_lines 個單位，中獎時收回 total_multiplier 個單位；
支援停損、停利、最大局數三種停止條件，以及 Free Spin 觸發機制。
"""

import random
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from core.markov import FreespinConfig
from core.reel import ReelStrip
from simulator.engine import spin, PAYLINES


@dataclass
class PlayerJourneyResult:
    """
    多位玩家旅程模擬的彙總結果。

    Attributes:
        num_players: 模擬玩家數
        starting_balance: 起始餘額（單位：單線押注額）
        stop_loss: 停損線（餘額低於此值即停止）
        stop_win: 停利線（餘額高於此值即停止）
        max_spins: 每位玩家最多玩幾局
        num_lines: 每局押注的付線數
        balance_histories: 各玩家的餘額走勢，balance_histories[i][j] = 第 i 位玩家第 j 局後的餘額
        final_balances: 各玩家最終餘額
        spin_counts: 各玩家實際玩了幾局
        bust_count: 觸停損或餘額不足以下注的玩家數（爆倉）
        win_count: 觸停利的玩家數
        max_count: 達到最大局數仍未停止的玩家數
        theoretical_rtp: 理論每線 RTP（供對照參考）
    """
    num_players: int                       # 模擬玩家數
    starting_balance: float                # 起始餘額（單位：單線押注額）
    stop_loss: float                       # 停損線
    stop_win: float                        # 停利線（餘額超過此值即停止）
    max_spins: int                         # 每位玩家最多局數
    num_lines: int                         # 每局押注付線數（= len(PAYLINES)）
    balance_histories: list[list[float]]   # balance_histories[玩家][局數] = 餘額快照
    final_balances: list[float]            # 各玩家最終餘額
    spin_counts: list[int]                 # 各玩家實際局數
    bust_count: int                        # 爆倉玩家數（觸停損或餘額不足以下注）
    win_count: int                         # 停利玩家數（觸停利）
    max_count: int                         # 到最大局數仍未停止的玩家數
    theoretical_rtp: float                 # 理論每線 RTP（每線標準化）
    fs_trigger_counts: list[int]           # 各玩家觸發 Free Spin 的次數（純底層模式全為 0）
    fs_retrigger_counts: list[int]         # 各玩家發生續場（retrigger）的次數（純底層模式全為 0）
    fs_earnings: list[float]               # 各玩家在 Free Spin 期間的總獲益（未觸發者為 0）


def simulate_player_journeys(  # 模擬多位玩家的完整遊戲旅程
    num_players: int = 100,
    starting_balance: float = 1000.0,
    stop_loss: float = 0.0,
    stop_win: float = 2000.0,
    max_spins: int = 500,
    fs_config: Optional[FreespinConfig] = None,
    seed: int | None = None,
    reel_strips: list[ReelStrip] | None = None,
) -> PlayerJourneyResult:
    """
    模擬多位玩家在多線老虎機上的遊戲旅程。

    押注模型：每局押滿所有付線，每線各 1 單位，每局成本 = num_lines 單位。
    中獎收益 = 本局 total_multiplier 單位；淨損益 = total_multiplier - num_lines。

    若傳入 fs_config，則以「每局真實 Scatter 結果」判定是否觸發 Free Spin
    （出現 ≥ FS_MIN_SCATTER 軸 Scatter 即觸發，與 engine.spin 一致），不讀 config.trigger_prob：
    FS 局不額外收費，贏分乘以 win_multiplier；FS 期間每局同樣以 Scatter 判定 retrigger（堆疊 +N 局）。

    Args:
        num_players: 模擬玩家數（越多統計越穩定）
        starting_balance: 起始餘額（單位：單線押注額）
        stop_loss: 停損線：餘額低於此值立即停止
        stop_win: 停利線：餘額高於此值立即停止
        max_spins: 每位玩家的最大局數上限
        fs_config: Free Spin 參數設定（None 表示純底層遊戲，不含 FS）；
                   僅 free_spin_count 與 win_multiplier 生效，trigger_prob／retrigger_prob 不採用
                   （觸發與續場改由真實 Scatter 結果衍生，與 calculate_freespin_rtp 一致）
        seed: 隨機種子（None = 每次不同，固定值讓結果可重現）
        reel_strips: 自訂捲軸帶列表（None 表示使用預設 REEL_STRIPS）

    Returns:
        PlayerJourneyResult，含各玩家餘額走勢與彙總統計
    """
    if seed is not None:
        random.seed(seed)

    num_lines = len(PAYLINES)  # 每局押注線數，動態讀取

    # 理論 RTP 只需計算一次，作為對照參考
    if fs_config is not None:
        from core.markov_freespin_rtp import calculate_freespin_rtp
        theoretical_rtp = calculate_freespin_rtp(fs_config, reel_strips=reel_strips).total_rtp  # FS 馬可夫理論值（含 FS 加成）
    else:
        from core.calculator import calculate_rtp
        theoretical_rtp = calculate_rtp(reel_strips=reel_strips).rtp_per_line  # 每線標準化理論值（無 FS）

    balance_histories: list[list[float]] = []
    final_balances: list[float] = []
    spin_counts: list[int] = []
    bust_count = 0   # 爆倉（觸停損）計數
    win_count = 0    # 停利計數
    max_count = 0    # 達最大局數計數
    fs_trigger_counts: list[int] = []    # 各玩家觸發 FS 次數
    fs_retrigger_counts: list[int] = []  # 各玩家發生續場次數
    fs_earnings_list: list[float] = []   # 各玩家 FS 期間總獲益

    for _ in range(num_players):
        balance = starting_balance  # 此玩家的當前餘額
        history = [balance]         # 記錄起始餘額（局數 0）
        fs_triggers = 0    # 此玩家累計觸發 FS 次數
        fs_retriggers = 0  # 此玩家累計續場次數
        fs_earned = 0.0    # 此玩家 FS 期間總獲益（所有 FS 局賠付合計）

        reached_max = True
        for spin_num in range(max_spins):
            # 餘額不足以押滿本局（< num_lines 單位）→ 視同破產，停止旅程
            # 真實機台押不起就不能玩；放在迴圈頂端先擋，避免餘額被押成負數
            if balance < num_lines:
                bust_count += 1
                reached_max = False
                break

            # ── 一局的收益計算 ──────────────────────────────────────────────
            if fs_config is None:
                # 純底層：直接 spin，不含 FS
                payout = float(spin(reel_strips).total_multiplier)  # 本局所有付線賠付總和
            else:
                # 含 FS：先執行基礎局，再以真實 Scatter 結果判斷是否觸發 FS
                outcome = spin(reel_strips)
                payout = float(outcome.total_multiplier)
                if outcome.free_spin_triggered:                  # 真實 Scatter ≥3 軸 → 觸發 FS
                    fs_triggers += 1                             # 記錄本次觸發
                    state = fs_config.free_spin_count           # 剩餘 FS 局數
                    while state > 0:
                        fs_outcome = spin(reel_strips)
                        fs_payout = fs_outcome.total_multiplier * fs_config.win_multiplier
                        fs_earned += fs_payout                   # 累計 FS 獲益（乘倍率後）
                        payout += fs_payout  # FS 局賠付乘倍率後累加到本局有效報酬
                        state -= 1  # 消耗一局
                        if fs_outcome.free_spin_triggered:       # FS 期間 Scatter retrigger
                            fs_retriggers += 1
                            state += fs_config.free_spin_count   # 追加局數

            # 押注模型：每線押 1 單位，押滿 num_lines 條，每局成本 = num_lines
            # payout 是倍率總和（已含 FS），直接對應「贏回幾單位」
            # 淨損益 = 贏回單位數 - 本局押出單位數
            balance += payout - num_lines  # 更新餘額

            history.append(balance)  # 記錄此局後的餘額快照

            # ── 停止條件判斷 ────────────────────────────────────────────────
            if balance <= stop_loss:
                bust_count += 1  # 觸停損（爆倉）
                reached_max = False
                break
            if balance >= stop_win:
                win_count += 1   # 觸停利
                reached_max = False
                break

        if reached_max:
            max_count += 1  # 跑完最大局數仍未停止

        balance_histories.append(history)
        final_balances.append(balance)
        spin_counts.append(len(history) - 1)  # -1 因為 history[0] 是起始值，不算局數
        fs_trigger_counts.append(fs_triggers)
        fs_retrigger_counts.append(fs_retriggers)
        fs_earnings_list.append(fs_earned)

    return PlayerJourneyResult(
        num_players=num_players,
        starting_balance=starting_balance,
        stop_loss=stop_loss,
        stop_win=stop_win,
        max_spins=max_spins,
        num_lines=num_lines,
        balance_histories=balance_histories,
        final_balances=final_balances,
        spin_counts=spin_counts,
        bust_count=bust_count,
        win_count=win_count,
        max_count=max_count,
        theoretical_rtp=theoretical_rtp,
        fs_trigger_counts=fs_trigger_counts,
        fs_retrigger_counts=fs_retrigger_counts,
        fs_earnings=fs_earnings_list,
    )
