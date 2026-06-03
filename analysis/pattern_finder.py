"""
analysis/pattern_finder.py - 回収率パターン分析

DBの全データを様々な切り口で分析し、
統計的にプラスになるパターンを洗い出す。
"""

import sqlite3
from dataclasses import dataclass


BET = 100  # 1点あたりの賭け金


@dataclass
class Pattern:
    name: str
    bets: int
    hits_win: int      # 単勝的中
    hits_place: int    # 複勝的中（3着以内）
    payout_win: float
    payout_place: float

    @property
    def win_rate(self):
        return self.hits_win / self.bets * 100 if self.bets else 0

    @property
    def place_rate(self):
        return self.hits_place / self.bets * 100 if self.bets else 0

    @property
    def win_roi(self):
        return self.payout_win / (self.bets * BET) * 100 if self.bets else 0

    @property
    def place_roi(self):
        return self.payout_place / (self.bets * BET) * 100 if self.bets else 0


def fetch_all(conn: sqlite3.Connection):
    """全出走データを取得する。"""
    return conn.execute("""
        SELECT
            r.race_id,
            r.date,
            r.venue,
            r.course_type,
            r.distance,
            r.track_condition,
            r.race_name,
            e.horse_id,
            e.horse_number,
            e.frame_number,
            e.odds,
            e.popularity,
            e.weight_carried,
            e.horse_weight,
            e.horse_weight_diff,
            e.jockey_name,
            res.finish_position
        FROM entries e
        JOIN races r ON e.race_id = r.race_id
        LEFT JOIN results res ON e.race_id = res.race_id AND e.horse_id = res.horse_id
        WHERE r.venue IN (
            '東京','中山','阪神','京都','中京',
            '新潟','福島','小倉','札幌','函館'
        )
        AND e.odds IS NOT NULL
        AND e.popularity IS NOT NULL
    """).fetchall()


def headcount_map(conn: sqlite3.Connection) -> dict:
    """レースごとの出走頭数を返す。"""
    rows = conn.execute("""
        SELECT race_id, COUNT(*) FROM entries GROUP BY race_id
    """).fetchall()
    return {r[0]: r[1] for r in rows}


def place_odds_estimate(win_odds: float) -> float:
    """単勝オッズから複勝払戻を推定（簡易）。"""
    if win_odds <= 2.0:
        return win_odds * 0.6 * BET
    elif win_odds <= 5.0:
        return win_odds * 0.5 * BET
    elif win_odds <= 10.0:
        return win_odds * 0.4 * BET
    elif win_odds <= 30.0:
        return win_odds * 0.3 * BET
    else:
        return min(win_odds * 0.25 * BET, 5000)


def analyze(rows, headcounts, label_fn, filter_fn=None) -> dict[str, Pattern]:
    """汎用パターン集計。label_fnで分類キーを返す。"""
    patterns: dict[str, Pattern] = {}
    for row in rows:
        if filter_fn and not filter_fn(row):
            continue
        label = label_fn(row, headcounts)
        if label is None:
            continue
        if label not in patterns:
            patterns[label] = Pattern(label, 0, 0, 0, 0.0, 0.0)
        p = patterns[label]
        p.bets += 1
        pos = row[16]  # finish_position
        odds = row[10]
        if pos == 1:
            p.hits_win += 1
            p.hits_place += 1
            p.payout_win += odds * BET
            p.payout_place += place_odds_estimate(odds)
        elif pos in (2, 3):
            p.hits_place += 1
            p.payout_place += place_odds_estimate(odds)
    return patterns


def print_patterns(patterns: dict[str, Pattern], sort_by="place_roi", min_bets=30, min_roi=100.0):
    """結果を回収率順に表示。"""
    items = [p for p in patterns.values() if p.bets >= min_bets]
    items.sort(key=lambda x: getattr(x, sort_by), reverse=True)

    print(f"{'パターン':<35} {'件数':>5} {'単勝率':>7} {'単勝ROI':>8} {'複勝率':>7} {'複勝ROI':>8}")
    print("-" * 80)
    for p in items:
        marker = "★" if p.place_roi >= 120 else ("△" if p.place_roi >= 100 else "  ")
        print(f"{marker}{p.name:<33} {p.bets:>5} {p.win_rate:>6.1f}% {p.win_roi:>7.1f}% {p.place_rate:>6.1f}% {p.place_roi:>7.1f}%")


