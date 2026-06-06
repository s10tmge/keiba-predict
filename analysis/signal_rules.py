"""
analysis/signal_rules.py - 3軸スコアリングロジック（実データ検証済み）

バックテスト結果（2025年JRA 40,484件）:
  ベースライン（全馬）:   単勝ROI  74.8円
  ベースライン（穴馬>=6人気）: 単勝ROI  73.8円

軸A検証済みシグナル（単勝ROI・件数）:
  N1: pop 9-11, prev_pop 1-3     → ROI 124円  n=711   ✓
  N2: pop 9-11, prev_pop 4-6, prev_pos 7+  → ROI 127円  n=910   ✓ (rev)
  N4: pop>=6, weight_diff<=-8     → ROI 111円  n=2829  ✓ (閾値修正)
  N8: pop 6-8, weight_diff<=-6   → ROI 116円  n=1477  ✓ (新規)
  N9: pop 9-11, prev_pop 4-6, weight_diff<=-6 → ROI 186円 n=288 ✓ (新規)

削除済みシグナル（ROI < 100）:
  N3: prev_pos 4-6 × 同コース      → ROI  78円  → 削除
  N5: pop 6-8, prev_pop 7-10      → ROI  88円  → 削除
  N6: ダート headcount<=10          → ROI  50円  → 削除
  N7: prev_pos 4-6 × 頭数減少      → ROI  74円  → 削除
  N4_old: weight<=-6 全体          → ROI  92円  → 閾値を-8へ修正

軸B（前走3F偏差・成績トレンド）:
  ※ バックテスト用CSVに prev_last3f / prev2_pos カラムなし。
  ※ 実運用では prev_last3f と race_avg_3f があれば B1 が有効。
  B1 スコア修正:
    diff >= 2.0 → +3.0 (旧: +2.0 バグ)
    diff >= 1.0 → +2.0 (旧: +2.0 バグで同値)
    diff >= 0.5 → +1.0
    diff <= -1.0 → -1.0

軸C（騎手×コース勝率）:
  ※ バックテスト用CSVに jockey_name カラムなし。スコアは理論値のみ。
  ※ 勝率 >= 0.20 → +2.0 はデータ不足で未検証。
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
    weight_diff = entry.get('horse_weight_diff')

    prev_pos = prev.get('finish_position') or prev.get('prev_pos')
    prev_pop = prev.get('popularity') or prev.get('prev_pop') or 0

    matched = []

    # N1: 前走1-3人気→今回9-11人気（単勝ROI 124円, n=711）
    # 市場が過小評価しがちなパターン
    if 9 <= pop <= 11 and 1 <= prev_pop <= 3:
        matched.append({'name': 'N1_前走人気急落', 'score': 3.0,
                        'desc': f"前走{prev_pop}人気→今回{pop}人気（市場の過小評価）"})

    # N2: 前走4-6人気→今回9-11人気、かつ前走大敗（7着以下）
    # prev_pos 1-6 の場合は ROI 65円で不採算 → prev_pos 7+ に限定（ROI 127円）
    if 9 <= pop <= 11 and 4 <= prev_pop <= 6:
        if prev_pos and prev_pos >= 7:
            matched.append({'name': 'N2_中人気前走大敗穴', 'score': 2.5,
                            'desc': f"前走{prev_pop}人気{prev_pos}着→今回{pop}人気（巻き返し狙い）"})
        # NOTE: prev_pos 1-6 の場合はシグナルなし（ROI 65円で損）

    # N4: 馬体重-8以上減（単勝ROI 111円, n=2829）
    # 旧閾値-6は ROI 92円で損。-8以下に修正。
    # pop 6-8 の場合は -6 でも ROI 116円なので N8 として別処理。
    if pop >= 9 and weight_diff is not None and weight_diff <= -8:
        matched.append({'name': 'N4_体重大幅絞れ', 'score': 1.5,
                        'desc': f"馬体重{weight_diff:+.0f}kg（9人気以上、大幅減量）"})

    # N8: pop 6-8 × 馬体重-6以上減（単勝ROI 116円, n=1477）
    # 中穴馬の体重減は信頼できるシグナル
    if 6 <= pop <= 8 and weight_diff is not None and weight_diff <= -6:
        matched.append({'name': 'N8_中穴体重絞れ', 'score': 1.5,
                        'desc': f"馬体重{weight_diff:+.0f}kg（6-8人気、減量）"})

    # N9: pop 9-11 × 前走4-6人気 × 体重-6以上減（単勝ROI 186円, n=288）
    # N2+N4の組合せシグナル（相乗効果あり）
    if 9 <= pop <= 11 and 4 <= prev_pop <= 6 and weight_diff is not None and weight_diff <= -6:
        matched.append({'name': 'N9_前走中人気体重絞れ穴', 'score': 3.0,
                        'desc': f"前走{prev_pop}人気×体重{weight_diff:+.0f}kg→今回{pop}人気"})

    return matched


def score_axis_b(entry: dict, prev: Optional[dict], race_avg_3f: Optional[float] = None) -> float:
    """
    軸B: 馬の能力スコア
    - B1: 前走3F偏差（前走レース平均と比較）
    - B2: 2走分の成績トレンド

    注意: 前走3Fタイム(prev_last3f)と2走前着順(prev2_pos)が必要。
    バックテスト用CSVにこれらのカラムが存在しないため未検証。
    実運用時は caller が entry に prev2_pos を、prev に last_3f を渡すこと。
    """
    if not prev:
        return 0.0

    score = 0.0
    prev_3f = prev.get('last_3f') or prev.get('prev_last3f')
    prev2_pos = entry.get('prev2_pos')
    prev_pos = prev.get('finish_position') or prev.get('prev_pos')

    # B1: 前走3F偏差（プラス = 平均より速い = 能力あり）
    # 修正: diff>=2.0 と diff>=1.0 が同値だったバグを修正
    if prev_3f and race_avg_3f:
        diff = race_avg_3f - prev_3f  # 正 = 平均より速い
        if diff >= 2.0:    score += 3.0   # 大幅速い (+3.0, 旧バグ: +2.0)
        elif diff >= 1.0:  score += 2.0   # 速い (+2.0)
        elif diff >= 0.5:  score += 1.0   # やや速い (+1.0)
        elif diff <= -1.0: score -= 1.0   # 遅い (-1.0)

    # B2: 成績トレンド（前走 vs 2走前）
    # 注意: prev2_pos は CSV に存在しないため実運用のみ
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

    注意: バックテスト用 CSV に jockey_name カラムなし。
    実運用時に jockey_stats を渡すことで有効化される。

    スコア設定は理論値（勝率ベース）:
      win_rate >= 0.20 → +2.0
      win_rate >= 0.15 → +1.0
      win_rate >= 0.10 → +0.5
      win_rate < 0.05  → -0.5
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
        entry: 出走馬データ。prev2_pos があれば B2 も計算。
        prev: 前走データ。last_3f があれば B1 も計算。
        race_avg_3f: 前走レースの上がり3F平均（なければNone）
        jockey_stats: {(jockey_name, course_type): win_rate}（なければNone）

    Returns:
        (total_score, signals_list)

    判断基準（軸A+B+Cの合計）:
        score >= 6.0 → ★★ 単勝推奨
        score >= 5.0 → ★  複勝推奨
        score >= 3.0 → △  監視対象
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
    total >= 20 のデータのみ採用（サンプル数不足を除外）。
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
    if score >= 6.0:   return "★★  単勝推奨"
    elif score >= 5.0: return "★   複勝推奨"
    elif score >= 3.0: return "△   監視"
    else:              return "-   スルー"
