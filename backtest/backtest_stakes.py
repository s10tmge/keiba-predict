"""
backtest/backtest_stakes.py - 重賞ロジックのエンドツーエンドバックテスト

verify.py と違い、SQLでシグナル条件を再実装せず、
本番コード（analysis.signal_rules_stakes.score_stakes）をそのまま
過去レース全頭に適用してROIを集計する。

- 本番コードと検証のズレを検出できる（コードが正）
- 判定バンド別（★★/★/△/スルー/消し）のROIが出る
  → 「合計スコアが高いほど期待値が高い」の直接検証
- --date-from / --date-to で期間指定可能
  → 2022〜2024年データを追加したらそのままアウトオブサンプル検証になる

使い方（keiba.db と同じフォルダで）:
    python -m backtest.backtest_stakes
    python -m backtest.backtest_stakes --date-from 2022-01-01 --date-to 2024-12-31
"""

import argparse
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.signal_rules_stakes import score_stakes, stakes_verdict  # noqa: E402

SQL = """
SELECT
    e.race_id, e.horse_number, e.popularity, e.frame_number,
    e.odds, e.weight_carried,
    r.date, r.distance, r.race_name,
    res.finish_position,
    hh.popularity        AS prev_pop,
    hh.finish_position   AS prev_pos,
    hh.distance          AS prev_dist,
    hh.corner_position   AS prev_corner,
    hh.headcount         AS prev_headcount,
    hh.weight_carried    AS prev_wc,
    hh2.finish_position  AS prev2_pos,
    pay_t.payout AS tansho,
    pay_f.payout AS fukusho
FROM entries e
JOIN races r    ON r.race_id = e.race_id
JOIN results res ON res.race_id = e.race_id AND res.horse_id = e.horse_id
LEFT JOIN horse_histories hh ON hh.horse_id = e.horse_id
  AND hh.race_date = (
    SELECT MAX(h2.race_date) FROM horse_histories h2
    WHERE h2.horse_id = e.horse_id AND h2.race_date < r.date
  )
LEFT JOIN horse_histories hh2 ON hh2.horse_id = e.horse_id
  AND hh2.race_date = (
    SELECT MAX(h3.race_date) FROM horse_histories h3
    WHERE h3.horse_id = e.horse_id AND h3.race_date < hh.race_date
  )
LEFT JOIN payouts pay_t ON pay_t.race_id = e.race_id AND pay_t.bet_type = '単勝'
  AND pay_t.combination = CAST(e.horse_number AS TEXT)
LEFT JOIN payouts pay_f ON pay_f.race_id = e.race_id AND pay_f.bet_type = '複勝'
  AND pay_f.combination = CAST(e.horse_number AS TEXT)
WHERE (
    r.race_name LIKE '%(G1)%' OR r.race_name LIKE '%(G2)%' OR r.race_name LIKE '%(G3)%'
    OR r.race_name LIKE '%（G1）%' OR r.race_name LIKE '%（G2）%' OR r.race_name LIKE '%（G3）%'
  )
  AND TRIM(r.course_type) = '芝'
  AND res.finish_position IS NOT NULL
  AND r.date >= ? AND r.date <= ?
"""


def roi_line(rows, label):
    n = len(rows)
    if not n:
        print(f"  {label}: n=0")
        return
    t_hit = [r for r in rows if r['finish_position'] == 1 and r['tansho']]
    f_hit = [r for r in rows
             if r['finish_position'] and r['finish_position'] <= 3 and r['fukusho']]
    t_roi = sum(r['tansho'] for r in t_hit) / n
    f_roi = sum(r['fukusho'] for r in f_hit) / n
    print(f"  {label}: n={n:<5} 単勝ROI={t_roi:5.0f}円({len(t_hit):>3}本/{len(t_hit)/n*100:4.1f}%)"
          f"  複勝ROI={f_roi:5.0f}円({len(f_hit):>3}本/{len(f_hit)/n*100:4.1f}%)")


