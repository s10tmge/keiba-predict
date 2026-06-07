"""
analysis/signal_rules_stakes.py - 重賞専用スコアリングロジック

バックテスト結果（2025年JRA重賞 1,943件 / G1:402 G2:537 G3:1004）:
  ベースライン（重賞全体）: 単勝ROI 68.9円  複勝ROI 74.9円

設計方針:
  重賞は1〜3人気を「軸」として信頼し、
  高スコアの穴馬を「相手」に加える馬連・三連複向け設計。
  単勝は穴馬シグナルが強い場合のみ。

  ※ 体重シグナルは重賞では無効（ROI 30〜36円）のため不採用。
  ※ 平場ロジックは analysis/signal_rules.py を使用。

軸馬（1〜3人気）信頼度の根拠:
  1人気を軸にした馬連ROI: 545円  三連複ROI: 2684円  n=116
  2人気を軸にした馬連ROI: 622円  三連複ROI: 1714円  n=115
  3人気を軸にした馬連ROI: 780円  三連複ROI: 3668円  n=115

検証済みROI（重賞全体・n>=30）:
  S1: 9-11人気 × 前走1-3人気                  → 単勝149円  複勝122円  n=113
  S2: 9-13人気 × 前走4-6人気 × 前走7着以下      → 単勝271円  複勝135円  n=58  ※9-13に拡張
  S3: 7-9人気  × 前走4-6人気 × 前走1-3着        → 単勝289円  複勝153円  n=36  ★
  S4: 7-9人気  × 前走着順改善                  → 単勝160円  複勝 94円  n=164
  S5: 7-9人気  × 前走1着                       → 単勝152円  複勝120円  n=111
  S6: 7-11人気 × 距離延長(100m超) × 前走1-3着   → 単勝153円  複勝 92円  n=96  ★ NEW

B_3F偏差（前走レースの全馬平均3F - その馬の前走3F: 正=平均より速い=能力あり）:
  ※ 予測時点で使える値。今走の3Fは使わない（レース後にしかわからないため）。
  偏差+1.0秒以上 × 穴馬7-11人気 → +2.5点
  偏差+0.5秒以上 × 穴馬7-11人気 → +1.5点
  偏差-0.5秒以下 × 穴馬7-11人気 → -2.0点（M2）
  ※ 重賞での定量検証は未完。race_avg_3fが渡された場合のみ有効化。

マイナスシグナル:
  M1: 10人気+ × 前走7着以下: 単勝35円 → -2.0点
      ただし S1(prev_pop=1-3)の場合は適用しない
  M2: 前走3F遅化0.5秒以上: 単勝53円 → -2.0点

人気上限の根拠:
  S1: 9-13拡張はROI低下（149→107円）のため 9-11 維持
  S2: 9-13拡張でROI改善（182→271円）のため 9-13 採用
  S3/S4/S5: 7-11拡張はROI低下のため 7-9 維持
"""

from typing import Optional


