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
    race_id           TEXT    NOT NULL,
    horse_id          TEXT    NOT NULL,
    jockey_name       TEXT,
    trainer_name      TEXT,
    frame_number      INTEGER,
    horse_number      INTEGER,
    weight_carried    REAL,
    horse_weight      INTEGER,
    horse_weight_diff INTEGER,
    odds              REAL,
    popularity        INTEGER,
    last_3f           REAL,               -- 上がり3ハロン (秒)
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

SQL_CREATE_HORSE_HISTORIES = """
CREATE TABLE IF NOT EXISTS horse_histories (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    horse_id        TEXT    NOT NULL,
    race_date       TEXT    NOT NULL,     -- YYYY-MM-DD
    venue           TEXT,
    race_name       TEXT,
    race_class      TEXT,                 -- G1/G2/G3/OP/3勝/2勝/1勝/未勝利
    course_type     TEXT,                 -- 芝/ダート
    distance        INTEGER,
    track_condition TEXT,                 -- 良/稍重/重/不良
    headcount       INTEGER,              -- 出走頭数
    frame_number    INTEGER,
    horse_number    INTEGER,
    popularity      INTEGER,
    odds            REAL,
    finish_position INTEGER,
    finish_time     TEXT,
    last_3f         REAL,                 -- 上がり3ハロン
    horse_weight    INTEGER,
    horse_weight_diff INTEGER,
    jockey_name     TEXT,
    UNIQUE (horse_id, race_date, race_name)
)
"""

SQL_CREATE_PAYOUTS = """
CREATE TABLE IF NOT EXISTS payouts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id       TEXT    NOT NULL,
    bet_type      TEXT    NOT NULL,   -- 単勝/複勝/枠連/馬連/ワイド/馬単/三連複/三連単
    combination   TEXT    NOT NULL,   -- 馬番の組み合わせ (例: "3", "3-5", "1-3-7")
    payout        INTEGER NOT NULL,   -- 払戻金額 (100円あたり)
    popularity    INTEGER,            -- 人気順位
    UNIQUE (race_id, bet_type, combination)
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
    SQL_CREATE_HORSE_HISTORIES,
    SQL_CREATE_PAYOUTS,
    SQL_CREATE_PREDICTIONS,
    *SQL_CREATE_INDEXES,
    "CREATE INDEX IF NOT EXISTS idx_horse_hist_horse ON horse_histories(horse_id)",
    "CREATE INDEX IF NOT EXISTS idx_horse_hist_date  ON horse_histories(race_date)",
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


def save_race_list(races, db_path: str = DB_PATH) -> None:
    """RaceInfo リストをracesテーブルに保存する（重複は無視）。"""
    conn = get_connection(db_path)
    try:
        with conn:
            for r in races:
                conn.execute(
                    """INSERT OR IGNORE INTO races
                       (race_id, date, venue, race_number, race_name, course_type, distance, race_class)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (r.race_id, r.date.isoformat(), r.venue, r.race_number,
                     r.race_name, r.course_type, r.distance, r.race_class),
                )
    finally:
        conn.close()


def save_race_detail(detail, db_path: str = DB_PATH) -> None:
    """RaceDetail をentries・results・racesテーブルに保存する（重複は無視）。"""
    conn = get_connection(db_path)
    try:
        with conn:
            # 馬場・天気をracesに反映
            conn.execute(
                "UPDATE races SET track_condition=?, weather=? WHERE race_id=?",
                (detail.track_condition, detail.weather, detail.race_id),
            )
            for e in detail.entries:
                conn.execute(
                    """INSERT OR IGNORE INTO horses (horse_id, name) VALUES (?,?)""",
                    (e.horse_id, e.horse_name),
                )
                conn.execute(
                    """INSERT OR IGNORE INTO entries
                       (race_id, horse_id, jockey_name, trainer_name, frame_number,
                        horse_number, weight_carried, horse_weight, horse_weight_diff,
                        odds, popularity)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (detail.race_id, e.horse_id, e.jockey_name, e.trainer_name,
                     e.frame_number, e.horse_number, e.weight_carried,
                     e.horse_weight, e.horse_weight_diff, e.odds, e.popularity),
                )
            for r in detail.results:
                conn.execute(
                    """INSERT OR IGNORE INTO results
                       (race_id, horse_id, finish_position, finish_time, margin)
                       VALUES (?,?,?,?,?)""",
                    (detail.race_id, r.horse_id, r.finish_position,
                     r.finish_time, r.margin),
                )
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
