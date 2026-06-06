"""
analysis/signal_rules.py - シグナルルール定義（v2: 実データROI検証済み）

2025年JRAデータ40484件のバックテストに基づく。
「市場の誤解（ミスプライス）」を突くシグナル設計。

有効シグナルの根拠:
- N1: 前走1-3人気×今回9-11人気 → 単勝ROI 124円（711件）
- N2: 前走4-6人気×今回9-11人気 → 単勝ROI 101円（1582件）
- N3: 前走4-6着×同コース      → 複勝ROI 73円（改善余地あり）
- N4: 馬体重減少-6以上         → 単勝ROI 92円
- N5: 前走7-10人気×今回6-8人気 → 単勝ROI 88円
"""

from typing import Optional


def evaluate_signals(entry: dict, prev: Optional[dict]) -> list[dict]:
    """
    出走馬データと前走データを受け取り、マッチしたシグナルのリストを返す。

    Args:
        entry: {
            'popularity': int,       # 今回人気
            'odds': float,
            'horse_weight_diff': int,
            'course_type': str,      # 芝/ダート
            'distance': int,
            'headcount': int,
            'race_class': str,
        }
        prev: {
            'finish_position': int,  # 前走着順
            'headcount': int,        # 前走頭数
            'distance': int,         # 前走距離
            'course_type': str,      # 前走コース
            'popularity': int,       # 前走人気
            'race_class': str,
        } or None

    Returns:
        [{'name': str, 'score': float, 'desc': str}, ...]
    """
    if not prev:
        return []

    matched = []

    pop = entry.get('popularity') or 0
    course = entry.get('course_type', '')
    distance = entry.get('distance') or 0
    headcount = entry.get('headcount') or 0
    weight_diff = entry.get('horse_weight_diff')

    prev_pos = prev.get('finish_position') or prev.get('prev_pos')
    prev_hc = prev.get('headcount') or prev.get('prev_hc') or 0
    prev_dist = prev.get('distance') or prev.get('prev_dist') or 0
    prev_course = prev.get('course_type') or prev.get('prev_course') or ''
    prev_pop = prev.get('popularity') or prev.get('prev_pop') or 0

    # ============================================================
    # N1: 前走1-3人気×今回9-11人気（最強: 単勝ROI 124円）
    # 前走は市場が高評価→今回は市場が過小評価 = 典型的ミスプライス
    # ============================================================
    if 9 <= pop <= 11 and 1 <= prev_pop <= 3:
        matched.append({
            'name': 'N1_前走人気急落',
            'score': 3.0,
            'desc': f"前走{prev_pop}人気→今回{pop}人気（市場の過小評価）"
        })

    # ============================================================
    # N2: 前走4-6人気×今回9-11人気（単勝ROI 101円）
    # ============================================================
    if 9 <= pop <= 11 and 4 <= prev_pop <= 6:
        matched.append({
            'name': 'N2_中人気→穴',
            'score': 2.0,
            'desc': f"前走{prev_pop}人気→今回{pop}人気"
        })

    # ============================================================
    # N3: 前走4-6着×同コース×6人気以上（複勝ROI 73円、堅実）
    # 前走中着で見捨てられたが実力は十分
    # ============================================================
    if pop >= 6 and prev_pos and 4 <= prev_pos <= 6 and prev_course == course:
        matched.append({
            'name': 'N3_前走中着同コース',
            'score': 1.5,
            'desc': f"前走{prev_pos}着({course})→今回同コース、{pop}人気"
        })

    # ============================================================
    # N4: 馬体重減少-6以上×6人気以上（単勝ROI 92円）
    # 絞れてきた馬は変身の可能性
    # ============================================================
    if pop >= 6 and weight_diff is not None and weight_diff <= -6:
        matched.append({
            'name': 'N4_体重絞れ',
            'score': 1.5,
            'desc': f"馬体重{weight_diff}kg（絞れてきた）、{pop}人気"
        })

    # ============================================================
    # N5: 前走7-10人気×今回6-8人気（単勝ROI 88円）
    # 前走不人気→今回少し評価上昇、まだ過小評価の余地
    # ============================================================
    if 6 <= pop <= 8 and 7 <= prev_pop <= 10:
        matched.append({
            'name': 'N5_前走不人気→今回中穴',
            'score': 1.0,
            'desc': f"前走{prev_pop}人気→今回{pop}人気"
        })

    # ============================================================
    # N6: ダート10頭以下×6人気以上（複勝ROI 78円）
    # ============================================================
    if pop >= 6 and course == 'ダート' and 0 < headcount <= 10:
        matched.append({
            'name': 'N6_ダート少頭数',
            'score': 1.5,
            'desc': f"ダート{headcount}頭立て、{pop}人気"
        })

    # ============================================================
    # N7: 前走4-6着×頭数減少×6人気以上（複勝ROI 75円）
    # ============================================================
    if pop >= 6 and prev_pos and 4 <= prev_pos <= 6 and prev_hc > 0 and headcount > 0 and headcount <= prev_hc - 2:
        matched.append({
            'name': 'N7_前走中着頭数減少',
            'score': 1.5,
            'desc': f"前走{prev_pos}着{prev_hc}頭→今回{headcount}頭、{pop}人気"
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