def score_stakes(entry: dict, prev: Optional[dict],
                 prev2_pos: Optional[int] = None,
                 jockey_win_rate: Optional[float] = None) -> tuple[float, list[dict]]:
    """
    重賞専用スコアリング。

    Args:
        entry:            出走馬データ（popularity, course_type, distance 必須）
        prev:             前走データ（finish_position, popularity, last_3f, distance 必須）
        prev2_pos:        2走前の着順（あればトレンド評価に使用）
        jockey_win_rate:  騎手のコース別勝率（jockey_stats.csv から取得）

    Returns:
        (total_score, signals_list)

    スコアの目安:
        5.0以上 → 穴馬として単勝・馬連相手に強く検討
        3.0以上 → 三連複の相手候補
        0以下   → 見送り（マイナスシグナル）
    """
    if not prev:
        return 0.0, []

    pop = entry.get('popularity') or 0
    prev_pop = prev.get('popularity') or prev.get('prev_pop') or 0
    prev_pos = prev.get('finish_position') or prev.get('prev_pos')
    course = entry.get('course_type', '')

    # 前走3F偏差（予測に使える値）
    # = (前走レースの全馬平均3F) - (その馬の前走3F)
    # 正 = 平均より速い = 能力あり
    # ※ race_avg_3f は今走レースではなく「前走レース」の平均。呼び出し元が渡す。
    prev_3f = prev.get('last_3f') or prev.get('prev_last3f')
    race_avg_3f = entry.get('race_avg_3f')  # 前走レースの全馬平均3F
    try:
        f3_diff = float(race_avg_3f) - float(prev_3f)  # 正=平均より速い=能力あり
    except (TypeError, ValueError):
        f3_diff = None

    # 距離変化
    try:
        dist_diff = int(entry.get('distance') or 0) - int(prev.get('distance') or prev.get('prev_dist') or 0)
    except (TypeError, ValueError):
        dist_diff = 0

    signals = []

    # -------------------------------------------------------
    # S1: 今回9-11人気 × 前走1-3人気（単勝ROI 149円, n=113）
    # 重賞で前走上位人気から今回大きく落とされているパターン
    # 拡張案（9-13人気）は ROI 107円 に低下→ 9-11 維持
    # -------------------------------------------------------
    if 9 <= pop <= 11 and 1 <= prev_pop <= 3:
        signals.append({
            'name': 'S1_前走上位人気急落',
            'score': 3.0,
            'desc': f"前走{prev_pop}人気→今回{pop}人気"
        })

    # -------------------------------------------------------
    # S2: 今回9-13人気 × 前走4-6人気 × 前走7着以下（単勝ROI 271円, n=58）
    # 前走大敗で過剰に嫌われているパターン。
    # ※ 9-13 まで拡張で ROI 改善（182→271円）を確認済み
    # -------------------------------------------------------
    if 9 <= pop <= 13 and 4 <= prev_pop <= 6 and prev_pos and prev_pos >= 7:
        signals.append({
            'name': 'S2_前走大敗穴',
            'score': 3.0,
            'desc': f"前走{prev_pop}人気{prev_pos}着→今回{pop}人気"
        })

    # -------------------------------------------------------
    # S3: 今回7-9人気 × 前走4-6人気 × 前走1-3着（単勝ROI 289円, n=36）
    # 前走好走したのに中穴に留まっている＝市場の過小評価が強い
    # 7-11 拡張は ROI 大幅低下（289→158円）→ 7-9 維持
    # -------------------------------------------------------
    if 7 <= pop <= 9 and 4 <= prev_pop <= 6 and prev_pos and 1 <= prev_pos <= 3:
        signals.append({
            'name': 'S3_前走中人気好走',
            'score': 4.0,
            'desc': f"前走{prev_pop}人気{prev_pos}着→今回{pop}人気"
        })

    # -------------------------------------------------------
    # S4: 今回7-9人気 × 前走で着順改善（単勝ROI 160円, n=164）
    # 上昇トレンドにあるのに人気がついていない
    # 7-11 拡張は ROI 低下（160→127円）→ 7-9 維持
    # -------------------------------------------------------
    if 7 <= pop <= 9 and prev_pos and prev2_pos:
        try:
            if float(prev_pos) < float(prev2_pos):
                signals.append({
                    'name': 'S4_上昇トレンド',
                    'score': 2.0,
                    'desc': f"2走前{prev2_pos}着→前走{prev_pos}着（改善）"
                })
        except (TypeError, ValueError):
            pass

    # -------------------------------------------------------
    # S5: 今回7-9人気 × 前走1着（単勝ROI 152円, n=111）
    # 前走勝ち馬が今回7-9人気に落ちているパターン
    # 7-11 拡張はROI低下（152→127円）→ 7-9 維持
    # -------------------------------------------------------
    if 7 <= pop <= 9 and prev_pos == 1:
        signals.append({
            'name': 'S5_前走勝ち馬',
            'score': 2.5,
            'desc': f"前走1着→今回{pop}人気"
        })

    # -------------------------------------------------------
    # S6: 今回7-11人気 × 距離延長(100m超) × 前走1-3着（単勝ROI 153円, n=96）
    # 距離延長で好走実績のある穴馬
    # -------------------------------------------------------
    if 7 <= pop <= 11 and dist_diff > 100 and prev_pos and 1 <= prev_pos <= 3:
        signals.append({
            'name': 'S6_距離延長好走実績',
            'score': 2.0,
            'desc': f"距離+{dist_diff}m×前走{prev_pos}着×{pop}人気"
        })

    # -------------------------------------------------------
    # B_3F: 前走3F偏差ボーナス（予測時点で使える値）
    # 前走レースの全馬平均3Fと比較した偏差。
    # 平均より速い = その馬の能力が高い可能性。
    # ※ 重賞での検証は未完（race_avg_3fのjoinデータが不足）。
    #    実運用時に race_avg_3f を渡すことで有効化。
    # -------------------------------------------------------
    if f3_diff is not None and 7 <= pop <= 11:
        if f3_diff >= 1.0:
            signals.append({
                'name': 'B_3F偏差大',
                'score': 2.5,
                'desc': f"前走3F 平均比+{f3_diff:.1f}秒（能力高め）"
            })
        elif f3_diff >= 0.5:
            signals.append({
                'name': 'B_3F偏差',
                'score': 1.5,
                'desc': f"前走3F 平均比+{f3_diff:.1f}秒"
            })

    # -------------------------------------------------------
    # D_騎手: 騎手勝率ボーナス（補助シグナル）
    # 穴馬帯×騎手勝率15%以上: 単独ROIは弱いが他シグナルの補強に
    # -------------------------------------------------------
    if jockey_win_rate is not None and 7 <= pop <= 11 and jockey_win_rate >= 0.15:
        signals.append({
            'name': 'D_騎手勝率',
            'score': 1.0,
            'desc': f"騎手勝率{jockey_win_rate:.0%}"
        })

    # -------------------------------------------------------
    # マイナスシグナル
    # -------------------------------------------------------

    # W1: 4-6人気 × 前走7着以下（中人気なのに前走大敗 = 過大評価の可能性）
    # 消しではなく警告レベル（-1.0）
    if 4 <= pop <= 6 and prev_pos and prev_pos >= 7:
        signals.append({
            'name': 'W1_中人気前走大敗',
            'score': -1.0,
            'desc': f"今回{pop}人気×前走{prev_pos}着（過大評価に注意）"
        })

    # M1: 10人気以上 × 前走7着以下（単勝ROI 35円）
    # ただし以下のプラスシグナル該当ケースは除外:
    #   S1（prev_pop=1-3）: M1とのnetでも単勝ROI高い
    #   S2（prev_pop=4-6 × prev_pos>=7 × pop=9-13）: S2自体が前走大敗条件
    if pop >= 10 and prev_pos and prev_pos >= 7:
        is_s1_case = (1 <= prev_pop <= 3)
        is_s2_case = (4 <= prev_pop <= 6) and (9 <= pop <= 13)
        if not is_s1_case and not is_s2_case:
            signals.append({
                'name': 'M1_大穴前走大敗',
                'score': -2.0,
                'desc': f"今回{pop}人気×前走{prev_pos}着"
            })

    # M2: 前走3F偏差マイナス（平均より遅い = 能力不足の可能性）
    # ※ B_3Fと同じく race_avg_3f が渡された場合のみ有効
    if f3_diff is not None and f3_diff <= -0.5 and 7 <= pop <= 11:
        signals.append({
            'name': 'M2_3F偏差マイナス',
            'score': -2.0,
            'desc': f"前走3F 平均比{f3_diff:.1f}秒（平均以下）"
        })

    total = sum(s['score'] for s in signals)
    return total, signals


