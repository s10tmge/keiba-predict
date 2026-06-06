"""
analysis/signal_backtest_v2.py - signal_rules.py の実データ検証

horse_histories × entries × payouts を使い、
各シグナルの実複勝ROIと単勝ROIを計算する。
スコア閾値ごとの成績も検証する。

使い方:
    python main.py signal-backtest-v2
    python -m analysis.signal_backtest_v2
"""

import sqlite3
import sys
from collections import defaultdict
from config import DB_PATH
from analysis.signal_rules import evaluate_signals


def run(db_path: str = DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    print("=== signal_rules.py バックテスト（2025年実データ）===\n")

    # 全エントリ + 前走 + 実払戻 を一括取得
    query = """
    WITH prev AS (
        SELECT
            horse_id,
            race_date,
            finish_position AS prev_pos,
            headcount AS prev_hc,
            distance AS prev_dist,
            course_type AS prev_course,
            popularity AS prev_pop,
            last_3f AS prev_3f,
            race_class AS prev_class,
            ROW_NUMBER() OVER (PARTITION BY horse_id ORDER BY race_date DESC) AS rn
        FROM horse_histories
    )
    SELECT
        e.race_id,
        e.horse_id,
        e.horse_number,
        e.popularity,
        e.odds,
        e.horse_weight,
        e.horse_weight_diff,
        e.last_3f,
        ra.course_type,
        ra.distance,
        ra.track_condition,
        ra.date,
        ra.race_class,
        ra.venue,
        r.finish_position,
        (SELECT COUNT(*) FROM entries e2 WHERE e2.race_id = e.race_id) AS headcount,
        p.prev_pos,
        p.prev_hc,
        p.prev_dist,
        p.prev_course,
        p.prev_pop,
        p.prev_3f,
        p.prev_class,
        pay_f.payout AS fukusho_payout,
        pay_t.payout AS tansho_payout
    FROM entries e
    JOIN races ra ON ra.race_id = e.race_id
    JOIN results r ON r.race_id = e.race_id AND r.horse_id = e.horse_id
    LEFT JOIN prev p ON p.horse_id = e.horse_id
        AND p.race_date < ra.date AND p.rn = 1
    LEFT JOIN payouts pay_f ON pay_f.race_id = e.race_id
        AND pay_f.bet_type = '複勝'
        AND pay_f.combination = CAST(e.horse_number AS TEXT)
    LEFT JOIN payouts pay_t ON pay_t.race_id = e.race_id
        AND pay_t.bet_type = '単勝'
        AND pay_t.combination = CAST(e.horse_number AS TEXT)
    WHERE ra.date >= '2025-01-01'
      AND p.prev_pos IS NOT NULL
    """

    rows = conn.execute(query).fetchall()
    print(f"分析対象エントリ: {len(rows)}件\n")

    if not rows:
        print("データなし")
        conn.close()
        return

    # 各エントリにシグナルスコアを付与
    scored = []
    signal_stats = defaultdict(lambda: {
        'count': 0, 'hit3': 0, 'hit1': 0,
        'fukusho_sum': 0, 'tansho_sum': 0,
        'fukusho_valid': 0, 'tansho_valid': 0
    })

    for row in rows:
        entry = dict(row)
        prev = {
            'finish_position': row['prev_pos'],
            'headcount': row['prev_hc'],
            'distance': row['prev_dist'],
            'course_type': row['prev_course'],
            'popularity': row['prev_pop'],
            'last_3f': row['prev_3f'],
            'race_class': row['prev_class'],
        }
        signals = evaluate_signals(entry, prev)
        total_score = sum(s['score'] for s in signals)

        is_hit3 = row['finish_position'] and row['finish_position'] <= 3
        is_hit1 = row['finish_position'] == 1

        for s in signals:
            name = s['name']
            signal_stats[name]['count'] += 1
            if is_hit3:
                signal_stats[name]['hit3'] += 1
            if is_hit1:
                signal_stats[name]['hit1'] += 1
            if row['fukusho_payout']:
                signal_stats[name]['fukusho_valid'] += 1
                if is_hit3:
                    signal_stats[name]['fukusho_sum'] += row['fukusho_payout']
            if row['tansho_payout']:
                signal_stats[name]['tansho_valid'] += 1
                if is_hit1:
                    signal_stats[name]['tansho_sum'] += row['tansho_payout']

        scored.append({
            **entry,
            'signals': signals,
            'score': total_score,
            'is_hit3': is_hit3,
            'is_hit1': is_hit1,
        })

    # シグナル別結果
    print(f"{'シグナル':<28} {'件数':>5} {'複勝率':>7} {'複勝ROI':>9} {'単勝ROI':>9}")
    print("-" * 65)

    signal_results = []
    for name, st in signal_stats.items():
        if st['count'] < 15:
            continue
        f_roi = st['fukusho_sum'] / st['fukusho_valid'] if st['fukusho_valid'] > 0 else 0
        t_roi = st['tansho_sum'] / st['tansho_valid'] if st['tansho_valid'] > 0 else 0
        f_rate = st['hit3'] / st['count']
        signal_results.append((name, st['count'], f_rate, f_roi, t_roi))

    signal_results.sort(key=lambda x: x[3], reverse=True)
    for name, cnt, f_rate, f_roi, t_roi in signal_results:
        mark = " ◆" if f_roi > 100 else ""
        print(f"{name:<28} {cnt:>5} {f_rate:>6.1%} {f_roi:>8.1f}円 {t_roi:>8.1f}円{mark}")

    # スコア閾値別パフォーマンス
    print("\n\n=== スコア閾値別パフォーマンス ===")
    print(f"{'閾値':>5} {'件数':>6} {'複勝率':>7} {'複勝ROI':>9} {'単勝ROI':>9} {'平均オッズ':>9}")
    print("-" * 55)

    for threshold in [0.1, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]:
        subset = [r for r in scored if r['score'] >= threshold]
        if len(subset) < 10:
            continue

        hit3 = [r for r in subset if r['is_hit3'] and r['fukusho_payout']]
        hit1 = [r for r in subset if r['is_hit1'] and r['tansho_payout']]
        valid_f = [r for r in subset if r['fukusho_payout']]
        valid_t = [r for r in subset if r['tansho_payout']]

        f_roi = sum(r['fukusho_payout'] for r in hit3) / len(valid_f) if valid_f else 0
        t_roi = sum(r['tansho_payout'] for r in hit1) / len(valid_t) if valid_t else 0
        f_rate = len(hit3) / len(subset)
        avg_odds = sum(r['odds'] or 0 for r in subset) / len(subset)

        mark = " ◆" if f_roi > 100 else ""
        print(f"{threshold:>5.1f} {len(subset):>6} {f_rate:>6.1%} {f_roi:>8.1f}円 "
              f"{t_roi:>8.1f}円 {avg_odds:>8.1f}倍{mark}")

    # 最良シグナル組み合わせの月別推移
    print("\n\n=== スコア≥2.0の月別推移 ===")
    print(f"{'月':>7} {'件数':>5} {'複勝率':>7} {'複勝ROI':>9}")
    print("-" * 35)

    from collections import defaultdict
    monthly = defaultdict(lambda: {'total': 0, 'hit': 0, 'pay_sum': 0, 'valid': 0})
    for r in scored:
        if r['score'] < 2.0:
            continue
        m = r['date'][:7]
        monthly[m]['total'] += 1
        if r['is_hit3']:
            monthly[m]['hit'] += 1
        if r['fukusho_payout']:
            monthly[m]['valid'] += 1
            if r['is_hit3']:
                monthly[m]['pay_sum'] += r['fukusho_payout']

    for month in sorted(monthly.keys()):
        d = monthly[month]
        roi = d['pay_sum'] / d['valid'] if d['valid'] > 0 else 0
        rate = d['hit'] / d['total'] if d['total'] > 0 else 0
        mark = " ◆" if roi > 100 else ""
        print(f"{month:>7} {d['total']:>5} {rate:>6.1%} {roi:>8.1f}円{mark}")

    # トップ事例（スコア高い馬の具体例）
    print("\n\n=== 高スコア馬の具体例（スコア≥3.0）===")
    high_score = [r for r in scored if r['score'] >= 3.0]
    high_score.sort(key=lambda x: x['score'], reverse=True)
    print(f"{'日付':>10} {'会場':>4} {'人気':>4} {'着順':>4} {'複勝払':>7} {'スコア':>6}  シグナル")
    for r in high_score[:20]:
        pos = r['finish_position'] or '-'
        pay = r['fukusho_payout'] or 0
        sig_names = "+".join(s['name'].split('_')[1] for s in r['signals'])
        mark = " ✓" if r['is_hit3'] else ""
        print(f"{r['date']:>10} {r['venue']:>4} {r['popularity']:>4}人気 "
              f"{str(pos):>4}着 {pay:>6}円 {r['score']:>5.1f}  {sig_names}{mark}")

    conn.close()


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else DB_PATH
    run(db)
