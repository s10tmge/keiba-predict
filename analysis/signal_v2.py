"""
analysis/signal_v2.py - 前走データ込み複合シグナル分析

horse_histories × entries × payoutsを結合し、
実払戻ベースのROIでシグナルを評価する。
"""

import sqlite3
import sys
from config import DB_PATH


def run(db_path: str = DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    print("=== 前走データ込み複合シグナル 実払戻ROI分析 ===\n")

    # メインクエリ: 前走情報付きエントリ × 実複勝払戻
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
    ),
    entry_with_prev AS (
        SELECT
            e.race_id,
            e.horse_id,
            e.popularity,
            e.odds,
            e.horse_weight_diff,
            e.last_3f,
            ra.course_type,
            ra.distance,
            ra.track_condition,
            ra.date,
            ra.race_class,
            (SELECT COUNT(*) FROM entries e2 WHERE e2.race_id = e.race_id) AS headcount,
            r.finish_position,
            p.prev_pos,
            p.prev_hc,
            p.prev_dist,
            p.prev_course,
            p.prev_pop,
            p.prev_3f,
            p.prev_class
        FROM entries e
        JOIN races ra ON ra.race_id = e.race_id
        JOIN results r ON r.race_id = e.race_id AND r.horse_id = e.horse_id
        LEFT JOIN prev p ON p.horse_id = e.horse_id
            AND p.race_date < ra.date AND p.rn = 1
        WHERE ra.date >= '2025-01-01'
          AND p.prev_pos IS NOT NULL
    ),
    with_payout AS (
        SELECT
            ep.*,
            pay.payout AS fukusho_payout
        FROM entry_with_prev ep
        LEFT JOIN payouts pay ON pay.race_id = ep.race_id
            AND pay.bet_type = '複勝'
            AND pay.combination = CAST(
                (SELECT horse_number FROM entries WHERE race_id = ep.race_id AND horse_id = ep.horse_id)
                AS TEXT
            )
    )
    SELECT * FROM with_payout
    """

    rows = conn.execute(query).fetchall()
    print(f"分析対象: {len(rows)}件\n")

    if not rows:
        print("データなし")
        conn.close()
        return

    # シグナル定義と集計
    signals_def = [
        # (シグナル名, フィルタ関数)
        ("6人気以上×前走1-3着×芝", lambda r: r['popularity'] >= 6 and r['prev_pos'] and r['prev_pos'] <= 3 and r['course_type'] == '芝'),
        ("6人気以上×前走1-3着×ダート", lambda r: r['popularity'] >= 6 and r['prev_pos'] and r['prev_pos'] <= 3 and r['course_type'] == 'ダート'),
        ("6人気以上×前走4-6着×芝", lambda r: r['popularity'] >= 6 and r['prev_pos'] and 4 <= r['prev_pos'] <= 6 and r['course_type'] == '芝'),
        ("6人気以上×前走4-6着×ダート", lambda r: r['popularity'] >= 6 and r['prev_pos'] and 4 <= r['prev_pos'] <= 6 and r['course_type'] == 'ダート'),
        ("6人気以上×前走頭数16以上→今回減", lambda r: r['popularity'] >= 6 and r['prev_hc'] and r['prev_hc'] >= 16 and r['headcount'] and r['headcount'] < r['prev_hc']),
        ("6人気以上×距離短縮200m以上", lambda r: r['popularity'] >= 6 and r['prev_dist'] and r['distance'] and r['distance'] - r['prev_dist'] <= -200),
        ("6人気以上×距離延長200m以上", lambda r: r['popularity'] >= 6 and r['prev_dist'] and r['distance'] and r['distance'] - r['prev_dist'] >= 200),
        ("6人気以上×コース変更ダート→芝", lambda r: r['popularity'] >= 6 and r['prev_course'] == 'ダート' and r['course_type'] == '芝'),
        ("6人気以上×コース変更芝→ダート", lambda r: r['popularity'] >= 6 and r['prev_course'] == '芝' and r['course_type'] == 'ダート'),
        ("6人気以上×前走人気1-3×今回6人気以上", lambda r: r['popularity'] >= 6 and r['prev_pop'] and r['prev_pop'] <= 3),
        ("6人気以上×馬体重増加+10以上", lambda r: r['popularity'] >= 6 and r['horse_weight_diff'] and r['horse_weight_diff'] >= 10),
        ("6人気以上×馬体重減少-10以上", lambda r: r['popularity'] >= 6 and r['horse_weight_diff'] and r['horse_weight_diff'] <= -10),
        ("7-9人気×ダート×頭数≤12", lambda r: 7 <= r['popularity'] <= 9 and r['course_type'] == 'ダート' and r['headcount'] and r['headcount'] <= 12),
        ("7-9人気×ダート×頭数≤12×前走1-5着", lambda r: 7 <= r['popularity'] <= 9 and r['course_type'] == 'ダート' and r['headcount'] and r['headcount'] <= 12 and r['prev_pos'] and r['prev_pos'] <= 5),
        ("6人気以上×前走1-3着×今回頭数減少", lambda r: r['popularity'] >= 6 and r['prev_pos'] and r['prev_pos'] <= 3 and r['prev_hc'] and r['headcount'] and r['headcount'] < r['prev_hc'] - 2),
        ("8人気以上×前走1-3着×同コース", lambda r: r['popularity'] >= 8 and r['prev_pos'] and r['prev_pos'] <= 3 and r['prev_course'] == r['course_type']),
        ("6人気以上×前走クラス上昇×今回同クラス", lambda r: _class_up(r)),
        ("6人気以上×今回頭数≤10×前走1-3着", lambda r: r['popularity'] >= 6 and r['headcount'] and r['headcount'] <= 10 and r['prev_pos'] and r['prev_pos'] <= 3),
        ("全体ベースライン（6人気以上）", lambda r: r['popularity'] >= 6),
    ]

    print(f"{'シグナル':<42} {'出走':>5} {'複勝的中':>7} {'的中率':>7} {'複勝ROI':>8} {'有効数':>5}")
    print("-" * 80)

    results = []
    for name, fn in signals_def:
        subset = [r for r in rows if fn(r)]
        if len(subset) < 20:
            continue

        hit = [r for r in subset if r['finish_position'] and r['finish_position'] <= 3 and r['fukusho_payout']]
        total_with_pay = [r for r in subset if r['fukusho_payout'] is not None]

        if len(total_with_pay) < 20:
            hit_rate = len([r for r in subset if r['finish_position'] and r['finish_position'] <= 3]) / len(subset)
            results.append((name, len(subset), 0, hit_rate, 0.0, 0))
            continue

        payout_sum = sum(r['fukusho_payout'] for r in hit)
        roi = payout_sum / len(total_with_pay) if total_with_pay else 0
        hit_rate = len(hit) / len(total_with_pay)
        results.append((name, len(subset), len(hit), hit_rate, roi, len(total_with_pay)))

    results.sort(key=lambda x: x[4], reverse=True)
    for name, total, hits, hit_rate, roi, valid in results:
        roi_str = f"{roi:.1f}円" if roi > 0 else "データ不足"
        marker = " ◆" if roi > 100 else ""
        print(f"{name:<42} {total:>5} {hits:>7} {hit_rate:>6.1%} {roi_str:>8}{marker}")

    # 上位シグナルの詳細
    print("\n\n=== KPF風シグナル: 前走大頭数→今回少頭数の詳細 ===")
    detail_query = """
    WITH prev AS (
        SELECT horse_id, race_date,
               finish_position AS prev_pos,
               headcount AS prev_hc,
               distance AS prev_dist,
               course_type AS prev_course,
               popularity AS prev_pop,
               ROW_NUMBER() OVER (PARTITION BY horse_id ORDER BY race_date DESC) AS rn
        FROM horse_histories
    )
    SELECT
        ra.date, ra.venue, ra.course_type, ra.distance,
        e.popularity, e.odds,
        (SELECT COUNT(*) FROM entries e2 WHERE e2.race_id = e.race_id) AS headcount,
        r.finish_position,
        p.prev_pos, p.prev_hc, p.prev_pop,
        pay.payout AS fukusho_payout
    FROM entries e
    JOIN races ra ON ra.race_id = e.race_id
    JOIN results r ON r.race_id = e.race_id AND r.horse_id = e.horse_id
    LEFT JOIN prev p ON p.horse_id = e.horse_id AND p.race_date < ra.date AND p.rn = 1
    LEFT JOIN payouts pay ON pay.race_id = e.race_id
        AND pay.bet_type = '複勝'
        AND pay.combination = CAST(
            (SELECT horse_number FROM entries WHERE race_id = e.race_id AND horse_id = e.horse_id)
            AS TEXT
        )
    WHERE ra.date >= '2025-01-01'
      AND e.popularity >= 6
      AND p.prev_hc >= 16
      AND (SELECT COUNT(*) FROM entries e2 WHERE e2.race_id = e.race_id) <= 12
    ORDER BY ra.date
    """
    drows = conn.execute(detail_query).fetchall()
    if drows:
        total = len(drows)
        hits = [r for r in drows if r['finish_position'] and r['finish_position'] <= 3 and r['fukusho_payout']]
        total_pay = [r for r in drows if r['fukusho_payout'] is not None]
        psum = sum(r['fukusho_payout'] for r in hits)
        roi = psum / len(total_pay) if total_pay else 0
        print(f"前走16頭以上→今回12頭以下×6人気以上: {total}件, 複勝ROI={roi:.1f}円/100円, 的中率={len(hits)/len(total_pay)*100:.1f}%")
    else:
        print("データなし")

    conn.close()


def _class_up(r):
    """クラスアップ判定（簡易）"""
    order = ["未勝利", "1勝", "2勝", "3勝", "オープン", "リステッド", "G3", "G2", "G1"]
    pc = r['prev_class'] or ""
    cc = r['race_class'] or ""
    try:
        return r['popularity'] >= 6 and order.index(cc) > order.index(pc)
    except ValueError:
        return False


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else DB_PATH
    run(db)
