"""
scraper パッケージ - netkeibaスクレイピングモジュール

使用方針:
  - requests + BeautifulSoup を主軸とする（シンプル・高速）
  - JavaScriptレンダリングが必要な場合は Selenium/Playwright を別途使用
  - リクエスト間に必ずスリープを入れてサイト負荷を軽減する
"""
