"""
debug_fetch.py - 実際のHTMLを確認するデバッグ用スクリプト

使い方:
  python debug_fetch.py 20230108

HTMLをdebug_output/フォルダに保存し、見つかったレースリンクを表示する。
"""

import re
import sys
import os
import time
import random
import requests
from bs4 import BeautifulSoup

DATE = sys.argv[1] if len(sys.argv) > 1 else "20230108"

os.makedirs("debug_output", exist_ok=True)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Safari/537.36")

url = f"https://db.netkeiba.com/race/list/{DATE}/"
print(f"取得中: {url}")

time.sleep(random.uniform(2, 4))
resp = requests.get(url, headers={"User-Agent": UA}, timeout=30)
print(f"ステータス: {resp.status_code}")
print(f"文字コード: {resp.encoding}")

out_path = f"debug_output/race_list_{DATE}.html"
with open(out_path, "w", encoding="utf-8") as f:
    f.write(resp.text)
print(f"HTML保存先: {out_path}")
print(f"HTMLサイズ: {len(resp.text)} 文字")
print()

soup = BeautifulSoup(resp.text, "lxml")

# レースリンクを探す
race_links = soup.find_all("a", href=re.compile(r"/race/\d{12}/"))
print(f"=== /race/XXXXXXXXXXXX/ 形式のリンク: {len(race_links)}件 ===")
for lnk in race_links[:20]:
    print(f"  {lnk['href']}  |  {lnk.get_text(strip=True)}")

# それ以外のraceリンクも確認
other_links = soup.find_all("a", href=re.compile(r"/race/"))
print(f"\n=== /race/ を含む全リンク（最初の20件）: {len(other_links)}件 ===")
for lnk in other_links[:20]:
    print(f"  {lnk['href']}  |  {lnk.get_text(strip=True)[:40]}")

# ページタイトル確認
title = soup.find("title")
print(f"\nページタイトル: {title.get_text() if title else '不明'}")
