"""
debug_horse.py - 馬ページのHTMLを確認するデバッグスクリプト
プロジェクトフォルダで実行: python debug_horse.py
"""
import sqlite3
import requests
from bs4 import BeautifulSoup

# DBから馬IDを1件取得
conn = sqlite3.connect('keiba.db')
horse_id = conn.execute("SELECT horse_id FROM horses LIMIT 1").fetchone()[0]
conn.close()

print(f"馬ID: {horse_id}")
url = f"https://db.netkeiba.com/horse/{horse_id}/"
resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
resp.encoding = 'euc-jp'
soup = BeautifulSoup(resp.text, 'lxml')

# テーブル一覧
print("\n=== テーブル一覧 ===")
for t in soup.find_all('table'):
    print(f"  class={t.get('class')}  rows={len(t.find_all('tr'))}")

# ヘッダー行
print("\n=== 一番行数多いテーブルのヘッダー ===")
tables = soup.find_all('table')
if tables:
    biggest = max(tables, key=lambda t: len(t.find_all('tr')))
    headers = [th.get_text(strip=True) for th in biggest.select('tr:first-child th, tr:first-child td')]
    print(headers)
    print("\n最初のデータ行:")
    rows = biggest.select('tr')
    if len(rows) > 1:
        cols = rows[1].select('td')
        print([c.get_text(strip=True) for c in cols])
