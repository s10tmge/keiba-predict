"""
export_analysis.py - 分析用データをCSVエクスポート
python export_analysis.py
"""
import sqlite3, csv

conn = sqlite3.connect('keiba.db')
conn.row_factory = sqlite3.Row

rows = conn.execute("""
SELECT e.race_id, e.horse_number, e.popularity, e.odds, e.horse_weight_diff,
       ra.course_type, ra.distance, ra.date, ra.venue, ra.race_class,
       r.finish_position,
       (SELECT COUNT(*) FROM entries e2 WHERE e2.race_id=e.race_id) AS headcount,
       p.finish_position AS prev_pos, p.headcount AS prev_hc,
       p.distance AS prev_dist, p.course_type AS prev_course,
       p.popularity AS prev_pop,
       pay_f.payout AS fukusho_payout,
       pay_t.payout AS tansho_payout
FROM entries e
JOIN races ra ON ra.race_id=e.race_id
JOIN results r ON r.race_id=e.race_id AND r.horse_id=e.horse_id
LEFT JOIN horse_histories p
    ON p.horse_id=e.horse_id
    AND p.race_date=(
        SELECT MAX(race_date) FROM horse_histories
        WHERE horse_id=e.horse_id AND race_date<ra.date
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

print(f"出力: {len(rows)}件 → analysis_data.csv")
conn.close()
