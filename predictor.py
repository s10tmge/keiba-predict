"""
predictor.py - 当日レースのリアルタイム予測

対象レースIDを受け取り、以下を実行:
1. DBから出走馬エントリを取得
2. horse_historiesから各馬の前走データを取得
3. シグナルルールでスコアリング
4. スコア上位馬の複勝・馬連推奨を出力

使い方:
    python predictor.py 202506010101
    python predictor.py --date 2025-06-07   # 当日全レース
"""

import argparse
import sqlite3
import sys

from config import DB_PATH
from analysis.signal_rules import score_horse


def get_race_entries(conn: sqlite3.Connection, race_id: str) -> list[dict]:
    """指定レースの出走馬情報をDBから取得する。"""
    rows = conn.execute("""
        SELECT
            e.horse_id,
            e.horse_number,
            e.frame_number,
            e.jockey_name,
            e.popularity,
            e.odds,
            e.horse_weight,
            e.horse_weight_diff,
            e.last_3f,
            h.name AS horse_name,
            ra.course_type,
            ra.distance,
            ra.track_condition,
            ra.venue,
            ra.date,
            ra.race_name,
            ra.race_class,
            (SELECT COUNT(*) FROM entries e2 WHERE e2.race_id = e.race_id) AS headcount
        FROM entries e
        JOIN races ra ON ra.race_id = e.race_id
        LEFT JOIN horses h ON h.horse_id = e.horse_id
        WHERE e.race_id = ?
        ORDER BY e.horse_number
    """, (race_id,)).fetchall()
    return [dict(r) for r in rows]


def get_prev_race(conn: sqlite3.Connection, horse_id: str, before_date: str) -> dict | None:
    """horse_historiesから指定日以前の直前レースを取得する。"""
    row = conn.execute("""
        SELECT finish_position, headcount, distance, course_type,
               popularity, last_3f, race_class, race_date, venue
        FROM horse_histories
        WHERE horse_id = ? AND race_date < ?
        ORDER BY race_date DESC
        LIMIT 1
    """, (horse_id, before_date)).fetchone()
    return dict(row) if row else None


def predict_race(conn: sqlite3.Connection, race_id: str, verbose: bool = False) -> list[dict]:
    """
    1レースの予測を実行し、スコア付き馬リストを返す。

    Returns:
        [{'horse_name': ..., 'horse_number': ..., 'popularity': ...,
          'odds': ..., 'score': ..., 'signals': [...]}, ...]
        スコア降順ソート済み
    """
    entries = get_race_entries(conn, race_id)
    if not entries:
        return []

    race_date = entries[0]['date']
    results = []

    for e in entries:
        prev = get_prev_race(conn, e['horse_id'], race_date)
        score, signals = score_horse(e, prev)
        results.append({
            **e,
            'score': score,
            'signals': signals,
            'prev': prev,
        })

    results.sort(key=lambda x: x['score'], reverse=True)
    return results


def format_race_prediction(race_id: str, horses: list[dict]) -> str:
    """予測結果を整形して文字列で返す。"""
    if not horses:
        return f"[{race_id}] データなし\n"

    e0 = horses[0]
    lines = []
    lines.append(f"\n{'='*60}")
    lines.append(f"【{e0['venue']} {e0['race_name'] or race_id}】 {e0['date']}")
    lines.append(f"  {e0['course_type']} {e0['distance']}m  {e0['track_condition']}  {e0['headcount']}頭")
    lines.append(f"{'='*60}")

    # シグナルマッチ馬
    signal_horses = [h for h in horses if h['score'] > 0]

    if not signal_horses:
        lines.append("  シグナルマッチなし（標準予測なし）")
    else:
        lines.append("\n  ◆ シグナルマッチ馬（スコア順）")
        for h in signal_horses[:5]:
            pop_str = f"{h['popularity']}人気" if h['popularity'] else "?"
            odds_str = f"{h['odds']:.1f}倍" if h['odds'] else "?"
            prev = h.get('prev')
            prev_str = f"前走{prev['finish_position']}着/{prev['headcount']}頭" if prev and prev.get('finish_position') else "前走不明"
            lines.append(f"  [{h['horse_number']:2}] {h['horse_name'] or h['horse_id']:<12} "
                         f"{pop_str:>5} {odds_str:>7}  スコア:{h['score']:.1f}  {prev_str}")
            for s in h['signals']:
                lines.append(f"       → {s['name']}: {s['desc']}")

    # 買い目推奨
    top3 = signal_horses[:3]
    if len(top3) >= 2:
        lines.append("\n  ◆ 推奨買い目")
        nums = [str(h['horse_number']) for h in top3]

        # 複勝: スコア1位
        lines.append(f"  複勝: {nums[0]}番")

        # 馬連: 1位-2位
        if len(nums) >= 2:
            lines.append(f"  馬連: {nums[0]}-{nums[1]}")

        # 3連複: 上位3頭
        if len(nums) >= 3:
            lines.append(f"  3連複: {nums[0]}-{nums[1]}-{nums[2]}")

    lines.append("")
    return "\n".join(lines)


def predict_date(conn: sqlite3.Connection, date: str) -> None:
    """指定日の全レースを予測して出力する。"""
    races = conn.execute("""
        SELECT race_id, venue, race_name, race_number
        FROM races
        WHERE date = ?
        ORDER BY venue, race_number
    """, (date,)).fetchall()

    if not races:
        print(f"{date} のレースデータがありません。")
        return

    print(f"\n{date} の予測 ({len(races)}レース)")

    total_signals = 0
    for race in races:
        horses = predict_race(conn, race['race_id'])
        signal_horses = [h for h in horses if h['score'] > 0]
        if signal_horses:
            total_signals += 1
            print(format_race_prediction(race['race_id'], horses))

    if total_signals == 0:
        print("シグナルマッチするレースなし")


def main():
    parser = argparse.ArgumentParser(description="競馬予測エンジン")
    parser.add_argument("race_id", nargs="?", help="レースID (例: 202506010101)")
    parser.add_argument("--date", help="日付 (YYYY-MM-DD) 当日全レース予測")
    parser.add_argument("--db", default=DB_PATH, help="DBパス")
    parser.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    if args.date:
        predict_date(conn, args.date)
    elif args.race_id:
        horses = predict_race(conn, args.race_id, verbose=args.verbose)
        print(format_race_prediction(args.race_id, horses))
    else:
        # 引数なし: 直近レース一覧を表示
        latest = conn.execute("""
            SELECT DISTINCT date FROM races ORDER BY date DESC LIMIT 5
        """).fetchall()
        print("最近の開催日:")
        for row in latest:
            print(f"  {row['date']}")
        print("\n使い方:")
        print("  python predictor.py --date 2025-06-07")
        print("  python predictor.py 202506010101")

    conn.close()


if __name__ == "__main__":
    main()
