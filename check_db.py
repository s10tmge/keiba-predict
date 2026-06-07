"""
check_db.py - DBの中身を確認する
python check_db.py
"""
import sqlite3

conn = sqlite3.connect('keiba.db')
conn.row_factory = sqlite3.Row

# テーブル一覧とカラム確認
print("=== racesテーブルのカラム ===")
cols = conn.execute("PRAGMA table_info(races)").fetchall()
for c in cols:
    print(f"  {c['name']} ({c['type']})")

# レースクラス分布
print("\n=== race_class 分布 ===")
rows = conn.execute("""
    SELECT race_class, COUNT(*) as cnt
    FROM races
    GROUP BY race_class
    ORDER BY cnt DESC
    LIMIT 30
""").fetchall()
for r in rows:
    print(f"  '{r['race_class']}': {r['cnt']}件")

# 有名重賞を検索
print("\n=== 有名重賞を検索 ===")
for name in ['安田記念', '日本ダービー', '天皇賞', '宝塚記念', '有馬記念', '皐月賞']:
    rows = conn.execute(
        "SELECT race_id, date, race_name, race_class FROM races WHERE race_name LIKE ?",
        (f'%{name}%',)
    ).fetchall()
    for r in rows:
        print(f"  {r['date']} {r['race_name']} class='{r['race_class']}'")

print("\n=== 総レース数・期間 ===")
r = conn.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM races").fetchone()
print(f"  {r[0]}レース  {r[1]} 〜 {r[2]}")

conn.close()
