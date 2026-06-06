"""
analysis/tune_signals.py - シグナルスコアの自動チューニング

signal_backtest_v2の結果を元に、複勝ROI>100%のシグナルのみ有効化し、
スコアをROIに比例して再設定する。

使い方:
    python main.py tune-signals
"""

import sqlite3
import sys
from config import DB_PATH
from analysis.signal_rules import evaluate_signals
from collections import defaultdict


def run(db_path: str = DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    print("=== シグナル自動チューニング ===\n")

    query = """
    WITH prev AS (
        SELECT horse_id, race_date,
               finish_position AS prev_pos, headcount AS prev_hc,
               distance AS prev_dist, course_type AS prev_course,
               popularity AS prev_pop, last_3f AS prev_3f,
               race_class AS prev_class,
               ROW_NUMBER() OVER (PARTITION BY horse_id ORDER BY race_date DESC) AS rn
        FROM horse_histories
    )
    SELECT
        e.race_id, e.horse_id, e.horse_number, e.popularity, e.odds,
        e.horse_weight, e.horse_weight_diff, e.last_3f,
        ra.course_type, ra.distance, ra.track_condition,
        ra.date, ra.race_class, ra.venue,
        r.finish_position,
        (SELECT COUNT(*) FROM entries e2 WHERE e2.race_id = e.race_id) AS headcount,
        p.prev_pos, p.prev_hc, p.prev_dist, p.prev_course,
        p.prev_pop, p.prev_3f, p.prev_class,
        pay_f.payout AS fukusho_payout
    FROM entries e
    JOIN races ra ON ra.race_id = e.race_id
    JOIN results r ON r.race_id = e.race_id AND r.horse_id = e.horse_id
    LEFT JOIN prev p ON p.horse_id = e.horse_id AND p.race_date < ra.date AND p.rn = 1
    LEFT JOIN payouts pay_f ON pay_f.race_id = e.race_id
        AND pay_f.bet_type = '複勝'
        AND pay_f.combination = CAST(e.horse_number AS TEXT)
    WHERE ra.date >= '2025-01-01'
      AND p.prev_pos IS NOT NULL
    """

    rows = conn.execute(query).fetchall()
    conn.close()

    signal_stats = defaultdict(lambda: {
        'count': 0, 'hit': 0, 'pay_sum': 0, 'valid': 0
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
        is_hit = row['finish_position'] and row['finish_position'] <= 3

        for s in signals:
            name = s['name']
            signal_stats[name]['count'] += 1
            if is_hit:
                signal_stats[name]['hit'] += 1
            if row['fukusho_payout']:
                signal_stats[name]['valid'] += 1
                if is_hit:
                    signal_stats[name]['pay_sum'] += row['fukusho_payout']

    print(f"{'シグナル':<30} {'件数':>5} {'複勝率':>7} {'複勝ROI':>9} {'推奨スコア':>9}")
    print("-" * 65)

    tuned_scores = {}
    for name, st in sorted(signal_stats.items()):
        if st['count'] < 15:
            continue
        roi = st['pay_sum'] / st['valid'] if st['valid'] > 0 else 0
        rate = st['hit'] / st['count']

        # ROI 100円=中立, 120円=スコア2.0, 80円=無効化
        if roi >= 120:
            score = 3.0
        elif roi >= 110:
            score = 2.0
        elif roi >= 100:
            score = 1.5
        elif roi >= 90:
            score = 0.5
        else:
            score = 0.0

        tuned_scores[name] = score
        mark = " ◆" if roi > 100 else (" ✗" if score == 0 else "")
        print(f"{name:<30} {st['count']:>5} {rate:>6.1%} {roi:>8.1f}円 {score:>8.1f}{mark}")

    # チューニング済みスコアをコメントとして出力（signal_rules.pyに貼り付け用）
    print("\n\n=== signal_rules.py 推奨スコア設定 ===")
    print("以下を signal_rules.py の各シグナルの score= に設定してください:\n")
    for name, score in tuned_scores.items():
        print(f"  {name}: score={score}")

    # 実際にsignal_rules.pyを自動更新
    _update_signal_rules(tuned_scores)


def _update_signal_rules(tuned: dict):
    """signal_rules.py のスコア値を自動更新する。"""
    import re
    from pathlib import Path

    path = Path(__file__).parent / "signal_rules.py"
    content = path.read_text(encoding="utf-8")

    # シグナル名→スコアのマッピング（S1_xxx形式）
    updated = False
    for name, score in tuned.items():
        # 'name': 'S1_xxx', パターンの後にある 'score': X.X を更新
        pattern = rf"('{re.escape(name)}',\s*\n\s*'score':\s*)[\d.]+"
        new_content = re.sub(pattern, rf"\g<1>{score}", content)
        if new_content != content:
            content = new_content
            updated = True

    if updated:
        path.write_text(content, encoding="utf-8")
        print("\nsignal_rules.py のスコアを更新しました。")
    else:
        print("\n※ signal_rules.py の自動更新は手動パターンが必要。上記スコアを手動で設定してください。")


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else DB_PATH
    run(db)
