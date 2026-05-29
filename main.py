"""
main.py - CLIエントリーポイント

使い方:
  python main.py init-db
  python main.py scrape --date 2024-01-01
  python main.py scrape --year 2024 --month 1
"""

import argparse
import logging
import sys
from datetime import date

# ロギング設定（INFOレベル以上をコンソール出力）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# =========================================================
# サブコマンド実装
# =========================================================

def cmd_init_db(args: argparse.Namespace) -> int:
    """DBを初期化してテーブルを作成する。"""
    from db.schema import init_db
    init_db()
    print("データベースの初期化が完了しました。")
    return 0


def cmd_scrape(args: argparse.Namespace) -> int:
    """
    レースデータをスクレイピングしてDBに保存する。

    --date を指定した場合: その日付1日分
    --year と --month を指定した場合: その月の全開催日分
    """
    import sqlite3
    from db.schema import get_connection, init_db
    from scraper.race_list import RaceListScraper
    from scraper.race_detail import RaceDetailScraper

    # DBが未初期化でも動くよう初期化を試みる
    init_db()

    list_scraper = RaceListScraper()
    detail_scraper = RaceDetailScraper()

    # 対象日付リストを決定
    target_dates: list[date] = []

    if args.date:
        try:
            target_dates = [date.fromisoformat(args.date)]
        except ValueError:
            print(f"エラー: 日付の形式が不正です（YYYY-MM-DD）: {args.date}", file=sys.stderr)
            return 1
    elif args.year and args.month:
        # 月単位: race_list スクレイパーの fetch_month は内部で日付走査する
        # ここでは1日ずつ取得するため日付リストを生成
        from datetime import timedelta
        year, month = args.year, args.month
        start = date(year, month, 1)
        end = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year + 1, 1, 1) - timedelta(days=1)
        current = start
        while current <= end:
            target_dates.append(current)
            current += timedelta(days=1)
    else:
        print("エラー: --date または --year と --month を指定してください。", file=sys.stderr)
        return 1

    conn = get_connection()
    total_races = 0

    try:
        for target_date in target_dates:
            logger.info(f"=== {target_date} のスクレイピング開始 ===")
            try:
                race_list = list_scraper.fetch(target_date)
            except Exception as exc:
                logger.warning(f"{target_date} のレース一覧取得に失敗: {exc}")
                continue

            for race_info in race_list:
                race_id = race_info.race_id
                logger.info(f"レース詳細取得中: {race_id} ({race_info.venue} {race_info.race_number}R)")

                # races テーブルへ保存
                try:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO races
                          (race_id, date, venue, race_number, race_name, course_type, distance, race_class)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            race_id,
                            race_info.date.strftime("%Y-%m-%d"),
                            race_info.venue,
                            race_info.race_number,
                            race_info.race_name,
                            race_info.course_type,
                            race_info.distance,
                            race_info.race_class,
                        ),
                    )
                    conn.commit()
                except sqlite3.Error as exc:
                    logger.error(f"races INSERT失敗 ({race_id}): {exc}")
                    continue

                # レース詳細を取得
                try:
                    detail = detail_scraper.fetch(race_id)
                except Exception as exc:
                    logger.warning(f"レース詳細取得に失敗 ({race_id}): {exc}")
                    continue

                # 馬場・天気を races テーブルへ更新
                conn.execute(
                    "UPDATE races SET track_condition=?, weather=? WHERE race_id=?",
                    (detail.track_condition, detail.weather, race_id),
                )

                # entries & horses & results を保存
                for entry in detail.entries:
                    # horses テーブル（存在しなければ INSERT）
                    conn.execute(
                        "INSERT OR IGNORE INTO horses (horse_id, name) VALUES (?, ?)",
                        (entry.horse_id, entry.horse_name),
                    )
                    # entries テーブル
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO entries
                          (race_id, horse_id, jockey_name, trainer_name,
                           frame_number, horse_number, weight_carried,
                           horse_weight, horse_weight_diff, odds, popularity)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            race_id,
                            entry.horse_id,
                            entry.jockey_name,
                            entry.trainer_name,
                            entry.frame_number,
                            entry.horse_number,
                            entry.weight_carried,
                            entry.horse_weight,
                            entry.horse_weight_diff,
                            entry.odds,
                            entry.popularity,
                        ),
                    )

                for result in detail.results:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO results
                          (race_id, horse_id, finish_position, finish_time, margin)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            race_id,
                            result.horse_id,
                            result.finish_position,
                            result.finish_time,
                            result.margin,
                        ),
                    )

                conn.commit()
                total_races += 1
                logger.info(f"保存完了: {race_id}")

    finally:
        conn.close()

    print(f"スクレイピング完了。保存レース数: {total_races}")
    return 0


# =========================================================
# CLI定義
# =========================================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="keiba-predict",
        description="競馬予想・データ収集システム",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # init-db サブコマンド
    subparsers.add_parser("init-db", help="SQLiteデータベースを初期化する")

    # scrape サブコマンド
    scrape_parser = subparsers.add_parser("scrape", help="レースデータをスクレイピングしてDBに保存する")
    scrape_group = scrape_parser.add_mutually_exclusive_group()
    scrape_group.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        help="スクレイピング対象日 (例: 2024-01-01)",
    )
    scrape_parser.add_argument("--year", type=int, metavar="YYYY", help="対象年（--monthと組み合わせて使用）")
    scrape_parser.add_argument("--month", type=int, metavar="M", help="対象月 1〜12（--yearと組み合わせて使用）")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "init-db":
        return cmd_init_db(args)
    elif args.command == "scrape":
        return cmd_scrape(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
