"""
today.py - 当日レースをWebから取得して予測する

DBにデータがなくてもWebからリアルタイムで取得可能。
毎週土日の朝に実行して当日のレースを予測する。

使い方:
    python today.py                          # 今日の日付
    python today.py --date 2025-06-07       # 指定日
    python today.py --date 2025-06-07 --fetch  # Webから最新データ取得してから予測
"""

import argparse
import sqlite3
import sys
from datetime import date as Date

from config import DB_PATH
from db.schema import init_db, get_connection, save_race_list, save_race_detail
from analysis.signal_rules import score_horse


def fetch_today_races(target_date: str, conn: sqlite3.Connection) -> int:
    """指定日のレースデータをWebから取得してDBに保存する。"""
    from scraper.race_list import RaceListScraper
    from scraper.race_detail import RaceDetailScraper

    list_scraper = RaceListScraper()
    detail_scraper = RaceDetailScraper()

    d = Date.fromisoformat(target_date)
    print(f"[Fetch] {target_date} のレースリストを取得中...")
    races = list_scraper.fetch(d)

    # 新馬・障害除外
    races = [r for r in races if not any(kw in (r.race_name or '') for kw in ['新馬', '障害', '障碍'])]
    print(f"  → {len(races)}レース対象")

    if not races:
        return 0

    save_race_list(races, DB_PATH)

    saved = 0
    for race in races:
        existing = conn.execute(
            "SELECT COUNT(*) FROM entries WHERE race_id=?", (race.race_id,)
        ).fetchone()[0]
        if existing > 0:
            continue
        try:
            detail = detail_scraper.fetch(race.race_id)
            save_race_detail(detail, DB_PATH)
            saved += 1
            print(f"  [{race.race_number:2}R] {race.race_name} → {len(detail.entries)}頭")
        except Exception as ex:
            print(f"  [{race.race_number:2}R] {race.race_name} エラー: {ex}")

    return saved


