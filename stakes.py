"""
stakes.py - 重賞レース予測（馬連・三連複向け）

使い方:
    python stakes.py --date 2026-06-07               # 当日の重賞
    python stakes.py --race_id 202606050811          # race_id直指定
    python stakes.py --date 2026-06-07 --fetch       # Webから取得してから予測
"""

import argparse
import sqlite3
import sys
from datetime import date as Date

from config import DB_PATH
from db.schema import init_db, get_connection
from analysis.signal_rules_stakes import score_stakes, stakes_verdict, evaluate_axis_horse


def get_race_entries(conn: sqlite3.Connection, race_id: str) -> list[dict]:
    rows = conn.execute("""
        SELECT
            e.horse_id, e.horse_number, e.frame_number,
            e.jockey_name, e.trainer_name,
            e.popularity, e.odds, e.horse_weight, e.horse_weight_diff,
            h.name AS horse_name,
            ra.course_type, ra.distance, ra.track_condition,
            ra.venue, ra.date, ra.race_name, ra.race_class,
            (SELECT COUNT(*) FROM entries e2 WHERE e2.race_id = e.race_id) AS headcount
        FROM entries e
        JOIN races ra ON ra.race_id = e.race_id
        LEFT JOIN horses h ON h.horse_id = e.horse_id
        WHERE e.race_id = ?
        ORDER BY e.popularity
    """, (race_id,)).fetchall()

    results = []
    for row in rows:
        e = dict(row)

        prev_row = conn.execute("""
            SELECT finish_position, popularity, headcount, distance,
                   course_type, last_3f, race_class, race_date
            FROM horse_histories
            WHERE horse_id = ? AND race_date < ?
            ORDER BY race_date DESC LIMIT 1
        """, (e['horse_id'], e['date'])).fetchone()
        prev = dict(prev_row) if prev_row else None

        prev2_row = conn.execute("""
            SELECT finish_position AS prev2_pos
            FROM horse_histories
            WHERE horse_id = ? AND race_date < ?
            ORDER BY race_date DESC LIMIT 1 OFFSET 1
        """, (e['horse_id'], e['date'])).fetchone()
        prev2_pos = prev2_row['prev2_pos'] if prev2_row else None

        score, signals = score_stakes(e, prev, prev2_pos=prev2_pos)
        e['prev'] = prev
        e['prev2_pos'] = prev2_pos
        e['score'] = score
        e['signals'] = signals
        results.append(e)

    return results


