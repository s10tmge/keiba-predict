"""
backtest/runner.py - バックテスト実行エンジン

2023年データで予測ロジックを検証する。
単勝・馬連の的中率と回収率を計算する。
"""

import sqlite3
from dataclasses import dataclass, field
from datetime import date

from features.calculator import calc_features_for_race
from features.scorer import rank_horses

JRA_VENUES = {"東京", "中山", "阪神", "京都", "中京", "新潟", "福島", "小倉", "札幌", "函館"}

BET_AMOUNT = 100  # 1点あたりの賭け金（円）


@dataclass
class RaceResult:
    race_id: str
    date: str
    venue: str
    race_number: int
    race_name: str
    course_type: str
    distance: int
    predicted_1st: int      # 予測1位の馬番
    predicted_2nd: int      # 予測2位の馬番
    actual_1st: int | None  # 実際の1着馬番
    actual_2nd: int | None  # 実際の2着馬番
    actual_3rd: int | None  # 実際の3着馬番
    tansho_odds: float | None   # 予測1位馬の単勝オッズ
    confidence: float


@dataclass
class BacktestSummary:
    total_races: int = 0
    # 単勝
    tansho_bets: int = 0
    tansho_hits: int = 0
    tansho_payout: float = 0.0
    # 馬連（予測1・2位の組み合わせ）
    umaren_bets: int = 0
    umaren_hits: int = 0
    umaren_payout: float = 0.0


def run_backtest(conn: sqlite3.Connection, start_date: str, end_date: str) -> tuple[list[RaceResult], BacktestSummary]:
    """指定期間のバックテストを実行する。"""

    races = conn.execute(
        """
        SELECT race_id, date, venue, race_number, race_name, course_type, distance
        FROM races
        WHERE date >= ? AND date <= ? AND venue IN ({})
        ORDER BY date
        """.format(",".join("?" * len(JRA_VENUES))),
        (start_date, end_date, *JRA_VENUES)
    ).fetchall()

    results: list[RaceResult] = []
    summary = BacktestSummary()

    for race_id, race_date, venue, race_number, race_name, course_type, distance in races:
        features = calc_features_for_race(conn, race_id)
        if len(features) < 3:
            continue

        ranked = rank_horses(features)
        if len(ranked) < 2:
            continue

        predicted_1st_feat, score1 = ranked[0]
        predicted_2nd_feat, score2 = ranked[1]
        confidence = score1 + (score1 - score2) * 2

        # 実際の結果を取得
        actuals = conn.execute(
            """
            SELECT e.horse_number, r.finish_position
            FROM results r
            JOIN entries e ON r.race_id = e.race_id AND r.horse_id = e.horse_id
            WHERE r.race_id = ? AND r.finish_position IN (1, 2, 3)
            ORDER BY r.finish_position
            """,
            (race_id,)
        ).fetchall()

        actual_map = {pos: num for num, pos in actuals}
        actual_1st = actual_map.get(1)
        actual_2nd = actual_map.get(2)
        actual_3rd = actual_map.get(3)

        # 馬連オッズを取得（簡易：DB未保存のためNone）
        umaren_odds = None

        result = RaceResult(
            race_id=race_id,
            date=race_date,
            venue=venue,
            race_number=race_number,
            race_name=race_name,
            course_type=course_type,
            distance=distance,
            predicted_1st=predicted_1st_feat.horse_number,
            predicted_2nd=predicted_2nd_feat.horse_number,
            actual_1st=actual_1st,
            actual_2nd=actual_2nd,
            actual_3rd=actual_3rd,
            tansho_odds=predicted_1st_feat.odds,
            confidence=confidence,
        )
        results.append(result)
        summary.total_races += 1

        # 単勝ベット（予測1位）
        summary.tansho_bets += BET_AMOUNT
        if actual_1st == predicted_1st_feat.horse_number and predicted_1st_feat.odds:
            summary.tansho_hits += 1
            summary.tansho_payout += predicted_1st_feat.odds * BET_AMOUNT

        # 馬連ベット（予測1・2位の組み合わせ）
        summary.umaren_bets += BET_AMOUNT
        pred_set = {predicted_1st_feat.horse_number, predicted_2nd_feat.horse_number}
        actual_top2 = {actual_1st, actual_2nd} - {None}
        if pred_set == actual_top2:
            summary.umaren_hits += 1
            # 馬連オッズはDBに未保存のため推定値（単勝オッズの積の0.7倍）
            est_odds = (predicted_1st_feat.odds or 5.0) * (predicted_2nd_feat.odds or 5.0) * 0.7
            summary.umaren_payout += min(est_odds, 500) * BET_AMOUNT  # 上限500倍

    return results, summary


def print_summary(summary: BacktestSummary, results: list[RaceResult]):
    print("\n" + "=" * 60)
    print("バックテスト結果")
    print("=" * 60)
    print(f"対象レース数: {summary.total_races}")
    print()

    # 単勝
    tansho_rate = summary.tansho_hits / summary.total_races * 100 if summary.total_races else 0
    tansho_roi = summary.tansho_payout / summary.tansho_bets * 100 if summary.tansho_bets else 0
    print(f"【単勝】予測1位を単勝買い")
    print(f"  的中率: {tansho_rate:.1f}% ({summary.tansho_hits}/{summary.total_races})")
    print(f"  回収率: {tansho_roi:.1f}%")
    print(f"  投資額: {summary.tansho_bets:,}円 / 払戻: {summary.tansho_payout:,.0f}円")
    print()

    # 馬連
    umaren_rate = summary.umaren_hits / summary.total_races * 100 if summary.total_races else 0
    umaren_roi = summary.umaren_payout / summary.umaren_bets * 100 if summary.umaren_bets else 0
    print(f"【馬連】予測1・2位の組み合わせ")
    print(f"  的中率: {umaren_rate:.1f}% ({summary.umaren_hits}/{summary.total_races})")
    print(f"  回収率: {umaren_roi:.1f}% ※馬連オッズは推定値")
    print()

    # 信頼度上位レースの成績
    high_conf = [r for r in results if r.confidence >= 50]
    if high_conf:
        hits = sum(1 for r in high_conf if r.actual_1st == r.predicted_1st)
        print(f"【参考】信頼度スコア50以上のレース ({len(high_conf)}件)")
        print(f"  単勝的中率: {hits/len(high_conf)*100:.1f}%")

    print("=" * 60)
