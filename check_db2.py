import sqlite3
conn = sqlite3.connect('keiba.db')
conn.row_factory = sqlite3.Row

print('=== horse_histories カラム ===')
for c in conn.execute('PRAGMA table_info(horse_histories)').fetchall():
    print(f'  {c["name"]} ({c["type"]})')

r = conn.execute('SELECT COUNT(*), COUNT(last_3f) FROM horse_histories').fetchone()
print(f'\nhorse_histories: 総{r[0]}件 / last_3f有{r[1]}件')

r = conn.execute('SELECT COUNT(*), COUNT(last_3f) FROM entries').fetchone()
print(f'entries: 総{r[0]}件 / last_3f有{r[1]}件')

r = conn.execute("""
SELECT COUNT(*) FROM entries e
JOIN races ra ON ra.race_id=e.race_id
WHERE ra.race_name LIKE '%(G1)%' OR ra.race_name LIKE '%(G2)%' OR ra.race_name LIKE '%(G3)%'
""").fetchone()
print(f'重賞entries: {r[0]}件')

# horse_historiesのサンプル
print('\n=== horse_histories サンプル3件 ===')
for r in conn.execute('SELECT * FROM horse_histories LIMIT 3').fetchall():
    print(dict(r))

conn.close()
