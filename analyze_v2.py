"""
analyze_v2.py - スタンドアロン分析スクリプト（依存なし）

使い方: python analyze_v2.py
DB: keiba.db (同フォルダ)
"""

import sqlite3
import sys
from collections import defaultdict

DB_PATH = "keiba.db"


def evaluate_signals(entry: dict, prev: dict) -> list:
    matched = []
    pop = entry.get('popularity') or 0
    course = entry.get('course_type', '')
    distance = entry.get('distance') or 0
    headcount = entry.get('headcount') or 0
    weight_diff = entry.get('horse_weight_diff')

    prev_pos = prev.get('prev_pos')
    prev_hc = prev.get('prev_hc') or 0
    prev_dist = prev.get('prev_dist') or 0
    prev_course = prev.get('prev_course', '')
    prev_pop = prev.get('prev_pop') or 0

    if pop >= 6 and prev_pos and prev_pos <= 3 and prev_course == course:
        matched.append('S1_前走好走同コース')
    if pop >= 6 and prev_hc >= 16 and 0 < headcount <= 12:
        matched.append('S2_大頭数→少頭数')
    if pop >= 6 and prev_pop <= 3 and prev_pos and prev_pos > 5:
        matched.append('S3_人気落ち巻返し')
    if pop >= 6 and course == 'ダート' and 0 < headcount <= 12 and prev_pos and prev_pos <= 5:
        matched.append('S4_少頭数ダート穴')
    if pop >= 6 and prev_dist > 0 and distance > 0 and (distance - prev_dist) <= -200 and prev_pos and prev_pos <= 3:
        matched.append('S5_短縮好走馬')
    if pop >= 9 and prev_pos and prev_pos <= 3 and abs(distance - prev_dist) <= 200:
        matched.append('S8_超穴前走好走')

    return matched