def stakes_verdict(score: float, pop: int) -> str:
    """
    重賞用の買い推奨を返す。
    単勝・複勝・馬連相手の用途別に判定。
    """
    if pop <= 3:
        # 上位人気は軸評価
        if score >= 0:
            return "◎ 軸候補（馬連・三連複の軸）"
        else:
            return "▲ 軸として疑問あり"
    else:
        # 穴馬はスコアで評価
        if score >= 5.0:
            return "★★ 穴馬単勝・馬連相手"
        elif score >= 3.0:
            return "★  三連複の相手候補"
        elif score >= 1.0:
            return "△  抑え"
        elif score < 0:
            return "✕  消し推奨"
        else:
            return "-  スルー"


def evaluate_axis_horse(entry: dict, prev: Optional[dict]) -> tuple[str, float]:
    """
    1〜3人気の軸馬としての信頼度を評価する。

    Returns:
        (verdict_str, confidence_score)
        confidence_score: プラスほど信頼できる軸
    """
    pop = entry.get('popularity') or 0
    prev_pop = prev.get('popularity') or prev.get('prev_pop') or 0 if prev else 0
    prev_pos = prev.get('finish_position') or prev.get('prev_pos') if prev else None

    score = 0.0
    notes = []

    if not prev:
        return "前走データなし", 0.0

    # 前走1-3人気で好走 → 信頼できる
    if 1 <= prev_pop <= 3 and prev_pos and prev_pos <= 3:
        score += 2.0
        notes.append(f"前走{prev_pop}人気{prev_pos}着（安定）")

    # 前走大敗 → 信頼度下がる
    if prev_pos and prev_pos >= 7:
        score -= 1.5
        notes.append(f"前走{prev_pos}着（不安）")

    if score >= 1.5:
        verdict = f"◎ 信頼できる軸 （{'・'.join(notes)}）"
    elif score >= 0:
        verdict = f"○ 標準的な軸 （{'・'.join(notes)}）"
    else:
        verdict = f"▲ 軸として不安 （{'・'.join(notes)}）"

    return verdict, score
