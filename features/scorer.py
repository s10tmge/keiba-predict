"""
features/scorer.py - 特徴量から予測スコアを計算する

各指標に重みをかけて合計スコアを算出。
スコアが高いほど「勝ちやすい」と判断する。
"""

from features.calculator import HorseFeatures


# 重みの設定（合計100）
WEIGHTS = {
    "last1_position": 20,      # 前走着順（最重要）
    "avg_position_5": 25,      # 直近5走平均（最重要）
    "win_rate_course": 15,     # コース適性
    "win_rate_distance": 15,   # 距離適性
    "win_rate_venue": 10,      # 競馬場適性
    "jockey_win_rate": 10,     # 騎手勝率
    "win_rate_overall": 5,     # 通算勝率
}


def score_horse(feat: HorseFeatures) -> float:
    """
    馬1頭のスコアを計算する（0〜100、高いほど有力）。
    データが少ない馬はスコアが低くなる。
    """
    score = 0.0

    # 前走着順スコア（1着=20点、2着=16点、...）
    if feat.last1_position is not None:
        pos_score = max(0, 20 - (feat.last1_position - 1) * 3)
        score += pos_score * (WEIGHTS["last1_position"] / 20)

    # 直近5走平均着順スコア（平均1着=25点、平均5着=10点、平均10着=0点）
    if feat.avg_position_5 is not None:
        avg_score = max(0, 25 - (feat.avg_position_5 - 1) * 2.5)
        score += avg_score * (WEIGHTS["avg_position_5"] / 25)

    # コース適性（勝率をそのまま使用）
    score += feat.win_rate_course * WEIGHTS["win_rate_course"]

    # 距離適性
    score += feat.win_rate_distance * WEIGHTS["win_rate_distance"]

    # 競馬場適性
    score += feat.win_rate_venue * WEIGHTS["win_rate_venue"]

    # 騎手勝率
    score += feat.jockey_win_rate * WEIGHTS["jockey_win_rate"]

    # 通算勝率
    score += feat.win_rate_overall * WEIGHTS["win_rate_overall"]

    return round(score, 3)


def rank_horses(features: list[HorseFeatures]) -> list[tuple[HorseFeatures, float]]:
    """馬リストをスコア順にソートして返す。"""
    scored = [(feat, score_horse(feat)) for feat in features]
    return sorted(scored, key=lambda x: x[1], reverse=True)
