"""
export_analysis.py - 分析用データをCSVエクスポート（v3: グレード判定追加）
python export_analysis.py
python export_analysis.py --grade G1    # 重賞のみ
python export_analysis.py --grade all   # 全レース（デフォルト）
"""
import sqlite3, csv, argparse, re

parser = argparse.ArgumentParser()
parser.add_argument('--grade', default='all', help='all / G1 / G2 / G3 / 重賞')
args = parser.parse_args()

conn = sqlite3.connect('keiba.db')
conn.row_factory = sqlite3.Row

def detect_grade(race_name: str) -> str:
    """race_nameからグレードを判定する（DBのrace_classが空のため）"""
    if not race_name:
        return ''
    for g in ['G1', 'G2', 'G3']:
        if f'({g})' in race_name or f'（{g}）' in race_name:
            return g
    if '(L)' in race_name or '（L）' in race_name:
        return 'L'
    return ''

# グレードフィルター条件
if args.grade == 'all':
    grade_filter = ''
elif args.grade == '重賞':
    grade_filter = "AND (ra.race_name LIKE '%(G1)%' OR ra.race_name LIKE '%(G2)%' OR ra.race_name LIKE '%(G3)%' OR ra.race_name LIKE '%（G1）%' OR ra.race_name LIKE '%（G2）%' OR ra.race_name LIKE '%（G3）%')"
else:
    grade_filter = f"AND (ra.race_name LIKE '%({args.grade})%' OR ra.race_name LIKE '%（{args.grade}）%')"

# 1. メインデータ
rows = conn.execute(f"""
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
    ra.race_name,
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
    -- 払戻（単勝・複勝・馬連・三連複）
    pay_t.payout  AS tansho_payout,
    pay_f.payout  AS fukusho_payout,
    pay_u.payout  AS umaren_payout,
    pay_s.payout  AS sanrenfuku_payout
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
LEFT JOIN payouts pay_t ON pay_t.race_id=e.race_id
    AND pay_t.bet_type='単勝'
    AND pay_t.combination=CAST(e.horse_number AS TEXT)
LEFT JOIN payouts pay_f ON pay_f.race_id=e.race_id
    AND pay_f.bet_type='複勝'
    AND pay_f.combination=CAST(e.horse_number AS TEXT)
-- 馬連・三連複は組み合わせが複数あるため1着馬番を含む最小払戻を取得
LEFT JOIN payouts pay_u ON pay_u.race_id=e.race_id
    AND pay_u.bet_type='馬連'
    AND pay_u.combination LIKE '%' || CAST(e.horse_number AS TEXT) || '%'
    AND r.finish_position=1
LEFT JOIN payouts pay_s ON pay_s.race_id=e.race_id
    AND pay_s.bet_type='三連複'
    AND pay_s.combination LIKE '%' || CAST(e.horse_number AS TEXT) || '%'
    AND r.finish_position=1
WHERE ra.date>='2025-01-01'
  AND p.finish_position IS NOT NULL
  {grade_filter}
""").fetchall()

# gradeカラムを追加してCSV出力
suffix = f'_{args.grade}' if args.grade != 'all' else ''
outfile = f'analysis_data{suffix}.csv'

with open(outfile, 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.writer(f)
    if rows:
        keys = list(rows[0].keys()) + ['grade']
        w.writerow(keys)
        for row in rows:
            grade = detect_grade(row['race_name'])
            w.writerow(list(row) + [grade])

print(f"メインデータ: {len(rows)}件 → {outfile}")

# 2. レース内の上がり3F統計
race_3f = conn.execute("""
SELECT race_id, AVG(last_3f) AS avg_3f, MIN(last_3f) AS min_3f,
       COUNT(CASE WHEN last_3f IS NOT NULL THEN 1 END) AS cnt_3f
FROM entries WHERE last_3f IS NOT NULL GROUP BY race_id
""").fetchall()

with open('race_3f_stats.csv', 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.writer(f)
    w.writerow(['race_id','avg_3f','min_3f','cnt_3f'])
    w.writerows(race_3f)
print(f"レース3F統計: {len(race_3f)}件 → race_3f_stats.csv")

# 3. 騎手×コース成績
jockey_stats = conn.execute("""
SELECT e.jockey_name, ra.course_type,
       COUNT(*) AS total,
       SUM(CASE WHEN r.finish_position=1 THEN 1 ELSE 0 END) AS wins,
       SUM(CASE WHEN r.finish_position<=3 THEN 1 ELSE 0 END) AS top3
FROM entries e
JOIN races ra ON ra.race_id=e.race_id
JOIN results r ON r.race_id=e.race_id AND r.horse_id=e.horse_id
WHERE ra.date>='2024-01-01' AND e.jockey_name IS NOT NULL AND e.jockey_name != ''
GROUP BY e.jockey_name, ra.course_type HAVING COUNT(*) >= 20
""").fetchall()

with open('jockey_stats.csv', 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.writer(f)
    w.writerow(['jockey_name','course_type','total','wins','top3'])
    w.writerows(jockey_stats)
print(f"騎手統計: {len(jockey_stats)}件 → jockey_stats.csv")

conn.close()
print("完了")
