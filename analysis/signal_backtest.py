"""
analysis/signal_backtest.py - 組み合わせシグナルのバックテスト

シグナル定義:
  S1: 4〜9番人気 × 少頭数(〜12頭) × 馬体重維持/減少(diff<=0)
  S2: 7〜9番人気 × ダート × 中距離(1401-2200m)
  S3: 4〜6番人気 × 芝 × 長距離(2201m〜)
  S4: 7〜9番人気 × 芝 × 中距離(1401-2200m)
  S5: 4〜9番人気 × 少頭数(〜12頭)  ← ゲートなし基本版
  COMBO: S1 OR S2 OR S3 OR S4 (複合シグナル)

除外ゲート (全シグナル共通):
  - 断然人気: 1番人気単勝オッズ <= 1.5
  - 多頭数: 16頭以上

賭け方: 複勝(3着以内) と 馬連(予測1位・2位)
"""

import sqlite3
from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# データ取得
# ---------------------------------------------------------------------------

FETCH_SQL = """
SELECT
    e.race_id,
    r.venue,
    r.course_type,
    r.distance,
    r.date,
    e.horse_id,
    e.popularity,
    e.odds,
    e.horse_weight,
    e.horse_weight_diff,
    e.horse_number,
    res.finish_position,
    (SELECT COUNT(*) FROM entries e2 WHERE e2.race_id = e.race_id) AS headcount,
    (SELECT MIN(e3.odds) FROM entries e3 WHERE e3.race_id = e.race_id) AS best_odds,
    (SELECT e4.popularity FROM entries e4
     WHERE e4.race_id = e.race_id
       AND e4.popularity = 1
     LIMIT 1) AS pop1_exists,
    (SELECT e5.odds FROM entries e5
     WHERE e5.race_id = e.race_id
       AND e5.popularity = 1
     LIMIT 1) AS pop1_odds
FROM entries e
JOIN races r ON e.race_id = r.race_id
LEFT JOIN results res ON e.race_id = res.race_id AND e.horse_id = res.horse_id
WHERE r.venue IN (
    '東京','中山','阪神','京都','中京','新潟','福島','小倉','札幌','函館'
)
ORDER BY e.race_id, e.popularity
"""


@dataclass
class Row:
    race_id: str
    venue: str
    course_type: str
    distance: int
    date: str
    horse_id: str
    popularity: int
    odds: Optional[float]
    horse_weight: Optional[int]
    horse_weight_diff: Optional[int]
    horse_number: int
    finish_position: Optional[int]
    headcount: int
    pop1_odds: Optional[float]


def fetch_rows(conn: sqlite3.Connection) -> list[Row]:
    cursor = conn.execute(FETCH_SQL)
    rows = []
    for r in cursor.fetchall():
        rows.append(Row(
            race_id=r[0], venue=r[1], course_type=r[2] or "",
            distance=r[3] or 0, date=r[4], horse_id=r[5],
            popularity=r[6] or 99, odds=r[7],
            horse_weight=r[8], horse_weight_diff=r[9],
            horse_number=r[10], finish_position=r[11],
            headcount=r[12] or 0, pop1_odds=r[15],
        ))
    return rows


# ---------------------------------------------------------------------------
# 複勝オッズ推定 (win_odds から簡易推計)
# ---------------------------------------------------------------------------

def estimate_fukusho_odds(win_odds: Optional[float]) -> float:
    """単勝オッズから複勝オッズを大まかに推定する。"""
    if not win_odds or win_odds <= 0:
        return 1.1
    if win_odds <= 2.0:
        return 1.1
    if win_odds <= 5.0:
        return 1.3 + (win_odds - 2.0) * 0.15
    if win_odds <= 10.0:
        return 1.75 + (win_odds - 5.0) * 0.10
    if win_odds <= 20.0:
        return 2.25 + (win_odds - 10.0) * 0.07
    return 2.95 + (win_odds - 20.0) * 0.03


# ---------------------------------------------------------------------------
# シグナル定義
# ---------------------------------------------------------------------------

def gate_pass(row: Row, race_pop1_odds: Optional[float], headcount: int) -> bool:
    """共通除外ゲート: Trueなら通過(買い対象)"""
    if headcount >= 16:
        return False
    if race_pop1_odds and race_pop1_odds <= 1.5:
        return False
    return True