def print_stakes_prediction(race_id: str, horses: list[dict]) -> None:
    if not horses:
        return

    e0 = horses[0]
    print(f"\n{'=' * 65}")
    print(f"【{e0['venue']} {e0['race_name'] or race_id}】")
    print(f"  {e0['course_type']} {e0['distance']}m  馬場:{e0['track_condition'] or '?'}  {e0['headcount']}頭")
    print(f"{'=' * 65}")

    # 軸馬（1〜3人気）
    axis = [h for h in horses if h['popularity'] and h['popularity'] <= 3]
    if axis:
        print("\n  ─── 軸候補（1〜3人気）───")
        for h in sorted(axis, key=lambda x: x['popularity']):
            name = (h['horse_name'] or h['horse_id'])[:12]
            prev = h.get('prev')
            prev_str = f"前走{prev['finish_position']}着/{prev['popularity']}人気" if prev and prev.get('finish_position') else "前走データなし"
            odds_str = f"{h['odds']:.1f}倍" if h['odds'] else "?"
            verdict_str, conf = evaluate_axis_horse(h, prev)
            print(f"  [{h['horse_number']:2}] {name:<12} {h['popularity']}人気 {odds_str:>7}  {prev_str}")
            print(f"       → {verdict_str}")

    # 穴馬シグナル（4人気以上でスコアあり）
    holes = [h for h in horses if h['popularity'] and h['popularity'] >= 4 and h['score'] > 0]
    holes.sort(key=lambda x: x['score'], reverse=True)

    if holes:
        print("\n  ─── 穴馬シグナル ───")
        for h in holes[:6]:
            name = (h['horse_name'] or h['horse_id'])[:12]
            pop_str = f"{h['popularity']}人気"
            odds_str = f"{h['odds']:.1f}倍" if h['odds'] else "?"
            prev = h.get('prev')
            prev_str = f"前走{prev['finish_position']}着/{prev['popularity']}人気" if prev and prev.get('finish_position') else "-"
            verd = stakes_verdict(h['score'], h['popularity'])
            print(f"  [{h['horse_number']:2}] {name:<12} {pop_str:>6} {odds_str:>8}  {prev_str}")
            for s in h['signals']:
                if s['score'] > 0:
                    print(f"       ✓ {s['name']}: {s['desc']}  (+{s['score']})")
            print(f"       → スコア{h['score']:.1f}  {verd}")

    # 消し推奨
    cuts = [h for h in horses if h['popularity'] and h['popularity'] >= 6 and h['score'] < -1]
    if cuts:
        print("\n  ─── 消し推奨 ───")
        for h in cuts:
            name = (h['horse_name'] or h['horse_id'])[:12]
            print(f"  [{h['horse_number']:2}] {name:<12} {h['popularity']}人気  スコア{h['score']:.1f}")

    # 買い目サマリー
    top_holes = [h for h in holes if h['score'] >= 3.0]
    top_axis = [h for h in axis if h['popularity'] and h['popularity'] <= 2]

    if top_holes and top_axis:
        print(f"\n  ◆ 推奨買い目（参考）")
        axis_nums = [str(h['horse_number']) for h in top_axis]
        hole_nums = [str(h['horse_number']) for h in top_holes[:3]]
        print(f"    馬連:  軸{'-'.join(axis_nums)} × 相手{'-'.join(hole_nums)}")
        if len(hole_nums) >= 2:
            print(f"    三連複: 軸{'-'.join(axis_nums)} × 相手{'-'.join(hole_nums)}")


def main():
    parser = argparse.ArgumentParser(description="重賞レース予測（馬連・三連複向け）")
    parser.add_argument("--date", default=str(Date.today()), help="日付 YYYY-MM-DD")
    parser.add_argument("--race_id", help="race_idを直接指定")
    parser.add_argument("--fetch", action="store_true", help="Webからデータ取得")
    parser.add_argument("--db", default=DB_PATH)
    args = parser.parse_args()

    init_db(args.db)
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    if args.fetch:
        from today import fetch_today_races, fetch_horse_histories_for_race
        fetch_today_races(args.date, conn)
        conn.close()
        conn = sqlite3.connect(args.db)
        conn.row_factory = sqlite3.Row

    if args.race_id:
        race_ids = [args.race_id]
    else:
        # 当日の重賞を抽出（race_nameにG1/G2/G3を含む）
        races = conn.execute("""
            SELECT race_id, venue, race_name, race_number
            FROM races
            WHERE date = ?
              AND (race_name LIKE '%(G1)%' OR race_name LIKE '%(G2)%' OR race_name LIKE '%(G3)%'
                OR race_name LIKE '%（G1）%' OR race_name LIKE '%（G2）%' OR race_name LIKE '%（G3）%')
            ORDER BY venue, race_number
        """, (args.date,)).fetchall()

        if not races:
            print(f"{args.date} の重賞データがありません。--fetch で取得してください。")
            conn.close()
            return

        race_ids = [r['race_id'] for r in races]
        print(f"\n=== {args.date} の重賞 ({len(race_ids)}レース) ===")

    for race_id in race_ids:
        if args.fetch:
            from today import fetch_horse_histories_for_race
            fetch_horse_histories_for_race(race_id, conn)
        horses = get_race_entries(conn, race_id)
        if horses:
            print_stakes_prediction(race_id, horses)

    conn.close()


if __name__ == "__main__":
    main()
