"""
config.py - システム全体の設定定数

ここに集約することで、設定変更が1ファイルで完結する。
"""

import os

# =========================================================
# データベース設定
# =========================================================
# DBファイルのパス（プロジェクトルートに配置）
DB_PATH = os.path.join(os.path.dirname(__file__), "keiba.db")

# =========================================================
# スクレイピング設定
# =========================================================
# リクエスト間のスリープ時間（秒）- サイト負荷軽減のため
SLEEP_MIN = 2.0  # 最小待機時間（秒）
SLEEP_MAX = 5.0  # 最大待機時間（秒）

# リトライ設定
MAX_RETRIES = 3          # 最大リトライ回数
RETRY_BACKOFF = 2.0      # 指数バックオフの基数（秒）

# リクエストタイムアウト（秒）
REQUEST_TIMEOUT = 30

# =========================================================
# netkeiba URL設定
# =========================================================
# レース一覧ページ（日付指定）- db.netkeiba.com は静的HTML
# 例: https://db.netkeiba.com/race/list/20240101/
RACE_LIST_BASE_URL = "https://db.netkeiba.com/race/list/"

# レース詳細ページ（race_id指定）
# 例: https://db.netkeiba.com/race/202401010101/
RACE_DETAIL_BASE_URL = "https://db.netkeiba.com/race/"

# robots.txt の確認先
ROBOTS_TXT_URLS = [
    "https://race.netkeiba.com/robots.txt",
    "https://db.netkeiba.com/robots.txt",
]

# =========================================================
# User-Agent ローテーション用リスト
# =========================================================
USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) "
        "Gecko/20100101 Firefox/121.0"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
]

# =========================================================
# レースフィルタリング設定
# =========================================================
# 除外するレース種別キーワード（新馬戦・障害レース）
EXCLUDE_RACE_KEYWORDS = [
    "新馬",
    "障害",
    "障害未勝利",
]

# 中央競馬（JRA）の競馬場コード（地方競馬除外に使用）
JRA_VENUE_CODES = {"01", "02", "03", "04", "05", "06", "07", "08", "09", "10"}

# 1開催日あたりの参加レース数上限
MAX_RACES_PER_DAY = 3