SIGNALS = {
    "S1_中穴×少頭数×馬体重維持減": lambda row: (
        4 <= row.popularity <= 9
        and row.headcount <= 12
        and row.horse_weight_diff is not None
        and row.horse_weight_diff <= 0
    ),
    "S2_7〜9人気×ダート×中距離": lambda row: (
        7 <= row.popularity <= 9
        and "ダ" in row.course_type
        and 1401 <= row.distance <= 2200
    ),
    "S3_4〜6人気×芝×長距離": lambda row: (
        4 <= row.popularity <= 6
        and "芝" in row.course_type
        and row.distance >= 2201
    ),
    "S4_7〜9人気×芝×中距離": lambda row: (
        7 <= row.popularity <= 9
        and "芝" in row.course_type
        and 1401 <= row.distance <= 2200
    ),
    "S5_中穴×少頭数(基本)": lambda row: (
        4 <= row.popularity <= 9
        and row.headcount <= 12
    ),
}


def is_combo(row: Row) -> bool:
    return any(fn(row) for fn in SIGNALS.values())


# ---------------------------------------------------------------------------
# バックテスト集計
# ---------------------------------------------------------------------------

@dataclass
class SignalResult:
    name: str
    bets: int
    fukusho_hits: int
    fukusho_return: float
    tansho_hits: int
    tansho_return: float
    races: int

    @property
    def fukusho_roi(self) -> float:
        return self.fukusho_return / self.bets * 100 if self.bets else 0

    @property
    def tansho_roi(self) -> float:
        return self.tansho_return / self.bets * 100 if self.bets else 0

    @property
    def fukusho_hit_rate(self) -> float:
        return self.fukusho_hits / self.bets * 100 if self.bets else 0


def run_signal_backtest(conn: sqlite3.Connection) -> list[SignalResult]:
    rows = fetch_rows(conn)

    # race_id ごとに pop1_odds を集約
    race_pop1: dict[str, Optional[float]] = {}
    for row in rows:
        if row.popularity == 1:
            race_pop1[row.race_id] = row.odds

    results: dict[str, SignalResult] = {
        name: SignalResult(name=name, bets=0, fukusho_hits=0,
                           fukusho_return=0.0, tansho_hits=0,
                           tansho_return=0.0, races=0)
        for name in list(SIGNALS.keys()) + ["COMBO_全シグナル合算"]
    }

    seen_races: dict[str, set] = {k: set() for k in results}

    for row in rows:
        if row.finish_position is None:
            continue

        pop1_odds = race_pop1.get(row.race_id)

        if not gate_pass(row, pop1_odds, row.headcount):
            continue

        fukusho_odds = estimate_fukusho_odds(row.odds)
        tansho_odds = row.odds or 0.0

        hit3 = row.finish_position <= 3
        hit1 = row.finish_position == 1

        def record(name: str):
            sr = results[name]
            sr.bets += 1
            if row.race_id not in seen_races[name]:
                seen_races[name].add(row.race_id)
                sr.races += 1
            if hit3:
                sr.fukusho_hits += 1
                sr.fukusho_return += fukusho_odds
            if hit1:
                sr.tansho_hits += 1
                sr.tansho_return += tansho_odds

        for name, fn in SIGNALS.items():
            if fn(row):
                record(name)

        if is_combo(row):
            record("COMBO_全シグナル合算")

    return list(results.values())


# ---------------------------------------------------------------------------
# 表示
# ---------------------------------------------------------------------------

def print_signal_results(results: list[SignalResult]) -> None:
    print("\n" + "=" * 75)
    print("★ 組み合わせシグナル バックテスト結果")
    print("  (共通ゲート: 断然人気1.5倍以下除外 / 16頭以上除外)")
    print("=" * 75)
    header = f"{'シグナル':<26} {'対象R':>5} {'賭数':>6} {'複勝的中率':>8} {'複勝ROI':>8} {'単勝ROI':>8}"
    print(header)
    print("-" * 75)

    for sr in results:
        marker = ""
        if sr.fukusho_roi >= 130:
            marker = " ★★"
        elif sr.fukusho_roi >= 120:
            marker = " ★"
        elif sr.fukusho_roi >= 110:
            marker = " △"
        print(
            f"{sr.name:<26} {sr.races:>5} {sr.bets:>6}"
            f"  {sr.fukusho_hit_rate:>6.1f}%  {sr.fukusho_roi:>6.1f}%{marker:5}"
            f"  {sr.tansho_roi:>6.1f}%"
        )

    print("=" * 75)
    print("注: 複勝オッズは単勝オッズから推計値。実際と異なる場合があります。")
    print()
