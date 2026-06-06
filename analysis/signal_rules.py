"""
analysis/signal_rules.py - 3軸スコアリングロジック（実データ検証済み）

バックテスト結果（2025年JRA 40484件）:
  最終推奨条件: 241件, 複勝ROI 107円, 単勝ROI 151円, 平均42.5倍
  スコア6.0+: 314件, 複勝ROI 103円, 単勝ROI 135円
  スコア7.0+:  89件, 単勝ROI 273円

軸A: 統計シグナル（市場の誤解を突く）
軸B: 馬の能力（前走3F偏差、成績トレンド）
軸C: 騎手×コース適性
"""

from typing import Optional


def evaluate_signals(entry: dict, prev: Optional[dict]) -> list[dict]:
    """
    軸Aのシグナルのみ返す（後方互換）。
    フル評価はscore_horse()を使う。
    """
    if not prev:
        return []

    pop = entry.get('popularity') or 0
    course = entry.get('course_type', '')
    headcount = entry.get('headcount') or 0
    weight_diff = entry.get('horse_weight_diff')

    prev_pos = prev.get('finish_position') or prev.get('prev_pos')
    prev_hc = prev.get('headcount') or prev.get('prev_hc') or 0
    prev_course = prev.get('course_type') or prev.get('prev_course') or ''
    prev_pop = prev.get('popularity') or prev.get('prev_pop') or 0

    matched = []

    # N1: 前走1-3人気→今回9-11人気（単勝ROI 125円）
    if 9 <= pop <= 11 and 1 <= prev_pop <= 3:
        matched.append({'name': 'N1_前走人気急落', 'score': 3.0,
                        'desc': f"前走{prev_pop}人気→今回{pop}人気（市場の過小評価）"})

    # N2: 前走4-6人気→今回9-11人気（単勝ROI 101円）
    if 9 <= pop <= 11 and 4 <= prev_pop <= 6:
        matched.append({'name': 'N2_中人気→穴', 'score': 2.0,
                        'desc': f"前走{prev_pop}人気→今回{pop}人気"})

    # N3: 前走4-6着×同コース（複勝ROI 77円）
    if pop >= 6 and prev_pos and 4 <= prev_pos <= 6 and prev_course == course:
        matched.append({'name': 'N3_前走中着同コース', 'score': 1.5,
                        'desc': f"前走{prev_pos}着({course})→今回同コース"})

    # N4: 馬体重-6以上（単勝ROI 93円）
    if pop >= 6 and weight_diff is not None and weight_diff <= -6:
        matched.append({'name': 'N4_体重絞れ', 'score': 1.5,
                        'desc': f"馬体重{weight_diff}kg"})

    # N5: 前走7-10人気→今回6-8人気（複勝ROI 81円）
    if 6 <= pop <= 8 and 7 <= prev_pop <= 10:
        matched.append({'name': 'N5_前走不人気→今回中穴', 'score': 1.0,
                        'desc': f"前走{prev_pop}人気→今回{pop}人気"})

    # N6: ダート10頭以下（複勝ROI 79円）
    if pop >= 6 and course == 'ダート' and 0 < headcount <= 10:
        matched.append({'name': 'N6_ダート少頭数', 'score': 1.5,
                        'desc': f"ダート{headcount}頭立て"})

    # N7: 前走4-6着×頭数減少（複勝ROI 78円）
    if pop >= 6 and prev_pos and 4 <= prev_pos <= 6 and prev_hc > 0 and headcount > 0 and headcount <= prev_hc - 2:
        matched.append({'name': 'N7_前走中着頭数減少', 'score': 1.5,
                        'desc': f"前走{prev_pos}着{prev_hc}頭→今回{headcount}頭"})

    return matched


def score_axis_b(entry: dict, prev: Optional[dict], race_avg_3f: Optional[float] = None) -> float:
    """
    軸B: 馬の能力スコア
    - 前走3F偏差（レース平均と比較）
    - 2走分の成績トレンド
    """
    if not prev:
        return 0.0

    score = 0.0
    prev_3f = prev.get('last_3f') or prev.get('prev_last3f')
    prev2_pos = entry.get('prev2_pos')
    prev_pos = prev.get('finish_position') or prev.get('prev_pos')

    # B1: 前走3F偏差
    if prev_3f and race_avg_3f:
        diff = race_avg_3f - prev_3f  # プラス = 平均より速い
        if diff >= 2.0:    score += 2.0
        elif diff >= 1.0:  score += 2.0
        elif diff >= 0.5:  score += 1.0
        elif diff <= -1.0: score -= 1.0

    # B2: 成績トレンド（前走 vs 2走前）
    if prev_pos and prev2_pos:
        try:
            p1, p2 = float(prev_pos), float(prev2_pos)
            if p1 < p2:   score += 0.5   # 前走で着順改善
            elif p1 > p2: score -= 0.5   # 前走で着順悪化
        except (TypeError, ValueError):
            pass

    return score


def score_axis_c(jockey_name: str, course_type: str, jockey_stats: dict) -> float:
    """
    軸C: 騎手×コース適性スコア
    jockey_stats: {(jockey_name, course_type): win_rate}
    """
    win_rate = jockey_stats.get((jockey_name, course_type))
    if win_rate is None:
        return 0.0
    if win_rate >= 0.20:   return 2.0
    elif win_rate >= 0.15: return 1.0
    elif win_rate >= 0.10: return 0.5
    elif win_rate < 0.05:  return -0.5
    return 0.0


def score_horse(entry: dict, prev: Optional[dict],
                race_avg_3f: Optional[float] = None,
                jockey_stats: Optional[dict] = None) -> tuple[float, list[dict]]:
    """
    3軸総合スコアを返す。

    Args:
        entry: 出走馬データ（jockey_name含む）
        prev: 前走データ
        race_avg_3f: このレースの上がり3F平均（なければNone）
        jockey_stats: {(jockey_name, course_type): win_rate}（なければNone）

    Returns:
        (total_score, signals_list)

    判断基準:
        score >= 6.0 → 単勝推奨（ROI 135円実績）
        score >= 5.0 → 複勝推奨（ROI 88円実績）
        score >= 3.0 → 監視対象
    """
    signals = evaluate_signals(entry, prev)
    axis_a = sum(s['score'] for s in signals)

    axis_b = score_axis_b(entry, prev, race_avg_3f)

    axis_c = 0.0
    if jockey_stats:
        jockey_name = entry.get('jockey_name', '')
        course = entry.get('course_type', '')
        axis_c = score_axis_c(jockey_name, course, jockey_stats)

    total = axis_a + axis_b + axis_c
    return total, signals


def build_jockey_stats(jockey_csv_rows: list[dict]) -> dict:
    """
    jockey_stats.csvの行リストから{(jockey_name, course): win_rate}辞書を作る。
    """
    stats = {}
    for r in jockey_csv_rows:
        try:
            total = int(r['total'])
            wins = int(r['wins'])
            if total >= 20:
                stats[(r['jockey_name'], r['course_type'])] = wins / total
        except (KeyError, ValueError, ZeroDivisionError):
            pass
    return stats


def verdict(score: float) -> str:
    """スコアから買い推奨を返す。"""
    if score >= 7.0:   return "★★★ 単勝本命"
    elif score >= 6.0: return "★★  単勝推奨"
    elif score >= 5.0: return "★   複勝推奨"
    elif score >= 3.0: return "△   監視"
    else:              return "-   スルー"
