"""
export_analysis.py - 分析用データをCSVエクスポート（v2: 能力指標付き）
python export_analysis.py
"""
import sqlite3, csv

conn = sqlite3.connect('keiba.db')
conn.row_factory = sqlite3.Row

# 1. メインデータ（前走情報 + 騎手名 + 馬ID）
rows = conn.execute("""
SELECT
    e.race_id,
    e.horse_id,
    e.horse_number,
    e.jockey_name,
    e.popularity,
    e.odds,
    e.horse_weight_diff,
    e.last_3f,
    ra.course_type,
    ra.distance,
    ra.date,
    ra.venue,
    ra.race_class,
    ra.track_condition,
    r.finish_position,
    (SELECT COUNT(*) FROM entries e2 WHERE e2.race_id=e.race_id) AS headcount,
    -- 前走情報
    p.finish_position   AS prev_pos,
    p.headcount         AS prev_hc,
    p.distance          AS prev_dist,
    p.course_type       AS prev_course,
    p.popularity        AS prev_pop,
    p.last_3f           AS prev_last3f,
    p.race_class        AS prev_class,
    p.track_condition   AS prev_cond,
    -- 2走前
    p2.finish_position  AS prev2_pos,
    p2.popularity       AS prev2_pop,
    p2.course_type      AS prev2_course,
    -- 払戻
    pay_f.payout AS fukusho_payout,
    pay_t.payout AS tansho_payout
FROM entries e
JOIN races ra ON ra.race_id=e.race_id
JOIN results r ON r.race_id=e.race_id AND r.horse_id=e.horse_id
LEFT JOIN horse_histories p
    ON p.horse_id=e.horse_id
    AND p.race_date=(
        SELECT MAX(race_date) FROM horse_histories
        WHERE horse_id=e.horse_id AND race_date < ra.date
    )
LEFT JOIN horse_histories p2
    ON p2.horse_id=e.horse_id
    AND p2.race_date=(
        SELECT MAX(race_date) FROM horse_histories
        WHERE horse_id=e.horse_id
          AND race_date < (
              SELECT MAX(race_date) FROM horse_histories
              WHERE horse_id=e.horse_id AND race_date < ra.date
          )
    )
LEFT JOIN payouts pay_f ON pay_f.race_id=e.race_id
    AND pay_f.bet_type='複勝'
    AND pay_f.combination=CAST(e.horse_number AS TEXT)
LEFT JOIN payouts pay_t ON pay_t.race_id=e.race_id
    AND pay_t.bet_type='単勝'
    AND pay_t.combination=CAST(e.horse_number AS TEXT)
WHERE ra.date>='2025-01-01'
  AND p.finish_position IS NOT NULL
""").fetchall()

with open('analysis_data.csv', 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.writer(f)
    if rows:
        w.writerow(rows[0].keys())
        w.writerows(rows)
print(f"メインデータ: {len(rows)}件 → analysis_data.csv")

# 2. レース内の上がり3F平均・標準偏差（同レースでの相対評価用）
race_3f = conn.execute("""
SELECT
    race_id,
    AVG(last_3f)                        AS avg_3f,
    MIN(last_3f)                        AS min_3f,
    COUNT(CASE WHEN last_3f IS NOT NULL THEN 1 END) AS cnt_3f
FROM entries
WHERE last_3f IS NOT NULL
GROUP BY race_id
""").fetchall()

with open('race_3f_stats.csv', 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.writer(f)
    w.writerow(['race_id','avg_3f','min_3f','cnt_3f'])
    w.writerows(race_3f)
print(f"レース3F統計: {len(race_3f)}件 → race_3f_stats.csv")

# 3. 騎手×コース成績（2024-2025）
jockey_stats = conn.execute("""
SELECT
    e.jockey_name,
    ra.course_type,
    COUNT(*) AS total,
    SUM(CASE WHEN r.finish_position=1 THEN 1 ELSE 0 END) AS wins,
    SUM(CASE WHEN r.finish_position<=3 THEN 1 ELSE 0 END) AS top3
FROM entries e
JOIN races ra ON ra.race_id=e.race_id
JOIN results r ON r.race_id=e.race_id AND r.horse_id=e.horse_id
WHERE ra.date>='2024-01-01'
  AND e.jockey_name IS NOT NULL AND e.jockey_name != ''
GROUP BY e.jockey_name, ra.course_type
HAVING COUNT(*) >= 20
""").fetchall()

with open('jockey_stats.csv', 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.writer(f)
    w.writerow(['jockey_name','course_type','total','wins','top3'])
    w.writerows(jockey_stats)
print(f"騎手統計: {len(jockey_stats)}件 → jockey_stats.csv")

conn.close()
print("完了")
