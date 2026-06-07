"""
analysis/signal_rules_stakes.py - 重賞専用スコアリングロジック

バックテスト結果（2025年JRA重賞 1,943件 / 芝1,717件）:
  ベースライン（重賞全体）: 単勝ROI 68.9円  複勝ROI 74.9円
  ベースライン（芝重賞）:   単勝ROI 71.7円  複勝ROI 75.3円

設計方針:
  重賞は1〜3人気を「軸」として信頼し、
  高スコアの穴馬を「相手」に加える馬連・三連複向け設計。
  単勝は穴馬シグナルが強い場合のみ。

  ※ 体重シグナル（N4・N8）は重賞では無効（ROI 30〜36円）のため不採用。
  ※ 平場ロジックは analysis/signal_rules.py を使用。

軸馬（1〜3人気）信頼度の根拠:
  1人気を軸にした馬連ROI: 545円  三連複ROI: 2684円  n=116
  2人気を軸にした馬連ROI: 622円  三連複ROI: 1714円  n=115
  3人気を軸にした馬連ROI: 780円  三連複ROI: 3668円  n=115
  → 軸として使う場合、馬連・三連複ともに期待値プラス

穴馬シグナル検証済みROI（芝重賞）:
  S1: 今回9-11人気 × 前走1-3人気                  → 単勝149円  複勝122円  n=113
  S2: 今回9-11人気 × 前走4-6人気 × 前走7着以下      → 単勝182円  複勝129円  n=37
  S3: 今回7-9人気 × 前走4-6人気 × 前走1-3着        → 単勝268円  複勝164円  n=30  ★
  S4: 今回7-9人気 × 前走で着順改善                  → 単勝161円  複勝 92円  n=148
  S5: 今回7-9人気 × 前走1着                       → 単勝163円  複勝118円  n=103

G3限定追加:
  S1×G3: ROI 116円  n=54
  S3×G3: ROI 267円  n=52（特に強い）
"""

from typing import Optional


def score_stakes(entry: dict, prev: Optional[dict],
                 prev2_pos: Optional[int] = None) -> tuple[float, list[dict]]:
    """
    重賞専用スコアリング。

    Args:
        entry:     出走馬データ（popularity, course_type 必須）
        prev:      前走データ（finish_position, popularity 必須）
        prev2_pos: 2走前の着順（あればトレンド評価に使用）

    Returns:
        (total_score, signals_list)

    スコアの目安:
        5.0以上 → 穴馬として単勝・馬連相手に検討
        3.0以上 → 三連複の相手候補
        0以下   → 見送り（マイナスシグナル）
    """
    if not prev:
        return 0.0, []

    pop = entry.get('popularity') or 0
    prev_pop = prev.get('popularity') or prev.get('prev_pop') or 0
    prev_pos = prev.get('finish_position') or prev.get('prev_pos')
    course = entry.get('course_type', '')

    signals = []

    # -------------------------------------------------------
    # S1: 今回9-11人気 × 前走1-3人気（単勝ROI 149円, n=113）
    # 重賞で前走上位人気から今回大きく落とされているパターン
    # -------------------------------------------------------
    if 9 <= pop <= 11 and 1 <= prev_pop <= 3:
        signals.append({
            'name': 'S1_前走上位人気急落',
            'score': 3.0,
            'desc': f"前走{prev_pop}人気→今回{pop}人気"
        })

    # -------------------------------------------------------
    # S2: 今回9-11人気 × 前走4-6人気 × 前走7着以下（単勝ROI 182円, n=37）
    # 前走大敗で過剰に嫌われているパターン
    # -------------------------------------------------------
    if 9 <= pop <= 11 and 4 <= prev_pop <= 6 and prev_pos and prev_pos >= 7:
        signals.append({
            'name': 'S2_前走大敗穴',
            'score': 3.0,
            'desc': f"前走{prev_pop}人気{prev_pos}着→今回{pop}人気"
        })

    # -------------------------------------------------------
    # S3: 今回7-9人気 × 前走4-6人気 × 前走1-3着（単勝ROI 268円, n=30）
    # 前走好走したのに中穴に留まっている＝市場の過小評価が強い
    # -------------------------------------------------------
    if 7 <= pop <= 9 and 4 <= prev_pop <= 6 and prev_pos and 1 <= prev_pos <= 3:
        signals.append({
            'name': 'S3_前走中人気好走',
            'score': 4.0,
            'desc': f"前走{prev_pop}人気{prev_pos}着→今回{pop}人気"
        })

    # -------------------------------------------------------
    # S4: 今回7-9人気 × 前走で着順改善（単勝ROI 161円, n=148）
    # 上昇トレンドにあるのに人気がついていない
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
    # S5: 今回7-9人気 × 前走1着（単勝ROI 163円, n=103）
    # 前走勝ち馬が今回7-9人気に落ちているパターン
    # -------------------------------------------------------
    if 7 <= pop <= 9 and prev_pos == 1:
        signals.append({
            'name': 'S5_前走勝ち馬',
            'score': 2.5,
            'desc': f"前走1着→今回{pop}人気"
        })

    # -------------------------------------------------------
    # マイナスシグナル
    # -------------------------------------------------------
    # 10人気以上 × 前走7着以下: 単勝ROI 16円（重賞では明確に不採算）
    if pop >= 10 and prev_pos and prev_pos >= 7:
        signals.append({
            'name': 'M1_大穴前走大敗',
            'score': -2.0,
            'desc': f"今回{pop}人気 × 前走{prev_pos}着"
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
