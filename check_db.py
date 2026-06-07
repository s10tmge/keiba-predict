"""
check_db.py - DBの中身を確認する
python check_db.py
"""
import sqlite3
from collections import Counter

conn = sqlite3.connect('keiba.db')
conn.row_factory = sqlite3.Row

# レーステーブルのクラス・グレード分布
print("=== races テーブル: race_class / grade 分布 ===")
rows = conn.execute("""
    SELECT race_class, grade, COUNT(*) as cnt
    FROM races
    GROUP BY race_class, grade
    ORDER BY cnt DESC
    LIMIT 30
""").fetchall()
for r in rows:
    print(f"  class='{r['race_class']}'  grade='{r['grade']}'  {r['cnt']}件")

# 重賞っぽいレース名を直接確認
print("\n=== race_name に G1/G2/G3 を含むレース ===")
rows = conn.execute("""
    SELECT race_id, date, venue, race_name, race_class, grade
    FROM races
    WHERE race_name LIKE '%G1%' OR race_name LIKE '%G2%' OR race_name LIKE '%G3%'
       OR grade IN ('G1','G2','G3')
    ORDER BY date DESC
    LIMIT 20
""").fetchall()
for r in rows:
    print(f"  {r['date']} {r['venue']} {r['race_name']} class={r['race_class']} grade={r['grade']}")

# 有名重賞を直接検索
print("\n=== 有名重賞を検索 ===")
for name in ['安田記念', '日本ダービー', '天皇賞', '宝塚記念', '有馬記念']:
    rows = conn.execute(
        "SELECT race_id, date, race_name, race_class, grade FROM races WHERE race_name LIKE ?",
        (f'%{name}%',)
    ).fetchall()
    for r in rows:
        print(f"  {r['date']} {r['race_name']} class={r['race_class']} grade={r['grade']}")

print("\n=== 総レース数・期間 ===")
r = conn.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM races").fetchone()
print(f"  {r[0]}レース  {r[1]} 〜 {r[2]}")

conn.close()