def run():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # データ件数確認
    cnt = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    hh = conn.execute("SELECT COUNT(*) FROM horse_histories").fetchone()[0]
    pay = conn.execute("SELECT COUNT(*) FROM payouts WHERE bet_type='複勝'").fetchone()[0]
    print(f"entries: {cnt}, horse_histories: {hh}, payouts複勝: {pay}")

    print("\n=== 前走データ結合テスト ===")
    test = conn.execute("""
        SELECT e.race_id, e.horse_id, e.popularity,
               p.finish_position AS prev_pos, p.headcount AS prev_hc
        FROM entries e
        JOIN races ra ON ra.race_id = e.race_id
        LEFT JOIN horse_histories p
            ON p.horse_id = e.horse_id
            AND p.race_date = (
                SELECT MAX(race_date) FROM horse_histories
                WHERE horse_id = e.horse_id AND race_date < ra.date
            )
        WHERE ra.date >= '2025-01-01'
          AND p.finish_position IS NOT NULL
        LIMIT 5
    """).fetchall()
    print(f"前走結合サンプル: {len(test)}件")
    for r in test:
        print(f"  pop={r['popularity']}, prev_pos={r['prev_pos']}, prev_hc={r['prev_hc']}")

    print("\n=== メイン分析（時間がかかります）===")
    query = """
        SELECT
            e.race_id, e.horse_id, e.horse_number,
            e.popularity, e.odds, e.horse_weight_diff,
            ra.course_type, ra.distance, ra.date, ra.venue,
            r.finish_position,
            (SELECT COUNT(*) FROM entries e2 WHERE e2.race_id = e.race_id) AS headcount,
            p.finish_position AS prev_pos,
            p.headcount       AS prev_hc,
            p.distance        AS prev_dist,
            p.course_type     AS prev_course,
            p.popularity      AS prev_pop,
            pay_f.payout AS fukusho_payout,
            pay_t.payout AS tansho_payout
        FROM entries e
        JOIN races ra ON ra.race_id = e.race_id
        JOIN results r ON r.race_id = e.race_id AND r.horse_id = e.horse_id
        LEFT JOIN horse_histories p
            ON p.horse_id = e.horse_id
            AND p.race_date = (
                SELECT MAX(race_date) FROM horse_histories
                WHERE horse_id = e.horse_id AND race_date < ra.date
            )
        LEFT JOIN payouts pay_f ON pay_f.race_id = e.race_id
            AND pay_f.bet_type = '複勝'
            AND pay_f.combination = CAST(e.horse_number AS TEXT)
        LEFT JOIN payouts pay_t ON pay_t.race_id = e.race_id
            AND pay_t.bet_type = '単勝'
            AND pay_t.combination = CAST(e.horse_number AS TEXT)
        WHERE ra.date >= '2025-01-01'
          AND p.finish_position IS NOT NULL
    """

    rows = conn.execute(query).fetchall()
    print(f"分析対象: {len(rows)}件\n")

    if not rows:
        print("データなし。horse_historiesの日付とentriesの日付を確認してください。")
        conn.close()
        return

    signal_stats = defaultdict(lambda: {
        'count': 0, 'hit3': 0, 'hit1': 0,
        'f_sum': 0.0, 'f_valid': 0,
        't_sum': 0.0, 't_valid': 0,
    })
    score_buckets = defaultdict(lambda: {
        'count': 0, 'hit3': 0,
        'f_sum': 0.0, 'f_valid': 0,
        't_sum': 0.0, 't_valid': 0,
        'odds_sum': 0.0,
    })

    for row in rows:
        entry = dict(row)
        prev = {
            'prev_pos': row['prev_pos'],
            'prev_hc': row['prev_hc'],
            'prev_dist': row['prev_dist'],
            'prev_course': row['prev_course'],
            'prev_pop': row['prev_pop'],
        }
        signals = evaluate_signals(entry, prev)
        score = len(signals) * 1.5

        is_hit3 = row['finish_position'] and row['finish_position'] <= 3
        is_hit1 = row['finish_position'] == 1
        fp = row['fukusho_payout']
        tp = row['tansho_payout']

        for s in signals:
            signal_stats[s]['count'] += 1
            if is_hit3: signal_stats[s]['hit3'] += 1
            if is_hit1: signal_stats[s]['hit1'] += 1
            if fp:
                signal_stats[s]['f_valid'] += 1
                if is_hit3: signal_stats[s]['f_sum'] += fp
            if tp:
                signal_stats[s]['t_valid'] += 1
                if is_hit1: signal_stats[s]['t_sum'] += tp

        for thr in [0, 1, 2, 3, 4]:
            if score >= thr or (thr == 0 and score == 0):
                if thr == 0 and score > 0:
                    continue
                b = score_buckets[thr]
                b['count'] += 1
                if is_hit3: b['hit3'] += 1
                b['odds_sum'] += (row['odds'] or 0)
                if fp:
                    b['f_valid'] += 1
                    if is_hit3: b['f_sum'] += fp
                if tp:
                    b['t_valid'] += 1
                    if is_hit1: b['t_sum'] += tp

    # シグナル別
    print(f"{'シグナル':<25} {'件数':>5} {'複勝率':>7} {'複勝ROI':>9} {'単勝ROI':>9}")
    print("-" * 60)
    for name, st in sorted(signal_stats.items(), key=lambda x: -(x[1]['f_sum'] / max(x[1]['f_valid'], 1))):
        if st['count'] < 10: continue
        fr = st['f_sum'] / st['f_valid'] if st['f_valid'] > 0 else 0
        tr = st['t_sum'] / st['t_valid'] if st['t_valid'] > 0 else 0
        hr = st['hit3'] / st['count']
        mark = " ◆" if fr > 100 else ""
        print(f"{name:<25} {st['count']:>5} {hr:>6.1%} {fr:>8.1f}円 {tr:>8.1f}円{mark}")

    # スコア閾値別
    print(f"\n{'閾値':>5} {'件数':>6} {'複勝率':>7} {'複勝ROI':>9} {'単勝ROI':>9} {'平均オッズ':>9}")
    print("-" * 55)
    all_scored = [r for r in rows]
    for thr in [0.1, 1.5, 3.0, 4.5]:
        subset = []
        for row in all_scored:
            entry = dict(row)
            prev = {
                'prev_pos': row['prev_pos'], 'prev_hc': row['prev_hc'],
                'prev_dist': row['prev_dist'], 'prev_course': row['prev_course'],
                'prev_pop': row['prev_pop'],
            }
            sc = len(evaluate_signals(entry, prev)) * 1.5
            if sc >= thr:
                subset.append(row)

        if len(subset) < 10: continue
        hit3 = [r for r in subset if r['finish_position'] and r['finish_position'] <= 3]
        vf = [r for r in subset if r['fukusho_payout']]
        vt = [r for r in subset if r['tansho_payout']]
        fr = sum(r['fukusho_payout'] for r in vf if r['finish_position'] and r['finish_position'] <= 3) / len(vf) if vf else 0
        tr = sum(r['tansho_payout'] for r in vt if r['finish_position'] == 1) / len(vt) if vt else 0
        hr = len(hit3) / len(subset)
        avg_odds = sum(r['odds'] or 0 for r in subset) / len(subset)
        mark = " ◆" if fr > 100 else ""
        print(f"{thr:>5.1f} {len(subset):>6} {hr:>6.1%} {fr:>8.1f}円 {tr:>8.1f}円 {avg_odds:>8.1f}倍{mark}")

    conn.close()


if __name__ == "__main__":
    run()
