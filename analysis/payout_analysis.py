"""
analysis/payout_analysis.py - 実際の払戻データを使ったROI分析

payoutsテーブルの実払戻金額を使って正確なROIを計算する。
対象: 単勝・複勝・馬連・ワイド
"""

import sqlite3
from dataclasses import dataclass, field
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
    (SELECT e5.odds FROM entries e5 WHERE e5.race_id = e.race_id AND e5.popularity = 1 LIMIT 1) AS pop1_odds
FROM entries e
JOIN races r ON e.race_id = r.race_id
LEFT JOIN results res ON e.race_id = res.race_id AND e.horse_id = res.horse_id
WHERE r.venue IN ('東京','中山','阪神','京都','中京','新潟','福島','小倉','札幌','函館')
ORDER BY e.race_id, e.popularity
"""

PAYOUT_SQL = """
SELECT race_id, bet_type, combination, payout
FROM payouts
WHERE bet_type IN ('単勝', '複勝', '馬連', 'ワイド')
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


def fetch_data(conn: sqlite3.Connection):
    rows = []
    for r in conn.execute(FETCH_SQL).fetchall():
        rows.append(Row(
            race_id=r[0], venue=r[1], course_type=r[2] or "",
            distance=r[3] or 0, date=r[4], horse_id=r[5],
            popularity=r[6] or 99, odds=r[7],
            horse_weight=r[8], horse_weight_diff=r[9],
            horse_number=r[10], finish_position=r[11],
            headcount=r[12] or 0, pop1_odds=r[13],
        ))

    # 払戻データをrace_id→{bet_type→{combo→payout}}で引けるように整理
    payouts: dict[str, dict[str, dict[str, int]]] = {}
    for race_id, bet_type, combo, payout in conn.execute(PAYOUT_SQL).fetchall():
        payouts.setdefault(race_id, {}).setdefault(bet_type, {})[combo] = payout

    return rows, payouts


# ---------------------------------------------------------------------------
# シグナル定義
# ---------------------------------------------------------------------------

SIGNALS = {
    "1番人気":              lambda r: r.popularity == 1,
    "2番人気":              lambda r: r.popularity == 2,
    "3番人気":              lambda r: r.popularity == 3,
    "4-6番人気":            lambda r: 4 <= r.popularity <= 6,
    "7-9番人気":            lambda r: 7 <= r.popularity <= 9,
    "10番人気以上":          lambda r: r.popularity >= 10,
    "4-6人気x少頭数(<=12)":  lambda r: 4 <= r.popularity <= 6 and r.headcount <= 12,
    "7-9人気x少頭数(<=12)":  lambda r: 7 <= r.popularity <= 9 and r.headcount <= 12,
    "4-6人気x多頭数(>=13)":  lambda r: 4 <= r.popularity <= 6 and r.headcount >= 13,
    "7-9人気x多頭数(>=13)":  lambda r: 7 <= r.popularity <= 9 and r.headcount >= 13,
    "4-6人気x芝":            lambda r: 4 <= r.popularity <= 6 and "芝" in r.course_type,
    "4-6人気xダート":         lambda r: 4 <= r.popularity <= 6 and "ダ" in r.course_type,
    "7-9人気x芝":            lambda r: 7 <= r.popularity <= 9 and "芝" in r.course_type,
    "7-9人気xダート":         lambda r: 7 <= r.popularity <= 9 and "ダ" in r.course_type,
    "4-9人気x少頭数x芝":     lambda r: 4 <= r.popularity <= 9 and r.headcount <= 12 and "芝" in r.course_type,
    "4-9人気x少頭数xダート":  lambda r: 4 <= r.popularity <= 9 and r.headcount <= 12 and "ダ" in r.course_type,
    "4-9人気x少頭数x体重減":  lambda r: 4 <= r.popularity <= 9 and r.headcount <= 12 and r.horse_weight_diff is not None and r.horse_weight_diff < 0,
    "4-6人気x芝x長距離":     lambda r: 4 <= r.popularity <= 6 and "芝" in r.course_type and r.distance >= 2200,
    "7-9人気xダートx中距離":  lambda r: 7 <= r.popularity <= 9 and "ダ" in r.course_type and 1400 <= r.distance <= 2200,
    "4-6人気x少頭数x芝":     lambda r: 4 <= r.popularity <= 6 and r.headcount <= 12 and "芝" in r.course_type,
    "4-6人気x少頭数xダート":  lambda r: 4 <= r.popularity <= 6 and r.headcount <= 12 and "ダ" in r.course_type,
}


