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
    """レースデータをスクレイピングしてDBに保存する。新馬・障害は除外。"""
    import sqlite3
    from db.schema import get_connection, init_db
    from scraper.race_list import RaceListScraper
    from scraper.race_detail import RaceDetailScraper

    init_db()

    list_scraper = RaceListScraper()
    detail_scraper = RaceDetailScraper()

    target_dates: list[date] = []

    if args.date:
        try:
            target_dates = [date.fromisoformat(args.date)]
        except ValueError:
            print(f"エラー: 日付の形式が不正です: {args.date}", file=sys.stderr)
            return 1
    elif args.year and args.month:
        from datetime import timedelta
        year, month = args.year, args.month
        start = date(year, month, 1)
        end = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year + 1, 1, 1) - timedelta(days=1)
        current = start
        while current <= end:
            target_dates.append(current)
            current += timedelta(days=1)
    elif args.year:
        from datetime import timedelta
        start = date(args.year, 1, 1)
        end = date(args.year, 12, 31)
        current = start
        while current <= end:
            target_dates.append(current)
            current += timedelta(days=1)
    else:
        print("エラー: --date / --year / --year --month を指定してください。", file=sys.stderr)
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

                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO races
                          (race_id, date, venue, race_number, race_name, course_type, distance, race_class)
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (race_id, race_info.date.strftime("%Y-%m-%d"), race_info.venue,
                         race_info.race_number, race_info.race_name, race_info.course_type,
                         race_info.distance, race_info.race_class),
                    )
                    conn.commit()
                except sqlite3.Error as exc:
                    logger.error(f"races INSERT失敗 ({race_id}): {exc}")
                    continue

                try:
                    detail = detail_scraper.fetch(race_id)
                except Exception as exc:
                    logger.warning(f"レース詳細取得に失敗 ({race_id}): {exc}")
                    continue

                conn.execute(
                    "UPDATE races SET track_condition=?, weather=?, distance=?, course_type=?, race_class=? WHERE race_id=?",
                    (detail.track_condition, detail.weather, detail.distance,
                     detail.course_type, detail.race_class, race_id),
                )

                for entry in detail.entries:
                    conn.execute(
                        "INSERT OR IGNORE INTO horses (horse_id, name) VALUES (?, ?)",
                        (entry.horse_id, entry.horse_name),
                    )
                    conn.execute(
                        """INSERT OR IGNORE INTO entries
                          (race_id, horse_id, jockey_name, trainer_name,
                           frame_number, horse_number, weight_carried,
                           horse_weight, horse_weight_diff, odds, popularity, last_3f)
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (race_id, entry.horse_id, entry.jockey_name, entry.trainer_name,
                         entry.frame_number, entry.horse_number, entry.weight_carried,
                         entry.horse_weight, entry.horse_weight_diff,
                         entry.odds, entry.popularity, entry.last_3f),
                    )

                for result in detail.results:
                    conn.execute(
                        """INSERT OR IGNORE INTO results
                          (race_id, horse_id, finish_position, finish_time, margin)
                          VALUES (?, ?, ?, ?, ?)""",
                        (race_id, result.horse_id, result.finish_position,
                         result.finish_time, result.margin),
                    )

                for payout in detail.payouts:
                    conn.execute(
                        """INSERT OR IGNORE INTO payouts
                          (race_id, bet_type, combination, payout, popularity)
                          VALUES (?, ?, ?, ?, ?)""",
                        (race_id, payout.bet_type, payout.combination,
                         payout.payout, payout.popularity),
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
    scrape_parser.add_argument("--year", type=int, metavar="YYYY", help="対象年（単独で1年分、--monthと組み合わせで1ヶ月分）")
    scrape_parser.add_argument("--month", type=int, metavar="M", help="対象月 1〜12（--yearと組み合わせて使用）")

    # predict サブコマンド
    predict_parser = subparsers.add_parser("predict", help="指定日のレースを予測してスコア上位3レースを表示する")
    predict_parser.add_argument("--date", metavar="YYYY-MM-DD", required=True, help="予測対象日")

    # backtest サブコマンド
    bt_parser = subparsers.add_parser("backtest", help="過去データでバックテストを実行する")
    bt_parser.add_argument("--start", metavar="YYYY-MM-DD", default="2023-01-01", help="開始日")
    bt_parser.add_argument("--end", metavar="YYYY-MM-DD", default="2023-12-31", help="終了日")

    # analyze サブコマンド
    subparsers.add_parser("analyze", help="25種類のパターン分析を実行する")

    # signal-backtest サブコマンド
    subparsers.add_parser("signal-backtest", help="組み合わせシグナルのバックテストを実行する")

    # payout-analysis サブコマンド
    subparsers.add_parser("payout-analysis", help="実払戻データによるROI分析")

    # scrape-horses サブコマンド
    subparsers.add_parser("scrape-horses", help="DBにある全馬の過去成績を取得してhorse_historiesに保存")

    # signal-v2 サブコマンド
    subparsers.add_parser("signal-v2", help="前走データ込み複合シグナル分析（実払戻ROI）")

    # maegashira サブコマンド
    subparsers.add_parser("maegashira", help="高倍率3着以内馬の前走パターン分析")

    return parser


def cmd_scrape_horses() -> int:
    """DBにある全馬の過去成績をスクレイピングしてhorse_historiesに保存する。"""
    import sqlite3
    from db.schema import get_connection, init_db
    from scraper.horse_history import HorseHistoryScraper

    init_db()
    conn = get_connection()
    scraper = HorseHistoryScraper()

    # 既にhorse_historiesにある馬はスキップ
    done = set(r[0] for r in conn.execute("SELECT DISTINCT horse_id FROM horse_histories").fetchall())
    all_horses = [r[0] for r in conn.execute("SELECT horse_id FROM horses").fetchall()]
    targets = [h for h in all_horses if h not in done]

    print(f"対象馬: {len(targets)}頭 (取得済み: {len(done)}頭)")
    saved = 0

    try:
        for i, horse_id in enumerate(targets, 1):
            if i % 100 == 0:
                logger.info(f"進捗: {i}/{len(targets)} ({saved}件保存済み)")
            records = scraper.fetch(horse_id)
            for rec in records:
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO horse_histories
                          (horse_id, race_date, venue, race_name, race_class,
                           course_type, distance, track_condition, headcount,
                           frame_number, horse_number, popularity, odds,
                           finish_position, finish_time, last_3f,
                           horse_weight, horse_weight_diff, jockey_name)
                          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (rec.horse_id, rec.race_date, rec.venue, rec.race_name,
                         rec.race_class, rec.course_type, rec.distance,
                         rec.track_condition, rec.headcount, rec.frame_number,
                         rec.horse_number, rec.popularity, rec.odds,
                         rec.finish_position, rec.finish_time, rec.last_3f,
                         rec.horse_weight, rec.horse_weight_diff, rec.jockey_name),
                    )
                    saved += 1
                except sqlite3.Error:
                    pass
            conn.commit()
    finally:
        conn.close()

    print(f"馬過去成績の取得完了。保存件数: {saved}")
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    from db.schema import get_connection
    from backtest.runner import run_backtest, print_summary

    print(f"バックテスト実行中: {args.start} 〜 {args.end}")
    conn = get_connection()
    results, summary = run_backtest(conn, args.start, args.end)
    conn.close()
    print_summary(summary, results)
    return 0


def cmd_predict(args: argparse.Namespace) -> int:
    """指定日のJRAレースをスコアリングして買い目を推薦する。"""
    from db.schema import get_connection
    from features.calculator import calc_features_for_race
    from features.scorer import rank_horses

    JRA_VENUES = {"東京", "中山", "阪神", "京都", "中京", "新潟", "福島", "小倉", "札幌", "函館"}

    conn = get_connection()
    races = conn.execute(
        "SELECT race_id, venue, race_number, race_name, course_type, distance FROM races WHERE date=?",
        (args.date,)
    ).fetchall()

    jra_races = [r for r in races if r[1] in JRA_VENUES]
    if not jra_races:
        print(f"{args.date} のJRAレースデータがありません。先にscrapeを実行してください。")
        return 1

    print(f"\n{args.date} のJRAレース予測（{len(jra_races)}レース対象）\n")

    race_scores = []
    for race_id, venue, race_number, race_name, course_type, distance in jra_races:
        features = calc_features_for_race(conn, race_id)
        if not features:
            continue
        ranked = rank_horses(features)

        # 出走頭数
        headcount = len(features)

        # 断然人気チェック（1番人気オッズ≤1.5は除外）
        pop1_odds = next((f.odds for f, _ in ranked if f.popularity == 1), None)
        if pop1_odds and pop1_odds <= 1.5:
            continue

        # 多頭数除外（16頭以上）
        if headcount >= 16:
            continue

        top_score = ranked[0][1] if ranked else 0
        gap = (ranked[0][1] - ranked[1][1]) if len(ranked) >= 2 else 0
        confidence = top_score + gap * 2

        # シグナル判定
        signals = []
        for feat, score in ranked[:5]:
            pop = feat.popularity or 99
            if 4 <= pop <= 9 and headcount <= 12:
                signals.append(f"{feat.horse_number}番({pop}人気)が中穴×少頭数シグナル")
            if 4 <= pop <= 6 and "芝" in (features[0].course_type if hasattr(features[0], 'course_type') else ""):
                pass  # course_typeはfeaturesに含まれないため省略

        race_scores.append((race_id, venue, race_number, race_name, course_type,
                            distance, ranked, confidence, headcount, signals))

    race_scores.sort(key=lambda x: x[7], reverse=True)

    print("=" * 65)
    print("★ 本日の参加推奨レース TOP5")
    print("  (断然人気1.5倍以下・16頭以上 は除外済み)")
    print("=" * 65)

    for i, (race_id, venue, race_number, race_name, course_type, distance,
            ranked, confidence, headcount, signals) in enumerate(race_scores[:5], 1):
        print(f"\n【{i}位】{venue} {race_number}R {race_name}")
        print(f"  {course_type}{distance}m  {headcount}頭  信頼度: {confidence:.1f}")
        print("  --- 予測順位 ---")
        for rank, (feat, score) in enumerate(ranked[:5], 1):
            odds_str = f"{feat.odds:.1f}倍" if feat.odds else "不明"
            pop_str  = f"{feat.popularity}人気" if feat.popularity else ""
            signal_mark = " ◆中穴" if feat.popularity and 4 <= feat.popularity <= 9 and headcount <= 12 else ""
            print(f"  {rank}位: {feat.horse_number}番  {pop_str}  単勝{odds_str}  スコア:{score:.1f}{signal_mark}")

        # 買い目推薦
        top2 = [feat for feat, _ in ranked[:2]]
        signal_horses = [feat for feat, _ in ranked[:5]
                         if feat.popularity and 4 <= feat.popularity <= 9 and headcount <= 12]
        print("  --- 買い目推薦 ---")
        if signal_horses:
            for sh in signal_horses[:2]:
                print(f"  複勝: {sh.horse_number}番  ({sh.popularity}人気 {sh.odds:.1f}倍)")
            if len(top2) == 2:
                print(f"  馬連: {top2[0].horse_number}-{top2[1].horse_number}番")
        else:
            if top2:
                print(f"  複勝: {top2[0].horse_number}番")
            if len(top2) == 2:
                print(f"  馬連: {top2[0].horse_number}-{top2[1].horse_number}番")

    conn.close()
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "init-db":
        return cmd_init_db(args)
    elif args.command == "scrape":
        return cmd_scrape(args)
    elif args.command == "predict":
        return cmd_predict(args)
    elif args.command == "backtest":
        return cmd_backtest(args)
    elif args.command == "analyze":
        from db.schema import get_connection
        from analysis.pattern_finder import run_all
        conn = get_connection()
        run_all(conn)
        conn.close()
        return 0
    elif args.command == "signal-backtest":
        from db.schema import get_connection
        from analysis.signal_backtest import run_signal_backtest, print_signal_results
        conn = get_connection()
        results = run_signal_backtest(conn)
        conn.close()
        print_signal_results(results)
        return 0
    elif args.command == "payout-analysis":
        from db.schema import get_connection
        from analysis.payout_analysis import run_payout_analysis, print_payout_analysis
        conn = get_connection()
        results = run_payout_analysis(conn)
        conn.close()
        print_payout_analysis(results)
        return 0
    elif args.command == "scrape-horses":
        return cmd_scrape_horses()
    elif args.command == "signal-v2":
        from analysis.signal_v2 import run
        run()
        return 0
    elif args.command == "maegashira":
        from analysis.maegashira_analysis import run
        run()
        return 0
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