def fetch_horse_histories_for_race(race_id: str, conn: sqlite3.Connection) -> None:
    """レースに出走する馬のhorse_historiesを必要に応じて取得する。"""
    from scraper.horse_history import HorseHistoryScraper
    from db.schema import get_connection as _gc

    horse_ids = [r[0] for r in conn.execute(
        "SELECT horse_id FROM entries WHERE race_id=?", (race_id,)
    ).fetchall()]

    # すでにデータがある馬はスキップ
    done = set(r[0] for r in conn.execute(
        "SELECT DISTINCT horse_id FROM horse_histories WHERE horse_id IN ({})".format(
            ','.join('?' * len(horse_ids))
        ), horse_ids
    ).fetchall()) if horse_ids else set()

    targets = [h for h in horse_ids if h not in done]
    if not targets:
        return

    print(f"  前走データ取得: {len(targets)}頭...")
    scraper = HorseHistoryScraper()
    write_conn = _gc(DB_PATH)

    for horse_id in targets:
        records = scraper.fetch(horse_id)
        if not records:
            continue
        with write_conn:
            for rec in records:
                write_conn.execute("""
                    INSERT OR IGNORE INTO horse_histories
                    (horse_id, race_date, race_id, venue, race_name, race_class,
                     course_type, distance, track_condition, headcount, frame_number,
                     horse_number, popularity, odds, finish_position, finish_time,
                     last_3f, horse_weight, horse_weight_diff, weight_carried,
                     corner_position, jockey_name)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    rec.horse_id, rec.race_date, rec.race_id, rec.venue, rec.race_name,
                    rec.race_class, rec.course_type, rec.distance, rec.track_condition,
                    rec.headcount, rec.frame_number, rec.horse_number, rec.popularity,
                    rec.odds, rec.finish_position, rec.finish_time, rec.last_3f,
                    rec.horse_weight, rec.horse_weight_diff, rec.weight_carried,
                    rec.corner_position, rec.jockey_name,
                ))

    write_conn.close()


def load_jockey_stats(db_path: str) -> dict:
    """DBから騎手×コース勝率辞書を作成する。"""
    import csv as _csv
    from pathlib import Path
    # jockey_stats.csvがあれば使う（エクスポート済みの場合）
    csv_path = Path(db_path).parent / 'jockey_stats.csv'
    if csv_path.exists():
        stats = {}
        with open(csv_path, encoding='utf-8-sig') as f:
            for r in _csv.DictReader(f):
                try:
                    total = int(r['total'])
                    wins = int(r['wins'])
                    if total >= 20:
                        stats[(r['jockey_name'], r['course_type'])] = wins / total
                except (KeyError, ValueError, ZeroDivisionError):
                    pass
        return stats
    # なければDBから直接集計
    conn2 = sqlite3.connect(db_path)
    rows = conn2.execute("""
        SELECT e.jockey_name, ra.course_type,
               COUNT(*) AS total,
               SUM(CASE WHEN r.finish_position=1 THEN 1 ELSE 0 END) AS wins
        FROM entries e
        JOIN races ra ON ra.race_id=e.race_id
        JOIN results r ON r.race_id=e.race_id AND r.horse_id=e.horse_id
        WHERE ra.date>='2024-01-01' AND e.jockey_name IS NOT NULL
        GROUP BY e.jockey_name, ra.course_type
        HAVING COUNT(*) >= 20
    """).fetchall()
    conn2.close()
    return {(r[0], r[1]): r[3]/r[2] for r in rows if r[2] > 0}


def get_race_avg_3f(conn: sqlite3.Connection, race_id: str) -> float | None:
    """レース内の上がり3F平均を返す。"""
    row = conn.execute(
        "SELECT AVG(last_3f) FROM entries WHERE race_id=? AND last_3f IS NOT NULL",
        (race_id,)
    ).fetchone()
    return row[0] if row else None


def get_race_entries_with_prev(conn: sqlite3.Connection, race_id: str,
                                jockey_stats: dict = None) -> list[dict]:
    rows = conn.execute("""
        SELECT
            e.horse_id, e.horse_number, e.frame_number,
            e.jockey_name, e.trainer_name,
            e.popularity, e.odds, e.horse_weight, e.horse_weight_diff, e.last_3f,
            h.name AS horse_name,
            ra.course_type, ra.distance, ra.track_condition,
            ra.venue, ra.date, ra.race_name, ra.race_class,
            (SELECT COUNT(*) FROM entries e2 WHERE e2.race_id = e.race_id) AS headcount
        FROM entries e
        JOIN races ra ON ra.race_id = e.race_id
        LEFT JOIN horses h ON h.horse_id = e.horse_id
        WHERE e.race_id = ?
        ORDER BY e.horse_number
    """, (race_id,)).fetchall()

    race_avg_3f = get_race_avg_3f(conn, race_id)

    results = []
    for row in rows:
        e = dict(row)
        prev_row = conn.execute("""
            SELECT finish_position, headcount, distance, course_type,
                   popularity, last_3f AS prev_last3f, race_class, race_date
            FROM horse_histories
            WHERE horse_id = ? AND race_date < ?
            ORDER BY race_date DESC LIMIT 1
        """, (e['horse_id'], e['date'])).fetchone()
        prev = dict(prev_row) if prev_row else None

        # 2走前
        prev2_row = conn.execute("""
            SELECT finish_position AS prev2_pos, popularity AS prev2_pop
            FROM horse_histories
            WHERE horse_id = ? AND race_date < ?
            ORDER BY race_date DESC LIMIT 1 OFFSET 1
        """, (e['horse_id'], e['date'])).fetchone()
        if prev2_row and prev:
            prev['prev2_pos'] = prev2_row['prev2_pos']

        score, signals = score_horse(e, prev, race_avg_3f, jockey_stats)
        e['prev'] = prev
        e['score'] = score
        e['signals'] = signals
        e['race_avg_3f'] = race_avg_3f
        results.append(e)

    results.sort(key=lambda x: x['score'], reverse=True)
    return results


def print_prediction(race_id: str, horses: list[dict]) -> None:
    if not horses:
        return
    e0 = horses[0]
    signal_horses = [h for h in horses if h['score'] > 0]
    if not signal_horses:
        return

    print(f"\n{'='*60}")
    print(f"【{e0['venue']} {e0['race_name'] or race_id}】")
    print(f"  {e0['course_type']} {e0['distance']}m  馬場:{e0['track_condition'] or '?'}  {e0['headcount']}頭立て")
    print(f"{'='*60}")
    print(f"  {'馬番':>3} {'馬名':<12} {'人気':>4} {'オッズ':>7} {'スコア':>5}  前走")

    from analysis.signal_rules import verdict
    for h in signal_horses[:6]:
        pop_str = f"{h['popularity']}人気" if h['popularity'] else "?"
        odds_str = f"{h['odds']:.1f}倍" if h['odds'] else "?"
        prev = h.get('prev')
        prev_str = f"前走{prev['finish_position']}着" if prev and prev.get('finish_position') else "-"
        name = (h['horse_name'] or h['horse_id'])[:12]
        verd = verdict(h['score'])
        print(f"  [{h['horse_number']:2}] {name:<12} {pop_str:>5} {odds_str:>7} {h['score']:>5.1f}  {prev_str}  {verd}")
        for s in h['signals']:
            print(f"       ✓ {s['name']}: {s['desc']}")

    # 買い目（スコアベース）
    buy = [h for h in signal_horses if h['score'] >= 5.0]
    if buy:
        print(f"\n  ◆ 推奨買い目")
        for h in buy[:3]:
            verd = verdict(h['score'])
            print(f"    {verd}  {h['horse_number']}番 {h['horse_name'] or ''} {h['odds']:.1f}倍")


def main():
    parser = argparse.ArgumentParser(description="当日レース予測")
    parser.add_argument("--date", default=str(Date.today()), help="日付 YYYY-MM-DD")
    parser.add_argument("--fetch", action="store_true", help="Webから最新データを取得してから予測")
    parser.add_argument("--db", default=DB_PATH)
    args = parser.parse_args()

    init_db(args.db)
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    if args.fetch:
        fetch_today_races(args.date, conn)
        conn.close()
        conn = sqlite3.connect(args.db)
        conn.row_factory = sqlite3.Row

    # 当日レース一覧
    races = conn.execute("""
        SELECT race_id, venue, race_name, race_number
        FROM races WHERE date = ?
        ORDER BY venue, race_number
    """, (args.date,)).fetchall()

    if not races:
        print(f"{args.date} のデータがありません。--fetch オプションで取得してください。")
        conn.close()
        return

    print(f"\n=== {args.date} の予測 ({len(races)}レース) ===")

    jockey_stats = load_jockey_stats(args.db)

    found = 0
    for race in races:
        if args.fetch:
            fetch_horse_histories_for_race(race['race_id'], conn)
        horses = get_race_entries_with_prev(conn, race['race_id'], jockey_stats=jockey_stats)
        signal_count = sum(1 for h in horses if h['score'] > 0)
        if signal_count > 0:
            found += 1
            print_prediction(race['race_id'], horses)

    if found == 0:
        print("シグナルマッチするレースなし")
    else:
        print(f"\n合計 {found}レースでシグナル検出")

    conn.close()


if __name__ == "__main__":
    main()
