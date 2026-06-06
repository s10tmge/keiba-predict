"""
analysis/maegashira_analysis.py - 前走データを使った高倍率3着以内パターン分析

高倍率（6人気以上）で3着以内に来た馬の前走特徴を抽出し、
再現性のあるシグナルを探す。
"""

import sqlite3
import sys
from collections import defaultdict
from config import DB_PATH


def run(db_path: str = DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    print("=== 前走データ付き高倍率好走分析 ===\n")

    # 2025年の6人気以上で3着以内に入った馬エントリを取得
    # entries + results + horse_histories (直前レース) を結合
    query = """
    WITH target AS (
        -- 6人気以上で複勝圏内に入った出走
        SELECT
            e.race_id,
            e.horse_id,
            e.popularity,
            e.odds,
            e.horse_weight,
            e.horse_weight_diff,
            e.last_3f,
            r.finish_position,
            ra.course_type,
            ra.distance,
            ra.track_condition,
            ra.venue,
            ra.date,
            (SELECT COUNT(*) FROM entries e2 WHERE e2.race_id = e.race_id) AS headcount
        FROM entries e
        JOIN results r ON r.race_id = e.race_id AND r.horse_id = e.horse_id
        JOIN races ra ON ra.race_id = e.race_id
        WHERE e.popularity >= 6
          AND r.finish_position <= 3
          AND ra.date >= '2025-01-01'
    ),
    -- 各出走の直前レース履歴を取得
    prev AS (
        SELECT
            h.horse_id,
            h.race_date,
            h.finish_position AS prev_pos,
            h.headcount AS prev_hc,
            h.distance AS prev_dist,
            h.course_type AS prev_course,
            h.popularity AS prev_pop,
            h.last_3f AS prev_3f,
            h.race_class AS prev_class,
            ROW_NUMBER() OVER (PARTITION BY h.horse_id ORDER BY h.race_date DESC) AS rn
        FROM horse_histories h
    )
    SELECT
        t.*,
        p.prev_pos,
        p.prev_hc,
        p.prev_dist,
        p.prev_course,
        p.prev_pop,
        p.prev_3f,
        p.prev_class
    FROM target t
    LEFT JOIN prev p ON p.horse_id = t.horse_id
        AND p.race_date < t.date
        AND p.rn = 1
    WHERE p.prev_pos IS NOT NULL
    """

    rows = conn.execute(query).fetchall()
    print(f"対象レコード数: {len(rows)}件（6人気以上3着以内、前走あり）\n")

    if not rows:
        print("データなし")
        conn.close()
        return

    # 特徴分布を集計
    analyze_features(rows)

    # 全体ベースライン（6人気以上で3着以内に来る確率）
    total_entries = conn.execute("""
        SELECT COUNT(*) FROM entries e
        JOIN races ra ON ra.race_id = e.race_id
        WHERE e.popularity >= 6 AND ra.date >= '2025-01-01'
    """).fetchone()[0]

    baseline_rate = len(rows) / total_entries if total_entries else 0
    print(f"\n=== ベースライン ===")
    print(f"6人気以上出走: {total_entries}件")
    print(f"6人気以上3着以内: {len(rows)}件 ({baseline_rate:.1%})")

    # シグナル別ROI分析
    print("\n=== シグナル別分析 ===")
    analyze_signals(rows, total_entries, conn)

    conn.close()


def analyze_features(rows):
    """前走特徴の分布を表示"""
    print("--- 前走着順分布 ---")
    pos_dist = defaultdict(int)
    for r in rows:
        pos = r['prev_pos']
        if pos:
            bucket = f"{pos}着" if pos <= 5 else "6着以下"
            pos_dist[bucket] += 1
    for k, v in sorted(pos_dist.items()):
        print(f"  {k}: {v}件")

    print("\n--- 前走頭数分布 ---")
    hc_dist = defaultdict(int)
    for r in rows:
        hc = r['prev_hc']
        if hc:
            bucket = "≤8" if hc <= 8 else "9-12" if hc <= 12 else "13-16" if hc <= 16 else "17+"
            hc_dist[bucket] += 1
    for k, v in sorted(hc_dist.items()):
        print(f"  {k}: {v}件")

    print("\n--- 今回頭数分布 ---")
    hc_dist2 = defaultdict(int)
    for r in rows:
        hc = r['headcount']
        if hc:
            bucket = "≤8" if hc <= 8 else "9-12" if hc <= 12 else "13-16" if hc <= 16 else "17+"
            hc_dist2[bucket] += 1
    for k, v in sorted(hc_dist2.items()):
        print(f"  {k}: {v}件")

    print("\n--- 前走→今回コース変化 ---")
    course_chg = defaultdict(int)
    for r in rows:
        pc, cc = r['prev_course'], r['course_type']
        course_chg[f"{pc}→{cc}"] += 1
    for k, v in sorted(course_chg.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}件")

    print("\n--- 距離変化分布 ---")
    dist_chg = defaultdict(int)
    for r in rows:
        pd, cd = r['prev_dist'], r['distance']
        if pd and cd:
            diff = cd - pd
            bucket = "短縮-200以上" if diff <= -200 else "短縮" if diff < 0 else "同距離" if diff == 0 else "延長+200以上" if diff >= 200 else "延長"
            dist_chg[bucket] += 1
    for k, v in sorted(dist_chg.items()):
        print(f"  {k}: {v}件")


def analyze_signals(rows, total_6up, conn, min_samples=20):
    """複数シグナルの組み合わせでROIを計算"""

    signals = []

    # 前走着順×頭数変化×コース
    def prev_pos_bucket(p):
        if p is None: return None
        return "前走1-3着" if p <= 3 else "前走4-5着" if p <= 5 else "前走6着以下"

    def hc_change(prev_hc, curr_hc):
        if not prev_hc or not curr_hc: return None
        diff = curr_hc - prev_hc
        return "頭数増加" if diff >= 3 else "頭数減少" if diff <= -3 else "頭数同程度"

    def dist_change(prev_d, curr_d):
        if not prev_d or not curr_d: return None
        diff = curr_d - prev_d
        return "短縮" if diff <= -200 else "延長" if diff >= 200 else "同距離"

    # シグナルグループ集計
    groups = defaultdict(lambda: {"hit": 0, "total": 0, "odds_sum": 0.0})

    for r in rows:
        pp = prev_pos_bucket(r['prev_pos'])
        hcc = hc_change(r['prev_hc'], r['headcount'])
        dc = dist_change(r['prev_dist'], r['distance'])
        course = r['course_type']

        combos = [
            f"前走{r['prev_pos']}着以内|{course}" if r['prev_pos'] and r['prev_pos'] <= 3 else None,
            f"{pp}|{course}" if pp else None,
            f"{pp}|{hcc}" if pp and hcc else None,
            f"{hcc}|{course}" if hcc else None,
            f"前走人気{r['prev_pop']}以下|{course}" if r['prev_pop'] else None,
            f"前走1-3着|{dc}|{course}" if r['prev_pos'] and r['prev_pos'] <= 3 and dc else None,
        ]

        for combo in combos:
            if combo:
                groups[combo]["hit"] += 1
                groups[combo]["odds_sum"] += (r['odds'] or 0)

    # ベースライン全体エントリからシグナル別エントリ数を取得
    all_entries_query = """
        SELECT e.horse_id, e.race_id, e.popularity, e.odds,
               ra.course_type, ra.date, ra.distance,
               (SELECT COUNT(*) FROM entries e2 WHERE e2.race_id = e.race_id) AS headcount
        FROM entries e
        JOIN races ra ON ra.race_id = e.race_id
        WHERE e.popularity >= 6 AND ra.date >= '2025-01-01'
    """
    all_entries = conn.execute(all_entries_query).fetchall()

    print(f"\n{'シグナル':<35} {'ヒット':>6} {'的中率':>7} {'平均オッズ':>9}")
    print("-" * 65)

    results = []
    for signal, data in groups.items():
        hits = data["hit"]
        if hits < min_samples:
            continue
        avg_odds = data["odds_sum"] / hits if hits > 0 else 0
        # 単勝ROI推定: 的中率 × 平均オッズ
        # ここでは hit率のみ表示（全体エントリ数が信号別にわからないため）
        results.append((signal, hits, avg_odds))

    results.sort(key=lambda x: x[1] * x[2], reverse=True)
    for signal, hits, avg_odds in results[:20]:
        hit_rate = hits / len(rows) if rows else 0
        pseudo_roi = hit_rate * avg_odds * 100
        print(f"{signal:<35} {hits:>6} {hit_rate:>6.1%} {avg_odds:>8.1f}倍")

    # 前走着順別の複勝ROI（実払戻使用）
    print("\n\n=== 前走着順 × コース × 今回人気帯 別 複勝ROI（実払戻） ===")
    roi_query = """
    WITH target AS (
        SELECT
            e.race_id,
            e.horse_id,
            e.popularity,
            e.odds,
            r.finish_position,
            ra.course_type,
            ra.date,
            (SELECT COUNT(*) FROM entries e2 WHERE e2.race_id = e.race_id) AS headcount
        FROM entries e
        JOIN results r ON r.race_id = e.race_id AND r.horse_id = e.horse_id
        JOIN races ra ON ra.race_id = e.race_id
        WHERE e.popularity >= 6
          AND ra.date >= '2025-01-01'
    ),
    prev AS (
        SELECT
            h.horse_id,
            h.race_date,
            h.finish_position AS prev_pos,
            h.headcount AS prev_hc,
            h.course_type AS prev_course,
            ROW_NUMBER() OVER (PARTITION BY h.horse_id ORDER BY h.race_date DESC) AS rn
        FROM horse_histories h
    ),
    combined AS (
        SELECT
            t.*,
            p.prev_pos,
            p.prev_hc,
            p.prev_course,
            CASE WHEN t.finish_position <= 3 THEN 1 ELSE 0 END AS hit
        FROM target t
        LEFT JOIN prev p ON p.horse_id = t.horse_id
            AND p.race_date < t.date AND p.rn = 1
        WHERE p.prev_pos IS NOT NULL
    )
    SELECT
        CASE WHEN prev_pos <= 3 THEN '前走1-3着' ELSE '前走4着以下' END AS prev_grp,
        course_type,
        CASE WHEN popularity <= 8 THEN '6-8人気' ELSE '9人気以上' END AS pop_grp,
        COUNT(*) AS total,
        SUM(hit) AS hits,
        ROUND(100.0 * SUM(hit) / COUNT(*), 1) AS hit_rate
    FROM combined
    GROUP BY prev_grp, course_type, pop_grp
    HAVING COUNT(*) >= 20
    ORDER BY hit_rate DESC
    """

    rows2 = conn.execute(roi_query).fetchall()
    print(f"{'前走':^10} {'コース':^6} {'人気':^8} {'出走':>5} {'的中':>5} {'的中率':>7}")
    print("-" * 55)
    for row in rows2:
        print(f"{row['prev_grp']:^10} {row['course_type']:^6} {row['pop_grp']:^8} "
              f"{row['total']:>5} {row['hits']:>5} {row['hit_rate']:>6.1f}%")


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else DB_PATH
    run(db)
