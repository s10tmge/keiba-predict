"""
analysis/signal_rules.py - シグナルルール定義

signal_v2.pyの分析結果を元に、有効なシグナルを定義する。
各ルールは (名前, フィルタ関数, 複勝ROI推定, 説明) のタプル。

使い方:
    from analysis.signal_rules import evaluate_signals
    signals = evaluate_signals(entry_dict, prev_dict)
"""

from typing import Optional


def _class_rank(cls: str) -> int:
    order = ["未勝利", "1勝", "2勝", "3勝", "オープン", "リステッド", "G3", "G2", "G1"]
    try:
        return order.index(cls)
    except ValueError:
        return -1


def evaluate_signals(entry: dict, prev: Optional[dict]) -> list[dict]:
    """
    出走馬データと前走データを受け取り、マッチしたシグナルのリストを返す。

    Args:
        entry: {
            'popularity': int,
            'odds': float,
            'horse_weight': int,
            'horse_weight_diff': int,
            'last_3f': float,
            'course_type': str,         # 芝/ダート
            'distance': int,
            'headcount': int,
            'race_class': str,
            'track_condition': str,
        }
        prev: {
            'finish_position': int,
            'headcount': int,
            'distance': int,
            'course_type': str,
            'popularity': int,
            'last_3f': float,
            'race_class': str,
        } or None

    Returns:
        [{'name': str, 'score': float, 'desc': str}, ...]
    """
    matched = []

    pop = entry.get('popularity') or 0
    course = entry.get('course_type', '')
    distance = entry.get('distance') or 0
    headcount = entry.get('headcount') or 0
    weight_diff = entry.get('horse_weight_diff')
    race_class = entry.get('race_class', '')
    odds = entry.get('odds') or 0

    if not prev:
        return matched

    prev_pos = prev.get('finish_position')
    prev_hc = prev.get('headcount') or 0
    prev_dist = prev.get('distance') or 0
    prev_course = prev.get('course_type', '')
    prev_pop = prev.get('popularity') or 0
    prev_class = prev.get('race_class', '')

    # ---- シグナル定義 (score = ROI推定ポイント、高いほど有望) ----

    # S1: 前走1-3着×同コース×6人気以上（過小評価された実力馬）
    if pop >= 6 and prev_pos and prev_pos <= 3 and prev_course == course:
        matched.append({
            'name': 'S1_前走好走同コース',
            'score': 1.5,
            'desc': f"前走{prev_pos}着({prev_course})→今回同コース、今回{pop}人気"
        })

    # S2: 前走大頭数(16頭以上)→今回少頭数(12頭以下) × 6人気以上（環境改善）
    if pop >= 6 and prev_hc >= 16 and 0 < headcount <= 12:
        matched.append({
            'name': 'S2_大頭数→少頭数',
            'score': 2.0,
            'desc': f"前走{prev_hc}頭→今回{headcount}頭、今回{pop}人気"
        })

    # S3: 前走人気1-3で着外→今回6人気以上（人気落ち馬の巻き返し）
    if pop >= 6 and prev_pop <= 3 and prev_pos and prev_pos > 5:
        matched.append({
            'name': 'S3_人気落ち巻返し',
            'score': 1.8,
            'desc': f"前走{prev_pop}人気{prev_pos}着→今回{pop}人気"
        })

    # S4: ダート×頭数12以下×6人気以上×前走1-5着（少頭数ダート穴）
    if pop >= 6 and course == 'ダート' and 0 < headcount <= 12 and prev_pos and prev_pos <= 5:
        matched.append({
            'name': 'S4_少頭数ダート穴',
            'score': 2.2,
            'desc': f"ダート{headcount}頭立て、前走{prev_pos}着、今回{pop}人気"
        })

    # S5: 距離短縮200m以上×前走1-3着×6人気以上（距離短縮実力馬）
    if pop >= 6 and prev_dist > 0 and distance > 0 and (distance - prev_dist) <= -200 and prev_pos and prev_pos <= 3:
        matched.append({
            'name': 'S5_短縮好走馬',
            'score': 1.6,
            'desc': f"前走{prev_dist}m→今回{distance}m(短縮{prev_dist - distance}m)、前走{prev_pos}着"
        })

    # S6: クラス上昇後に人気落ち→今回同クラスで巻返し
    prev_rank = _class_rank(prev_class)
    curr_rank = _class_rank(race_class)
    if pop >= 6 and prev_rank > curr_rank >= 0 and prev_pos and prev_pos <= 5:
        matched.append({
            'name': 'S6_格下降巻返し',
            'score': 1.4,
            'desc': f"{prev_class}→{race_class}(格下げ)、前走{prev_pos}着、今回{pop}人気"
        })

    # S7: 馬体重増加+10以上×ダート×前走1-3着（充実期ダート馬）
    if pop >= 6 and weight_diff and weight_diff >= 10 and course == 'ダート' and prev_pos and prev_pos <= 3:
        matched.append({
            'name': 'S7_体重増充実ダート',
            'score': 1.5,
            'desc': f"馬体重+{weight_diff}kg、ダート、前走{prev_pos}着、今回{pop}人気"
        })

    # S8: 9人気以上×前走1-3着×距離同程度（超高配当候補）
    if pop >= 9 and prev_pos and prev_pos <= 3 and abs(distance - prev_dist) <= 200:
        matched.append({
            'name': 'S8_超穴前走好走',
            'score': 1.3,
            'desc': f"{pop}人気と低評価だが前走{prev_pos}着の実力馬"
        })

    return matched


def score_horse(entry: dict, prev: Optional[dict]) -> tuple[float, list[dict]]:
    """
    馬のシグナルスコア合計と、マッチしたシグナルリストを返す。

    Returns:
        (total_score, signals_matched)
    """
    signals = evaluate_signals(entry, prev)
    total = sum(s['score'] for s in signals)
    return total, signals
