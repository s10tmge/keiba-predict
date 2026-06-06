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
            if is_hit3:
                signal_stats[s]['hit3'] += 1
                if fp: signal_stats[s]['f_sum'] += fp
            if is_hit1:
                signal_stats[s]['hit1'] += 1
                if tp: signal_stats[s]['t_sum'] += tp

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

    # シグナル別 (ROI = 払戻合計 / 全ベット数)
    print(f"{'シグナル':<25} {'件数':>5} {'複勝率':>7} {'複勝ROI':>9} {'単勝ROI':>9} {'平均払戻':>8}")
    print("-" * 68)
    for name, st in sorted(signal_stats.items(), key=lambda x: -(x[1]['f_sum'] / max(x[1]['count'], 1))):
        if st['count'] < 10: continue
        fr = st['f_sum'] / st['count']           # 全ベット数で割る = ROI
        tr = st['t_sum'] / st['count']
        avg_pay = st['f_sum'] / max(st['hit3'], 1)  # 的中時平均払戻
        hr = st['hit3'] / st['count']
        mark = " ◆" if fr > 100 else ""
        print(f"{name:<25} {st['count']:>5} {hr:>6.1%} {fr:>8.1f}円 {tr:>8.1f}円 {avg_pay:>7.0f}円{mark}")

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
        total = len(subset)
        hit3 = [r for r in subset if r['finish_position'] and r['finish_position'] <= 3]
        f_sum = sum(r['fukusho_payout'] for r in hit3 if r['fukusho_payout'])
        t_sum = sum(r['tansho_payout'] for r in subset if r['finish_position'] == 1 and r['tansho_payout'])
        fr = f_sum / total   # 正しいROI: 払戻合計/全ベット数
        tr = t_sum / total
        hr = len(hit3) / total
        avg_odds = sum(r['odds'] or 0 for r in subset) / total
        mark = " ◆" if fr > 100 else ""
        print(f"{thr:>5.1f} {total:>6} {hr:>6.1%} {fr:>8.1f}円 {tr:>8.1f}円 {avg_odds:>8.1f}倍{mark}")

    # スコア4.5以上（複数シグナル重複）の詳細
    print("\n\n=== スコア4.5以上の詳細（単勝候補）===")
    high = []
    for row in rows:
        entry = dict(row)
        prev = {
            'prev_pos': row['prev_pos'], 'prev_hc': row['prev_hc'],
            'prev_dist': row['prev_dist'], 'prev_course': row['prev_course'],
            'prev_pop': row['prev_pop'],
        }
        sc = len(evaluate_signals(entry, prev)) * 1.5
        if sc >= 4.5:
            high.append((row, sc))

    hit1 = [r for r, s in high if r['finish_position'] == 1]
    t_sum = sum(r['tansho_payout'] for r in hit1 if r['tansho_payout'])
    t_roi = t_sum / len(high) if high else 0
    hit3 = [r for r, s in high if r['finish_position'] and r['finish_position'] <= 3]
    print(f"件数: {len(high)}, 1着: {len(hit1)}({len(hit1)/len(high)*100:.1f}%), 3着内: {len(hit3)}({len(hit3)/len(high)*100:.1f}%)")
    print(f"単勝ROI: {t_roi:.1f}円")

    # 月別
    from collections import defaultdict as dd
    monthly = dd(lambda: {'n': 0, 'win': 0, 't_sum': 0})
    for row, sc in high:
        m = row['date'][:7]
        monthly[m]['n'] += 1
        if row['finish_position'] == 1:
            monthly[m]['win'] += 1
            if row['tansho_payout']: monthly[m]['t_sum'] += row['tansho_payout']
    print(f"\n{'月':>7} {'件数':>4} {'勝率':>6} {'単勝ROI':>9}")
    for m in sorted(monthly):
        d = monthly[m]
        roi = d['t_sum'] / d['n'] if d['n'] > 0 else 0
        rate = d['win'] / d['n']
        mark = " ◆" if roi > 100 else ""
        print(f"{m:>7} {d['n']:>4} {rate:>5.1%} {roi:>8.1f}円{mark}")

    # 馬連ROI分析
    print("\n\n=== 馬連ROI分析（スコア上位2頭の馬連）===")
    # レース別にスコア高い2頭の馬連を調べる
    race_horses = dd(list)
    for row in rows:
        entry = dict(row)
        prev = {
            'prev_pos': row['prev_pos'], 'prev_hc': row['prev_hc'],
            'prev_dist': row['prev_dist'], 'prev_course': row['prev_course'],
            'prev_pop': row['prev_pop'],
        }
        sc = len(evaluate_signals(entry, prev)) * 1.5
        if sc > 0:
            race_horses[row['race_id']].append((sc, row['horse_number'], row['finish_position']))

    # 各レースで上位2頭の馬連を確認
    bets = 0
    wins = 0
    pay_sum = 0
    for race_id, horses in race_horses.items():
        if len(horses) < 2:
            continue
        horses.sort(reverse=True)
        h1, h2 = horses[0][1], horses[1][1]
        pos1, pos2 = horses[0][2], horses[1][2]
        # 馬連的中 = 2頭が1着2着（順不同）
        hit = pos1 in [1, 2] and pos2 in [1, 2] and pos1 != pos2
        combo = f"{min(h1,h2)}-{max(h1,h2)}"
        pay = conn.execute(
            "SELECT payout FROM payouts WHERE race_id=? AND bet_type='馬連' AND combination=?",
            (race_id, combo)
        ).fetchone()
        bets += 1
        if hit and pay:
            wins += 1
            pay_sum += pay[0]

    if bets > 0:
        roi = pay_sum / bets
        print(f"シグナル上位2頭馬連: {bets}レース, 的中{wins}({wins/bets*100:.1f}%), 馬連ROI: {roi:.1f}円")
    else:
        print("馬連データなし")

    conn.close()


if __name__ == "__main__":
    run()