def main():
    ap = argparse.ArgumentParser(description="重賞ロジック エンドツーエンドバックテスト")
    ap.add_argument("--db", default="keiba.db")
    ap.add_argument("--date-from", default="2000-01-01")
    ap.add_argument("--date-to", default="2099-12-31")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(SQL, (args.date_from, args.date_to)).fetchall()
    conn.close()

    print(f"対象: 芝重賞 {args.date_from} 〜 {args.date_to}")
    print(f"総頭数: {len(rows)}")
    if not rows:
        print("データなし。--db のパスを確認してください。")
        return

    scored = []
    for r in rows:
        entry = {
            'popularity': r['popularity'],
            'distance': r['distance'],
            'frame_number': r['frame_number'],
            'weight_carried': r['weight_carried'],
        }
        prev = None
        if r['prev_pos'] is not None or r['prev_pop'] is not None:
            prev = {
                'popularity': r['prev_pop'],
                'finish_position': r['prev_pos'],
                'distance': r['prev_dist'],
                'corner_position': r['prev_corner'],
                'headcount': r['prev_headcount'],
                'weight_carried': r['prev_wc'],
            }
        score, signals = score_stakes(entry, prev, prev2_pos=r['prev2_pos'])
        scored.append({'row': r, 'score': score, 'signals': signals})

    # ------------------------------------------------------------
    # 1. 判定バンド別ROI（合計スコア→verdictが期待値順になっているか）
    # ------------------------------------------------------------
    print("\n" + "=" * 64)
    print("[1] 判定バンド別ROI（穴馬4人気以上・本番verdictそのまま）")
    print("=" * 64)
    bands = defaultdict(list)
    for s in scored:
        pop = s['row']['popularity']
        if not pop or pop <= 3:
            continue
        v = stakes_verdict(s['score'], pop)
        bands[v.split()[0]].append(s['row'])
    for key in ["★★", "★", "△", "-", "⚠", "✕"]:
        if key in bands:
            roi_line(bands[key], f"{key:>3}")

    # ------------------------------------------------------------
    # 2. スコア帯別ROI
    # ------------------------------------------------------------
    print("\n" + "=" * 64)
    print("[2] スコア帯別ROI（4人気以上）")
    print("=" * 64)
    buckets = [
        ("6.0以上", lambda x: x >= 6.0),
        ("5.0-5.9", lambda x: 5.0 <= x < 6.0),
        ("3.0-4.9", lambda x: 3.0 <= x < 5.0),
        ("1.0-2.9", lambda x: 1.0 <= x < 3.0),
        ("0.1-0.9", lambda x: 0 < x < 1.0),
        ("0（無印）", lambda x: x == 0),
        ("-0.1〜-1.9", lambda x: -2.0 < x < 0),
        ("-2.0以下", lambda x: x <= -2.0),
    ]
    for label, fn in buckets:
        sub = [s['row'] for s in scored
               if s['row']['popularity'] and s['row']['popularity'] >= 4
               and fn(s['score'])]
        roi_line(sub, label)

    # ------------------------------------------------------------
    # 3. シグナル別ROI（本番コード発動ベース）
    # ------------------------------------------------------------
    print("\n" + "=" * 64)
    print("[3] シグナル別ROI（本番コードが実際に発動した頭数ベース）")
    print("=" * 64)
    by_sig = defaultdict(list)
    for s in scored:
        for sig in s['signals']:
            by_sig[sig['name']].append(s['row'])
    for name in sorted(by_sig):
        roi_line(by_sig[name], name)

    # ------------------------------------------------------------
    # 4. データ欠損率（シグナルが機能する前提の確認）
    # ------------------------------------------------------------
    print("\n" + "=" * 64)
    print("[4] データ欠損率")
    print("=" * 64)
    n = len(rows)
    for col, label in [('prev_pos', '前走着順'), ('prev_corner', '前走通過順位'),
                       ('prev_headcount', '前走頭数'), ('prev_wc', '前走斤量'),
                       ('weight_carried', '今回斤量'), ('prev2_pos', '2走前着順')]:
        missing = sum(1 for r in rows if r[col] is None)
        print(f"  {label}: 欠損 {missing}/{n} ({missing/n*100:.1f}%)")

    print("\n完了。このテキストをクロードに貼り付けてください。")


if __name__ == "__main__":
    main()
