"""
analysis/backtest_new_signals.py - 新データを使ったシグナル検証

検証対象:
  1. B_3F     : 前走3F偏差（race_idジョインで初めて検証可能）
  2. 脚質      : 前走4角位置取り比率（corner_positionから算出）
  3. 斤量減    : 前走比-2kg以上の斤量減ブースト
  4. 斤量比率  : 斤量÷馬体重 > 12.5% のデバフ
  5. 前走グレード: 前走G1/G2/G3か否かで既存シグナルの精度が変わるか

実行:
  python -m analysis.backtest_new_signals          # 重賞のみ
  python -m analysis.backtest_new_signals --all    # 全レース
"""

import sqlite3
import argparse
from collections import defaultdict

DB_PATH = 'keiba.db'


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def roi(payouts: list) -> str:
    if not payouts:
        return 'n=0'
    hits = [p for p in payouts if p]
    rate = sum(hits) / len(payouts)
    return f"ROI {rate:.0f}円  n={len(payouts)}  的中率{len(hits)/len(payouts)*100:.1f}%"


def main(grade_filter: str):
    conn = get_conn()

    if grade_filter == '重賞':
        gf = """AND (ra.race_name LIKE '%(G1)%' OR ra.race_name LIKE '%(G2)%'
                    OR ra.race_name LIKE '%(G3)%'
                    OR ra.race_name LIKE '%（G1）%' OR ra.race_name LIKE '%（G2）%'
                    OR ra.race_name LIKE '%（G3）%')"""
    else:
        gf = ''

    # -------------------------------------------------------
    # ベースデータ取得
    # entries + prev horse_histories + payouts
    # -------------------------------------------------------
    rows = conn.execute(f"""
    SELECT
        e.race_id, e.horse_id, e.popularity, e.weight_carried AS cur_kilo,
        e.horse_weight AS cur_hw,
        ra.date, ra.distance AS cur_dist, ra.course_type,
        ra.race_name,
        r.finish_position,
        -- 単勝払戻
        pay_t.payout AS tansho,
        -- 前走データ
        h.last_3f        AS prev_3f,
        h.race_id        AS prev_race_id,
        h.finish_position AS prev_pos,
        h.popularity     AS prev_pop,
        h.distance       AS prev_dist,
        h.course_type    AS prev_course,
        h.race_class     AS prev_class,
        h.weight_carried AS prev_kilo,
        h.corner_position AS prev_corner,
        h.headcount      AS prev_hc,
        -- 2走前
        h2.finish_position AS prev2_pos
    FROM entries e
    JOIN races ra ON ra.race_id = e.race_id
    JOIN results r ON r.race_id = e.race_id AND r.horse_id = e.horse_id
    LEFT JOIN horse_histories h
        ON h.horse_id = e.horse_id
        AND h.race_date = (
            SELECT MAX(race_date) FROM horse_histories
            WHERE horse_id = e.horse_id AND race_date < ra.date
        )
    LEFT JOIN horse_histories h2
        ON h2.horse_id = e.horse_id
        AND h2.race_date = (
            SELECT MAX(race_date) FROM horse_histories
            WHERE horse_id = e.horse_id
              AND race_date < (
                  SELECT MAX(race_date) FROM horse_histories
                  WHERE horse_id = e.horse_id AND race_date < ra.date
              )
        )
    LEFT JOIN payouts pay_t
        ON pay_t.race_id = e.race_id AND pay_t.bet_type = '単勝'
        AND pay_t.combination = CAST(e.horse_number AS TEXT)
    WHERE ra.date >= '2025-01-01'
      AND e.popularity IS NOT NULL
      AND r.finish_position IS NOT NULL
      {gf}
    """).fetchall()

    # prev_race_id -> avg_3f のマッピングを作成（entriesから）
    race_avg_3f = {}
    for rr in conn.execute(
        "SELECT race_id, AVG(last_3f) as avg FROM entries WHERE last_3f IS NOT NULL GROUP BY race_id"
    ):
        race_avg_3f[rr['race_id']] = rr['avg']

    conn.close()

    print(f"\n対象データ: {len(rows)}件  ({grade_filter})")
    print("=" * 65)

    # -------------------------------------------------------
    # 1. B_3F: 前走3F偏差
    # -------------------------------------------------------
    print("\n【1. B_3F 前走3F偏差】")
    print("  定義: 前走レース全馬平均3F - その馬の前走3F (正=速い=能力あり)")

    b3f_buckets = {
        '+2.0以上': (2.0, 99),
        '+1.0〜2.0': (1.0, 2.0),
        '+0.5〜1.0': (0.5, 1.0),
        '±0.5': (-0.5, 0.5),
        '-0.5以下': (-99, -0.5),
    }
    b3f_results = defaultdict(list)

    for row in rows:
        pop = row['popularity']
        if not (7 <= pop <= 11):
            continue
        prev_rid = row['prev_race_id']
        prev_3f = row['prev_3f']
        if not prev_rid or not prev_3f:
            continue
        avg = race_avg_3f.get(prev_rid)
        if not avg:
            continue
        diff = avg - prev_3f
        for label, (lo, hi) in b3f_buckets.items():
            if lo <= diff < hi:
                b3f_results[label].append(row['tansho'])
                break

    for label in b3f_buckets:
        print(f"  {label:12s}: {roi(b3f_results[label])}")

    # -------------------------------------------------------
    # 2. 脚質分類（前走4角位置取り比率）
    # -------------------------------------------------------
    print("\n【2. 脚質シグナル（前走4角位置取り比率）】")
    print("  0-25%=逃先行 / 26-70%=中団 / 71-100%=後方")

    def parse_last_corner(corner_str, hc):
        if not corner_str or not hc or hc == 0:
            return None
        parts = [p.strip() for p in corner_str.replace('－', '-').split('-')]
        last = parts[-1]
        try:
            pos = int(last)
            return pos / hc
        except (ValueError, TypeError):
            return None

    pace_buckets = {
        '逃先行(0-25%)': (0, 0.26),
        '中団(26-70%)': (0.26, 0.71),
        '後方(71-100%)': (0.71, 1.01),
    }
    pace_results = defaultdict(list)

    for row in rows:
        pop = row['popularity']
        if not (7 <= pop <= 11):
            continue
        ratio = parse_last_corner(row['prev_corner'], row['prev_hc'])
        if ratio is None:
            continue
        for label, (lo, hi) in pace_buckets.items():
            if lo <= ratio < hi:
                pace_results[label].append(row['tansho'])
                break

    for label in pace_buckets:
        print(f"  {label:18s}: {roi(pace_results[label])}")

    # 距離短縮×前走前脚質
    print("\n  ── 距離短縮(100m超)×前走前脚質(0-25%) ──")
    short_front = []
    for row in rows:
        pop = row['popularity']
        if not (7 <= pop <= 11):
            continue
        if not row['prev_dist'] or not row['cur_dist']:
            continue
        dist_diff = row['cur_dist'] - row['prev_dist']
        if dist_diff >= -100:
            continue
        ratio = parse_last_corner(row['prev_corner'], row['prev_hc'])
        if ratio is not None and ratio <= 0.25:
            short_front.append(row['tansho'])
    print(f"  距離短縮×前走逃先行: {roi(short_front)}")

    # -------------------------------------------------------
    # 3. 斤量シグナル
    # -------------------------------------------------------
    print("\n【3. 斤量シグナル】")

    # 3a. 斤量減ブースト（今回 < 前走 -2kg）
    kilo_down = []
    kilo_same = []
    kilo_up = []
    for row in rows:
        pop = row['popularity']
        if not (7 <= pop <= 11):
            continue
        cur_k = row['cur_kilo']
        prev_k = row['prev_kilo']
        if not cur_k or not prev_k:
            continue
        diff = cur_k - prev_k
        if diff <= -2.0:
            kilo_down.append(row['tansho'])
        elif diff >= 2.0:
            kilo_up.append(row['tansho'])
        else:
            kilo_same.append(row['tansho'])

    print(f"  斤量減(-2kg以上): {roi(kilo_down)}")
    print(f"  斤量変化なし    : {roi(kilo_same)}")
    print(f"  斤量増(+2kg以上): {roi(kilo_up)}")

    # 3b. 斤量比率デバフ（斤量÷馬体重 > 12.5%）
    print("\n  ── 斤量比率デバフ（斤量÷馬体重）──")
    ratio_over = []
    ratio_ok = []
    for row in rows:
        pop = row['popularity']
        if not (4 <= pop <= 11):
            continue
        cur_k = row['cur_kilo']
        cur_hw = row['cur_hw']
        if not cur_k or not cur_hw or cur_hw == 0:
            continue
        ratio = cur_k / cur_hw
        if ratio > 0.125:
            ratio_over.append(row['tansho'])
        else:
            ratio_ok.append(row['tansho'])

    print(f"  比率12.5%超（デバフ候補）: {roi(ratio_over)}")
    print(f"  比率12.5%以下（正常）    : {roi(ratio_ok)}")

    # -------------------------------------------------------
    # 4. 前走グレード別ROI（S1〜S3の精度検証）
    # -------------------------------------------------------
    print("\n【4. 前走グレード別 S1シグナルのROI】")
    print("  S1: 今回9-11人気 × 前走1-3人気")

    s1_by_grade = defaultdict(list)
    for row in rows:
        pop = row['popularity']
        prev_pop = row['prev_pop']
        if not (9 <= pop <= 11 and prev_pop and 1 <= prev_pop <= 3):
            continue
        grade = row['prev_class'] or '不明'
        if grade not in ['G1', 'G2', 'G3']:
            grade = 'OP以下'
        s1_by_grade[grade].append(row['tansho'])

    for grade in ['G1', 'G2', 'G3', 'OP以下', '不明']:
        if s1_by_grade[grade]:
            print(f"  前走{grade:6s}: {roi(s1_by_grade[grade])}")

    print("\n  S3: 今回7-9人気 × 前走4-6人気 × 前走1-3着")
    s3_by_grade = defaultdict(list)
    for row in rows:
        pop = row['popularity']
        prev_pop = row['prev_pop']
        prev_pos = row['prev_pos']
        if not (7 <= pop <= 9 and prev_pop and 4 <= prev_pop <= 6
                and prev_pos and 1 <= prev_pos <= 3):
            continue
        grade = row['prev_class'] or '不明'
        if grade not in ['G1', 'G2', 'G3']:
            grade = 'OP以下'
        s3_by_grade[grade].append(row['tansho'])

    for grade in ['G1', 'G2', 'G3', 'OP以下', '不明']:
        if s3_by_grade[grade]:
            print(f"  前走{grade:6s}: {roi(s3_by_grade[grade])}")

    print()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--all', action='store_true', help='全レース対象（デフォルト:重賞のみ）')
    args = parser.parse_args()
    main('全レース' if args.all else '重賞')
