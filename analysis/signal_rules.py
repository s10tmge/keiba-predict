"""
analysis/signal_rules.py - 3軸スコアリングロジック（実データ検証済み）

バックテスト結果（2025年JRA 40,484件）:
  ベースライン（全馬）:        単勝ROI  75.0円
  ベースライン（人気6以上）:   単勝ROI  73.8円

軸A検証済みシグナル（単勝ROI・件数）:
  N1: pop 9-11, prev_pop 1-3                        → ROI 124円  n=711
  N2: pop 9-11, prev_pop 4-6, prev_pos>=7           → ROI 127円  n=910
  N4: pop>=6,   weight_diff<=-8, weight_diff>=-16   → ROI 111円  n=2829
  N8: pop 6-8,  weight_diff<=-8                     → ROI 130円  n=884
  N9: pop 9-11, prev_pop 4-6, weight_diff<=-6       → ROI 186円  n=288

削除済みシグナル（ROI < 100）:
  N3: prev_pos 4-6 × 同コース    → ROI  78円
  N5: pop 6-8, prev_pop 7-10    → ROI  88円
  N6: ダート headcount<=10        → ROI  50円
  N7: prev_pos 4-6 × 頭数減少   → ROI  74円

軸B（前走3F偏差）:
  ※ バックテスト用CSVに prev_last3f カラムなし → 未検証
  実運用では horse_histories.last_3f と race平均3Fで計算

軸C（騎手×コース勝率）:
  ※ バックテスト用CSVに jockey_name カラムなし → 未検証
  実運用では jockey_stats.csv を渡すことで有効化

設計方針:
  スコアは候補馬を絞る網。最終的な買い判断（オッズ・市場評価）は人間が行う。
  「人気6以上限定」「オッズ4倍以上」等の追加フィルターはロジックに含めない。
"""

from typing import Optional


def evaluate_signals(entry: dict, prev: Optional[dict]) -> list[dict]:
    """
    軸Aシグナルを返す。フル評価は score_horse() を使う。
    前走データがない場合は空リスト。
    """
    if not prev:
        return []

    pop = entry.get('popularity') or 0
    weight_diff = entry.get('horse_weight_diff')

    prev_pos = prev.get('finish_position') or prev.get('prev_pos')
    prev_pop = prev.get('popularity') or prev.get('prev_pop') or 0

    matched = []

    # N1: 今回9-11人気 × 前走1-3人気（単勝ROI 124円, n=711）
    # 前走で上位人気だった馬が今回大きく人気を落としているパターン
    if 9 <= pop <= 11 and 1 <= prev_pop <= 3:
        matched.append({
            'name': 'N1_前走人気急落',
            'score': 3.0,
            'desc': f"前走{prev_pop}人気→今回{pop}人気"
        })

    # N2: 今回9-11人気 × 前走4-6人気 × 前走7着以下（単勝ROI 127円, n=910）
    # 前走大敗で人気を落としたが巻き返す可能性
    # ※ 前走1-6着の場合はROI 65円で損なので除外
    if 9 <= pop <= 11 and 4 <= prev_pop <= 6:
        if prev_pos and prev_pos >= 7:
            matched.append({
                'name': 'N2_前走大敗穴',
                'score': 2.5,
                'desc': f"前走{prev_pop}人気{prev_pos}着→今回{pop}人気"
            })

    # N4: 今回6人気以上 × 体重-8〜-16kg（単勝ROI 111円, n=2829）
    # -16kg以下は過度な減量でROI 41円と逆効果のため上限設定
    if pop >= 6 and weight_diff is not None and -16 < weight_diff <= -8:
        matched.append({
            'name': 'N4_体重大幅減',
            'score': 1.5,
            'desc': f"馬体重{weight_diff:+.0f}kg"
        })

    # N8: 今回6-8人気 × 体重-8kg以下（単勝ROI 130円, n=884）
    # 中穴帯で大幅体重減。N4と重複する場合は両方加算
    if 6 <= pop <= 8 and weight_diff is not None and weight_diff <= -8:
        matched.append({
            'name': 'N8_中穴大幅体重減',
            'score': 1.5,
            'desc': f"馬体重{weight_diff:+.0f}kg（6-8人気）"
        })

    # N9: 今回9-11人気 × 前走4-6人気 × 体重-6kg以下（単勝ROI 186円, n=288）
    # N2との複合。体重絞れ×人気急落の相乗効果
    if 9 <= pop <= 11 and 4 <= prev_pop <= 6 and weight_diff is not None and weight_diff <= -6:
        matched.append({
            'name': 'N9_人気落ち体重絞れ',
            'score': 3.0,
            'desc': f"前走{prev_pop}人気×体重{weight_diff:+.0f}kg→今回{pop}人気"
        })

    return matched


def score_axis_b(entry: dict, prev: Optional[dict], race_avg_3f: Optional[float] = None) -> float:
    """
    軸B: 馬の能力スコア（前走3F偏差 + 成績トレンド）

    偏差 = (前走レース全馬平均3F) - (その馬の前走3F)
    プラスなら平均より速い = 能力あり
    """
    if not prev:
        return 0.0

    score = 0.0
    prev_3f = prev.get('last_3f') or prev.get('prev_last3f')
    prev2_pos = entry.get('prev2_pos')
    prev_pos = prev.get('finish_position') or prev.get('prev_pos')

    # B1: 前走3F偏差
    if prev_3f and race_avg_3f:
        diff = race_avg_3f - prev_3f
        if diff >= 2.0:    score += 3.0
        elif diff >= 1.0:  score += 2.0
        elif diff >= 0.5:  score += 1.0
        elif diff <= -1.0: score -= 1.0

    # B2: 成績トレンド（前走 vs 2走前）
    if prev_pos and prev2_pos:
        try:
            p1, p2 = float(prev_pos), float(prev2_pos)
            if p1 < p2:   score += 0.5
            elif p1 > p2: score -= 0.5
        except (TypeError, ValueError):
            pass

    return score


def score_axis_c(jockey_name: str, course_type: str, jockey_stats: dict) -> float:
    """
    軸C: 騎手×コース勝率スコア
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

    Returns:
        (total_score, signals_list)

    スコアの目安（軸B・C含む合計）:
        6.0以上 → 単勝候補として検討
        3.0以上 → 監視対象
        3.0未満 → スルー
    """
    signals = evaluate_signals(entry, prev)
    axis_a = sum(s['score'] for s in signals)
    axis_b = score_axis_b(entry, prev, race_avg_3f)
    axis_c = 0.0
    if jockey_stats:
        axis_c = score_axis_c(
            entry.get('jockey_name', ''),
            entry.get('course_type', ''),
            jockey_stats
        )
    return axis_a + axis_b + axis_c, signals


def build_jockey_stats(jockey_csv_rows: list[dict]) -> dict:
    """jockey_stats.csv の行リストから {(jockey_name, course_type): win_rate} を作る。"""
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
    if score >= 6.0:   return "★★  単勝候補"
    elif score >= 3.0: return "△   監視"
    else:              return "-   スルー"