def run_all(conn: sqlite3.Connection):
    print("データ読み込み中...")
    rows = fetch_all(conn)
    headcounts = headcount_map(conn)
    print(f"総データ件数: {len(rows):,}")

    # ヘルパー関数
    def popularity(row): return row[11] or 99
    def odds(row): return row[10] or 0
    def pos(row): return row[16]
    def venue(row): return row[2]
    def course(row): return row[3]
    def distance(row): return row[4] or 0
    def track(row): return row[5] or ""
    def race_name(row): return row[6] or ""
    def frame(row): return row[9] or 0
    def weight_diff(row): return row[14]
    def jockey(row): return row[15] or ""
    def carried(row): return row[12] or 0
    def headcount(row, hc): return hc.get(row[0], 0)

    def dist_band(d):
        if d <= 1400: return "短距離(〜1400)"
        elif d <= 1800: return "マイル(1401-1800)"
        elif d <= 2200: return "中距離(1801-2200)"
        else: return "長距離(2201〜)"

    def pop_band(p):
        if p <= 3: return "1〜3番人気"
        elif p <= 6: return "4〜6番人気"
        elif p <= 9: return "7〜9番人気"
        else: return "10番人気以下"

    def odds_band(o):
        if o < 3: return "単勝1〜3倍"
        elif o < 6: return "単勝3〜6倍"
        elif o < 10: return "単勝6〜10倍"
        elif o < 20: return "単勝10〜20倍"
        elif o < 50: return "単勝20〜50倍"
        else: return "単勝50倍以上"

    def frame_band(f):
        if f <= 2: return "1〜2枠(内)"
        elif f <= 4: return "3〜4枠"
        elif f <= 6: return "5〜6枠"
        else: return "7〜8枠(外)"

    def head_band(h):
        if h <= 12: return "少頭数(〜12頭)"
        elif h <= 15: return "中頭数(13〜15頭)"
        else: return "多頭数(16頭以上)"

    def month(row): return row[1][5:7] + "月" if row[1] else ""

    def class_band(name):
        if "新馬" in name or "未勝利" in name: return None
        if "オープン" in name or "OP" in name: return "オープン"
        if "3勝" in name or "1600万" in name: return "3勝クラス"
        if "2勝" in name or "1000万" in name: return "2勝クラス"
        if "1勝" in name or "500万" in name: return "1勝クラス"
        if "重賞" in name or "GI" in name or "GII" in name or "GIII" in name: return "重賞"
        return "その他"

    # =========================================================
    # 1. 人気帯別
    # =========================================================
    print("\n" + "=" * 80)
    print("【1】人気帯別")
    print("=" * 80)
    p = analyze(rows, headcounts, lambda r, h: pop_band(popularity(r)))
    print_patterns(p, min_bets=50)

    # =========================================================
    # 2. オッズ帯別
    # =========================================================
    print("\n" + "=" * 80)
    print("【2】オッズ帯別")
    print("=" * 80)
    p = analyze(rows, headcounts, lambda r, h: odds_band(odds(r)))
    print_patterns(p, min_bets=50)

    # =========================================================
    # 3. 会場別
    # =========================================================
    print("\n" + "=" * 80)
    print("【3】会場別（複勝ROI順）")
    print("=" * 80)
    p = analyze(rows, headcounts, lambda r, h: venue(r))
    print_patterns(p, min_bets=50)

    # =========================================================
    # 4. コース別
    # =========================================================
    print("\n" + "=" * 80)
    print("【4】コース別（芝/ダート）")
    print("=" * 80)
    p = analyze(rows, headcounts, lambda r, h: course(r))
    print_patterns(p, min_bets=50)

    # =========================================================
    # 5. 距離帯別
    # =========================================================
    print("\n" + "=" * 80)
    print("【5】距離帯別")
    print("=" * 80)
    p = analyze(rows, headcounts, lambda r, h: dist_band(distance(r)))
    print_patterns(p, min_bets=50)

    # =========================================================
    # 6. 馬場状態別
    # =========================================================
    print("\n" + "=" * 80)
    print("【6】馬場状態別")
    print("=" * 80)
    p = analyze(rows, headcounts, lambda r, h: track(r) or "不明")
    print_patterns(p, min_bets=50)

    # =========================================================
    # 7. 枠番別
    # =========================================================
    print("\n" + "=" * 80)
    print("【7】枠番別")
    print("=" * 80)
    p = analyze(rows, headcounts, lambda r, h: frame_band(frame(r)))
    print_patterns(p, min_bets=50)

    # =========================================================
    # 8. 頭数別
    # =========================================================
    print("\n" + "=" * 80)
    print("【8】出走頭数別")
    print("=" * 80)
    p = analyze(rows, headcounts, lambda r, h: head_band(headcount(r, h)))
    print_patterns(p, min_bets=50)

    # =========================================================
    # 9. 馬体重増減別
    # =========================================================
    print("\n" + "=" * 80)
    print("【9】馬体重増減別")
    print("=" * 80)
    def weight_band(r, h):
        d = weight_diff(r)
        if d is None: return None
        if d <= -10: return "大幅減(-10kg以下)"
        elif d < -4: return "減少(-5〜-9kg)"
        elif d <= 4: return "維持(±4kg以内)"
        elif d < 10: return "増加(+5〜+9kg)"
        else: return "大幅増(+10kg以上)"
    p = analyze(rows, headcounts, weight_band)
    print_patterns(p, min_bets=50)

    # =========================================================
    # 10. 斤量別
    # =========================================================
    print("\n" + "=" * 80)
    print("【10】斤量別")
    print("=" * 80)
    def carried_band(r, h):
        c = carried(r)
        if c <= 0: return None
        if c <= 52: return "軽量(〜52kg)"
        elif c <= 54: return "54kg"
        elif c <= 56: return "56kg"
        elif c <= 57: return "57kg"
        else: return "重量(58kg以上)"
    p = analyze(rows, headcounts, carried_band)
    print_patterns(p, min_bets=50)

    # =========================================================
    # 11. 月別
    # =========================================================
    print("\n" + "=" * 80)
    print("【11】月別")
    print("=" * 80)
    p = analyze(rows, headcounts, lambda r, h: month(r))
    print_patterns(p, min_bets=50)

    # =========================================================
    # 12. 会場×コース
    # =========================================================
    print("\n" + "=" * 80)
    print("【12】会場×コース")
    print("=" * 80)
    p = analyze(rows, headcounts, lambda r, h: f"{venue(r)}×{course(r)}")
    print_patterns(p, min_bets=30)

    # =========================================================
    # 13. 人気帯×コース
    # =========================================================
    print("\n" + "=" * 80)
    print("【13】人気帯×コース")
    print("=" * 80)
    p = analyze(rows, headcounts, lambda r, h: f"{pop_band(popularity(r))}×{course(r)}")
    print_patterns(p, min_bets=50)

    # =========================================================
    # 14. 人気帯×距離帯
    # =========================================================
    print("\n" + "=" * 80)
    print("【14】人気帯×距離帯")
    print("=" * 80)
    p = analyze(rows, headcounts, lambda r, h: f"{pop_band(popularity(r))}×{dist_band(distance(r))}")
    print_patterns(p, min_bets=30)

    # =========================================================
    # 15. 人気帯×馬場
    # =========================================================
    print("\n" + "=" * 80)
    print("【15】人気帯×馬場状態")
    print("=" * 80)
    p = analyze(rows, headcounts, lambda r, h: f"{pop_band(popularity(r))}×{track(r) or '不明'}")
    print_patterns(p, min_bets=30)

    # =========================================================
    # 16. 人気帯×頭数
    # =========================================================
    print("\n" + "=" * 80)
    print("【16】人気帯×出走頭数")
    print("=" * 80)
    p = analyze(rows, headcounts, lambda r, h: f"{pop_band(popularity(r))}×{head_band(headcount(r, h))}")
    print_patterns(p, min_bets=30)

    # =========================================================
    # 17. 人気帯×枠番
    # =========================================================
    print("\n" + "=" * 80)
    print("【17】人気帯×枠番")
    print("=" * 80)
    p = analyze(rows, headcounts, lambda r, h: f"{pop_band(popularity(r))}×{frame_band(frame(r))}")
    print_patterns(p, min_bets=30)

    # =========================================================
    # 18. コース×距離帯×馬場
    # =========================================================
    print("\n" + "=" * 80)
    print("【18】コース×距離帯×馬場（3重複合）")
    print("=" * 80)
    p = analyze(rows, headcounts, lambda r, h: f"{course(r)}×{dist_band(distance(r))}×{track(r) or '不明'}")
    print_patterns(p, min_bets=30)

    # =========================================================
    # 19. 人気帯×会場（中穴が出やすい会場）
    # =========================================================
    print("\n" + "=" * 80)
    print("【19】中穴(5〜9番人気)×会場")
    print("=" * 80)
    p = analyze(rows, headcounts,
        lambda r, h: venue(r),
        filter_fn=lambda r: 5 <= popularity(r) <= 9
    )
    print_patterns(p, min_bets=30)

    # =========================================================
    # 20. 断然人気（単勝1.5倍以下）の信頼度
    # =========================================================
    print("\n" + "=" * 80)
    print("【20】断然人気（単勝1.5倍以下）の信頼度")
    print("=" * 80)
    p = analyze(rows, headcounts,
        lambda r, h: "断然人気(1.5倍以下)",
        filter_fn=lambda r: odds(r) <= 1.5 and popularity(r) == 1
    )
    print_patterns(p, min_bets=10)

    # =========================================================
    # 21. S6相当（多頭数×中穴）
    # =========================================================
    print("\n" + "=" * 80)
    print("【21】S6相当：16頭以上×5〜9番人気")
    print("=" * 80)
    p = analyze(rows, headcounts,
        lambda r, h: f"{course(r)}×{dist_band(distance(r))}",
        filter_fn=lambda r: headcount(r, headcounts) >= 16 and 5 <= popularity(r) <= 9
    )
    print_patterns(p, min_bets=20)

    # =========================================================
    # 22. 重・不良馬場×人気帯
    # =========================================================
    print("\n" + "=" * 80)
    print("【22】重・不良馬場×人気帯")
    print("=" * 80)
    p = analyze(rows, headcounts,
        lambda r, h: pop_band(popularity(r)),
        filter_fn=lambda r: track(r) in ("重", "不良")
    )
    print_patterns(p, min_bets=20)

    # =========================================================
    # 23. 騎手別回収率（上位・下位）
    # =========================================================
    print("\n" + "=" * 80)
    print("【23】騎手別複勝ROI（50件以上）")
    print("=" * 80)
    p = analyze(rows, headcounts, lambda r, h: jockey(r))
    print_patterns(p, min_bets=50)

    # =========================================================
    # 24. 馬体重増減×人気帯
    # =========================================================
    print("\n" + "=" * 80)
    print("【24】馬体重増減×人気帯")
    print("=" * 80)
    def wb_pop(r, h):
        d = weight_diff(r)
        if d is None: return None
        wb = "大幅減" if d <= -10 else ("減少" if d < -4 else ("維持" if d <= 4 else ("増加" if d < 10 else "大幅増")))
        return f"{wb}×{pop_band(popularity(r))}"
    p = analyze(rows, headcounts, wb_pop)
    print_patterns(p, min_bets=20)

    # =========================================================
    # 25. 人気帯×コース×距離（3重）
    # =========================================================
    print("\n" + "=" * 80)
    print("【25】人気帯×コース×距離帯（3重複合）")
    print("=" * 80)
    p = analyze(rows, headcounts,
        lambda r, h: f"{pop_band(popularity(r))}×{course(r)}×{dist_band(distance(r))}"
    )
    print_patterns(p, min_bets=20)

    print("\n\n★=複勝ROI120%以上  △=複勝ROI100%以上（統計的プラス）")
    print("※複勝払戻は単勝オッズからの推定値")
