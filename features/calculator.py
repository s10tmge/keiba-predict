"""
features/calculator.py - 特徴量の計算

各馬について以下の指標を計算する:
- 前走着順・前々走着順
- 直近5走の平均着順
- コース適性（芝/ダート別勝率）
- 距離適性（距離帯別勝率）
- 騎手の直近勝率
- 馬場状態別成績
"""

import sqlite3
from dataclasses import dataclass, field

JRA_VENUES = {"東京", "中山", "阪神", "京都", "中京", "新潟", "福島", "小倉", "札幌", "函館"}


@dataclass
class HorseFeatures:
    race_id: str
    horse_id: str
    horse_number: int
    odds: float | None

    # 前走情報
    last1_position: int | None = None   # 前走着順
    last2_position: int | None = None   # 前々走着順
    last3_position: int | None = None

    # 直近5走平均着順（小さいほど良い）
    avg_position_5: float | None = None

    # 勝率系
    win_rate_overall: float = 0.0       # 通算勝率
    win_rate_course: float = 0.0        # コース(芝/ダート)別勝率
    win_rate_distance: float = 0.0      # 距離帯別勝率
    win_rate_venue: float = 0.0         # 競馬場別勝率

    # 騎手勝率（直近90日）
    jockey_win_rate: float = 0.0

    # 馬体重変化
    weight_diff: int | None = None


def _distance_band(distance: int) -> str:
    if distance <= 1400:
        return "sprint"
    elif distance <= 1800:
        return "mile"
    elif distance <= 2200:
        return "middle"
    else:
        return "long"


def calc_features_for_race(conn: sqlite3.Connection, race_id: str) -> list[HorseFeatures]:
    """指定レースの全出走馬の特徴量を計算して返す。"""

    # レース情報取得
    race = conn.execute(
        "SELECT course_type, distance, venue, date FROM races WHERE race_id=?",
        (race_id,)
    ).fetchone()
    if not race:
        return []

    course_type, distance, venue, race_date = race
    dist_band = _distance_band(distance or 0)

    entries = conn.execute(
        "SELECT horse_id, jockey_name, horse_number, odds, horse_weight_diff FROM entries WHERE race_id=?",
        (race_id,)
    ).fetchall()

    result_list = []

    for horse_id, jockey_name, horse_number, odds, weight_diff in entries:
        feat = HorseFeatures(
            race_id=race_id,
            horse_id=horse_id,
            horse_number=horse_number or 0,
            odds=odds,
            weight_diff=weight_diff,
        )

        # 過去レース結果（この馬の、対象レース日より前のもの）
        past = conn.execute(
            """
            SELECT r.finish_position, ra.course_type, ra.distance, ra.venue, ra.date
            FROM results r
            JOIN races ra ON r.race_id = ra.race_id
            WHERE r.horse_id = ?
              AND ra.date < ?
              AND ra.venue IN ({})
            ORDER BY ra.date DESC
            LIMIT 20
            """.format(",".join("?" * len(JRA_VENUES))),
            (horse_id, race_date, *JRA_VENUES)
        ).fetchall()

        positions = [p[0] for p in past if p[0] is not None]

        # 前走・前々走・前々々走
        feat.last1_position = positions[0] if len(positions) > 0 else None
        feat.last2_position = positions[1] if len(positions) > 1 else None
        feat.last3_position = positions[2] if len(positions) > 2 else None

        # 直近5走平均着順
        recent5 = positions[:5]
        feat.avg_position_5 = sum(recent5) / len(recent5) if recent5 else None

        # 通算勝率
        if positions:
            feat.win_rate_overall = positions.count(1) / len(positions)

        # コース別勝率
        course_results = [p[0] for p in past if p[1] == course_type and p[0] is not None]
        if course_results:
            feat.win_rate_course = course_results.count(1) / len(course_results)

        # 距離帯別勝率
        dist_results = [p[0] for p in past if _distance_band(p[2] or 0) == dist_band and p[0] is not None]
        if dist_results:
            feat.win_rate_distance = dist_results.count(1) / len(dist_results)

        # 競馬場別勝率
        venue_results = [p[0] for p in past if p[3] == venue and p[0] is not None]
        if venue_results:
            feat.win_rate_venue = venue_results.count(1) / len(venue_results)

        # 騎手勝率（直近90日）
        if jockey_name:
            jockey_past = conn.execute(
                """
                SELECT r.finish_position
                FROM results r
                JOIN entries e ON r.race_id = e.race_id AND r.horse_id = e.horse_id
                JOIN races ra ON r.race_id = ra.race_id
                WHERE e.jockey_name = ?
                  AND ra.date < ?
                  AND ra.date >= date(?, '-90 days')
                  AND r.finish_position IS NOT NULL
                """,
                (jockey_name, race_date, race_date)
            ).fetchall()
            jockey_positions = [p[0] for p in jockey_past]
            if jockey_positions:
                feat.jockey_win_rate = jockey_positions.count(1) / len(jockey_positions)

        result_list.append(feat)

    return result_list