# ---------------------------------------------------------------------------
# 集計クラス
# ---------------------------------------------------------------------------

@dataclass
class SignalStat:
    name: str
    bets: int = 0
    # 単勝
    tansho_hits: int = 0
    tansho_ret: float = 0.0
    # 複勝
    fukusho_hits: int = 0
    fukusho_ret: float = 0.0
    # 馬連（1着または2着の場合、相手馬との馬連払戻を計上）
    umaren_hits: int = 0
    umaren_ret: float = 0.0

    @property
    def tansho_roi(self): return self.tansho_ret / self.bets * 100 if self.bets else 0
    @property
    def fukusho_roi(self): return self.fukusho_ret / self.bets * 100 if self.bets else 0
    @property
    def umaren_roi(self): return self.umaren_ret / self.bets * 100 if self.bets else 0
    @property
    def tansho_rate(self): return self.tansho_hits / self.bets * 100 if self.bets else 0
    @property
    def fukusho_rate(self): return self.fukusho_hits / self.bets * 100 if self.bets else 0


def _combo_key(a: int, b: int) -> str:
    lo, hi = min(a, b), max(a, b)
    return f"{lo}-{hi}"


def run_payout_analysis(conn: sqlite3.Connection) -> list[SignalStat]:
    rows, payouts = fetch_data(conn)

    # race_id → horse_number → Row のマップ（馬連計算用）
    race_map: dict[str, dict[int, Row]] = {}
    for row in rows:
        race_map.setdefault(row.race_id, {})[row.horse_number] = row

    stats = {name: SignalStat(name=name) for name in SIGNALS}

    for row in rows:
        if row.finish_position is None:
            continue

        race_payouts = payouts.get(row.race_id, {})
        tansho_map  = race_payouts.get("単勝", {})
        fukusho_map = race_payouts.get("複勝", {})
        umaren_map  = race_payouts.get("馬連", {})

        for name, fn in SIGNALS.items():
            if not fn(row):
                continue
            st = stats[name]
            st.bets += 1

            num_str = str(row.horse_number)

            # 単勝
            if row.finish_position == 1:
                payout = tansho_map.get(num_str, 0)
                if payout:
                    st.tansho_hits += 1
                    st.tansho_ret += payout / 100

            # 複勝
            if row.finish_position <= 3:
                payout = fukusho_map.get(num_str, 0)
                if payout:
                    st.fukusho_hits += 1
                    st.fukusho_ret += payout / 100

            # 馬連: 1着か2着なら相手との馬連を計上
            if row.finish_position in (1, 2):
                partner_pos = 2 if row.finish_position == 1 else 1
                partner = next(
                    (r for r in race_map.get(row.race_id, {}).values()
                     if r.finish_position == partner_pos),
                    None
                )
                if partner:
                    key = _combo_key(row.horse_number, partner.horse_number)
                    payout = umaren_map.get(key, 0)
                    if payout:
                        st.umaren_hits += 1
                        st.umaren_ret += payout / 100

    return list(stats.values())


# ---------------------------------------------------------------------------
# 表示
# ---------------------------------------------------------------------------

def print_payout_analysis(results: list[SignalStat]) -> None:
    print("\n" + "=" * 80)
    print("★ 実払戻データによるROI分析")
    print("  (payoutsテーブルの実際の払戻金額を使用)")
    print("=" * 80)
    print(f"{'シグナル':<26} {'賭数':>6}  {'単勝率':>6} {'単勝ROI':>8}  {'複勝率':>6} {'複勝ROI':>8}  {'馬連ROI':>8}")
    print("-" * 80)

    for st in sorted(results, key=lambda x: x.fukusho_roi, reverse=True):
        if st.bets < 200:
            continue
        best = max(st.tansho_roi, st.fukusho_roi, st.umaren_roi)
        m = " ★★" if best >= 120 else " ★" if best >= 110 else " △" if best >= 100 else ""
        print(
            f"{st.name:<26} {st.bets:>6}"
            f"  {st.tansho_rate:>5.1f}% {st.tansho_roi:>7.1f}%"
            f"  {st.fukusho_rate:>5.1f}% {st.fukusho_roi:>7.1f}%"
            f"  {st.umaren_roi:>7.1f}%{m}"
        )

    print("=" * 80)
    print("基準: 単勝・複勝・馬連の控除後理論値は約75-80%。100%超=プラス収支")
    print()
