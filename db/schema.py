"""
db/schema.py - SQLiteスキーマ定義とDB初期化

テーブル構成:
  - races      : レース基本情報
  - horses     : 馬の基本情報
  - entries    : 出走情報（レースと馬の紐付け）
  - results    : レース結果
  - predictions: システムの予測ログ
"""

import sqlite3
import logging
from pathlib import Path
from config import DB_PATH

logger = logging.getLogger(__name__)

# =========================================================
# CREATE TABLE 文
# =========================================================

SQL_CREATE_RACES = """
CREATE TABLE IF NOT EXISTS races (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id        TEXT    NOT NULL UNIQUE,   -- netkeibaのレースID (例: 202401010101)
    date           TEXT    NOT NULL,           -- 開催日 (YYYY-MM-DD)
    venue          TEXT    NOT NULL,           -- 競馬場名 (例: 東京, 中山)
    race_number    INTEGER NOT NULL,           -- レース番号 (1〜12)
    race_name      TEXT,                       -- レース名 (例: 有馬記念)
    course_type    TEXT,                       -- コース種別 (芝/ダート)
    distance       INTEGER,                    -- 距離 (メートル)
    track_condition TEXT,                      -- 馬場状態 (良/稍重/重/不良)
    weather        TEXT,                       -- 天気 (晴/曇/雨/小雨/雪)
    race_class     TEXT,                       -- クラス (G1/G2/G3/オープン/3勝/2勝/1勝/未勝利 等)
    created_at     TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
)
"""

SQL_CREATE_HORSES = """
CREATE TABLE IF NOT EXISTS horses (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    horse_id   TEXT    NOT NULL UNIQUE,   -- netkeibaの馬ID
    name       TEXT    NOT NULL,           -- 馬名
    sex        TEXT,                       -- 性別 (牡/牝/セ)
    birthday   TEXT,                       -- 生年月日 (YYYY-MM-DD)
    created_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
)
"""

SQL_CREATE_ENTRIES = """
CREATE TABLE IF NOT EXISTS entries (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id           TEXT    NOT NULL,   -- races.race_id への参照
    horse_id          TEXT    NOT NULL,   -- horses.horse_id への参照
    jockey_name       TEXT,               -- 騎手名
    trainer_name      TEXT,               -- 調教師名
    frame_number      INTEGER,            -- 枠番 (1〜8)
    horse_number      INTEGER,            -- 馬番
    weight_carried    REAL,               -- 斤量 (kg)
    horse_weight      INTEGER,            -- 馬体重 (kg)
    horse_weight_diff INTEGER,            -- 馬体重増減 (kg)
    odds              REAL,               -- 単勝オッズ
    popularity        INTEGER,            -- 人気順位
    created_at        TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (race_id, horse_number)
)
"""

SQL_CREATE_RESULTS = """
CREATE TABLE IF NOT EXISTS results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id         TEXT    NOT NULL,   -- races.race_id への参照
    horse_id        TEXT    NOT NULL,   -- horses.horse_id への参照
    finish_position INTEGER,            -- 着順 (中止・除外の場合はNULL)
    finish_time     TEXT,               -- タイム (例: "1:33.5")
    margin          TEXT,               -- 着差 (例: "クビ", "1/2", "1")
    created_at      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (race_id, horse_id)
)
"""

SQL_CREATE_PREDICTIONS = """
CREATE TABLE IF NOT EXISTS predictions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id          TEXT    NOT NULL,   -- races.race_id への参照
    prediction_date  TEXT    NOT NULL,   -- 予測実行日 (YYYY-MM-DD)
    confidence_score REAL,               -- 自信度スコア (0.0〜1.0)
    bet_type         TEXT,               -- 券種 (馬連/3連複/単勝 等)
    bet_content      TEXT,               -- 買い目 (例: "3-5", "1-3-7")
    created_at       TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
)
"""

# インデックス作成（検索高速化）
SQL_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_races_date    ON races(date)",
    "CREATE INDEX IF NOT EXISTS idx_races_venue   ON races(venue)",
    "CREATE INDEX IF NOT EXISTS idx_entries_race  ON entries(race_id)",
    "CREATE INDEX IF NOT EXISTS idx_entries_horse ON entries(horse_id)",
    "CREATE INDEX IF NOT EXISTS idx_results_race  ON results(race_id)",
    "CREATE INDEX IF NOT EXISTS idx_results_horse ON results(horse_id)",
    "CREATE INDEX IF NOT EXISTS idx_predictions_race ON predictions(race_id)",
]

ALL_CREATE_STATEMENTS = [
    SQL_CREATE_RACES,
    SQL_CREATE_HORSES,
    SQL_CREATE_ENTRIES,
    SQL_CREATE_RESULTS,
    SQL_CREATE_PREDICTIONS,
    *SQL_CREATE_INDEXES,
]


# =========================================================
# 初期化関数
# =========================================================

def init_db(db_path: str = DB_PATH) -> None:
    """
    データベースを初期化する。

    DBファイルが存在しない場合は新規作成し、全テーブルを作成する。
    既存のテーブルは変更しない（IF NOT EXISTS）。

    Args:
        db_path: SQLiteファイルのパス（デフォルト: config.DB_PATH）
    """
    # DBファイルの親ディレクトリを作成
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"DBを初期化します: {db_path}")
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            for sql in ALL_CREATE_STATEMENTS:
                conn.execute(sql)
        logger.info("全テーブルの作成が完了しました。")
    finally:
        conn.close()


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    """
    SQLite接続を返す。

    Row Factoryを設定してdict風アクセスを可能にする。

    Args:
        db_path: SQLiteファイルのパス

    Returns:
        sqlite3.Connection オブジェクト
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # カラム名でアクセス可能にする
    conn.execute("PRAGMA journal_mode=WAL")   # 書き込みパフォーマンス向上
    conn.execute("PRAGMA foreign_keys=ON")    # 外部キー制約を有効化
    return conn
