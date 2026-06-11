"""
analysis/verify_review_items.py - レビュー指摘事項の一括検証

対象:
  指摘1: 12-13人気+前走1-3人気の空白地帯ROI / S1拡張効果
  指摘2: シグナル重複時のROI（加算モデルの妥当性）
  指摘3: S4着順改善幅別ROI
  指摘6: 混戦フラグ緩和案（軸2頭以上▲）
  追加:  内枠有利の検証（frame_number × 勝率/ROI）
  追加:  S7改善案（逃先行×内枠の複合効果）

実行: python -m analysis.verify_review_items
"""

import sqlite3
from collections import defaultdict
from config import DB_PATH


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def roi_summary(rows, label):
    n = len(rows)
    if not n:
        print(f"  {label}: n=0 (データなし)")
        return
    t_hits = [r['tansho'] for r in rows if r['finish_position'] == 1 and r['tansho']]
    f_hits = [r['fukusho'] for r in rows if r['finish_position'] and r['finish_position'] <= 3 and r['fukusho']]
    t_roi = sum(t_hits) / n / 100
    f_roi = sum(f_hits) / n / 100
    t_rate = len(t_hits) / n * 100
    f_rate = len(f_hits) / n * 100
    print(f"  {label}: n={n}  単勝ROI={t_roi:.0f}円({t_rate:.1f}%)  複勝ROI={f_roi:.0f}円({f_rate:.1f}%)")


# ============================================================
# 共通クエリ（重賞: G1/G2/G3 芝）
# ============================================================
BASE_SQL = """
SELECT
    e.race_id, e.horse_number, e.popularity, e.frame_number,
    res.finish_position,
    hh.popularity       AS prev_pop,
    hh.finish_position  AS prev_pos,
    hh2.finish_position AS prev2_pos,
    hh.corner_position  AS prev_corner,
    hh.headcount        AS prev_headcount,
    hh.distance         AS prev_dist,
    e.horse_weight_diff AS weight_diff,
    pay_t.payout  AS tansho,
    pay_f.payout  AS fukusho
FROM entries e
JOIN races r   ON r.race_id = e.race_id
JOIN results res ON res.race_id = e.race_id AND res.horse_id = e.horse_id
-- 前走
LEFT JOIN horse_histories hh ON hh.horse_id = e.horse_id
  AND hh.race_date = (
    SELECT MAX(h2.race_date) FROM horse_histories h2
    WHERE h2.horse_id = e.horse_id AND h2.race_date < r.date
  )
-- 2走前
LEFT JOIN horse_histories hh2 ON hh2.horse_id = e.horse_id
  AND hh2.race_date = (
    SELECT MAX(h3.race_date) FROM horse_histories h3
    WHERE h3.horse_id = e.horse_id AND h3.race_date < hh.race_date
  )
LEFT JOIN payouts pay_t ON pay_t.race_id = e.race_id AND pay_t.bet_type = '単勝'
  AND pay_t.combination = CAST(e.horse_number AS TEXT)
LEFT JOIN payouts pay_f ON pay_f.race_id = e.race_id AND pay_f.bet_type = '複勝'
  AND pay_f.combination = CAST(e.horse_number AS TEXT)
WHERE r.race_class IN ('G1','G2','G3')
  AND r.course_type = '芝'
  AND res.finish_position IS NOT NULL
"""

BASE_SQL_ALL = BASE_SQL.replace("AND r.course_type = '芝'", "")


def pace_style(corner_position, headcount):
    if not corner_position or not headcount or headcount <= 0:
        return None
    parts = [p.strip() for p in str(corner_position).split('-') if p.strip().isdigit()]
    if not parts:
        return None
    try:
        ratio = int(parts[-1]) / headcount
        if ratio <= 0.25:   return "逃先行"
        elif ratio <= 0.70: return "中団"
        else:               return "後方"
    except (ValueError, ZeroDivisionError):
        return None


def main():
    conn = get_conn()
    rows = conn.execute(BASE_SQL).fetchall()
    rows_all = conn.execute(BASE_SQL_ALL).fetchall()
    print(f"重賞芝 総レコード数: {len(rows)}")
    print(f"重賞全コース 総レコード数: {len(rows_all)}")

    # ============================================================
    # 指摘1: S1の人気帯別ROI（空白地帯 12-13人気 の検証）
    # ============================================================
    print("\n" + "="*60)
    print("【指摘1】S1人気帯の空白地帯検証")
    print("="*60)

    for pop_lo, pop_hi, label in [
        (9, 11, "既存S1 (9-11人気+前走1-3人気)"),
        (12, 13, "空白地帯 (12-13人気+前走1-3人気)"),
        (9, 13, "S1拡張案 (9-13人気+前走1-3人気)"),
        (11, 11, "境界 11人気のみ"),
        (12, 12, "境界 12人気のみ"),
    ]:
        sub = [r for r in rows
               if pop_lo <= r['popularity'] <= pop_hi
               and r['prev_pop'] and 1 <= r['prev_pop'] <= 3]
        roi_summary(sub, label)

    # ============================================================
    # 指摘2: シグナル重複時のROI検証
    # ============================================================
    print("\n" + "="*60)
    print("【指摘2】シグナル重複時のROI（加算モデル検証）")
    print("="*60)

    def count_signals(r):
        pop = r['popularity']
        prev_pop = r['prev_pop']
        prev_pos = r['prev_pos']
        prev2_pos = r['prev2_pos']
        dist_diff = 0  # distanceデータがなければスキップ
        sigs = 0
        if pop and prev_pop and prev_pos:
            if 9 <= pop <= 11 and 1 <= prev_pop <= 3: sigs += 1  # S1
            if 9 <= pop <= 13 and 4 <= prev_pop <= 6 and prev_pos >= 7: sigs += 1  # S2
            if 7 <= pop <= 9 and 4 <= prev_pop <= 6 and 1 <= prev_pos <= 3: sigs += 1  # S3
            if 7 <= pop <= 9 and prev2_pos and prev_pos < prev2_pos: sigs += 1  # S4
            if 7 <= pop <= 9 and prev_pos == 1: sigs += 1  # S5
            pace = pace_style(r['prev_corner'], r['prev_headcount'])
            if pace == "逃先行" and 7 <= pop <= 11: sigs += 1  # S7
            if pace == "後方" and prev_pos >= 7 and 7 <= pop <= 11: sigs += 1  # S8
        return sigs

    for sig_count, label in [(1, "シグナル1個のみ"), (2, "シグナル2個"), (3, "シグナル3個以上")]:
        if sig_count == 3:
            sub = [r for r in rows if count_signals(r) >= 3]
        else:
            sub = [r for r in rows if count_signals(r) == sig_count]
        roi_summary(sub, label)

    # スコア帯別（★★=5.0以上を模擬）
    print("  ※スコア5.0以上の近似: S3+S4重複(6.0点相当)")
    sub_s3s4 = [r for r in rows
                if r['popularity'] and 7 <= r['popularity'] <= 9
                and r['prev_pop'] and 4 <= r['prev_pop'] <= 6
                and r['prev_pos'] and 1 <= r['prev_pos'] <= 3
                and r['prev2_pos'] and r['prev_pos'] < r['prev2_pos']]
    roi_summary(sub_s3s4, "S3+S4重複(6.0点・★★帯)")

    sub_s1s4 = [r for r in rows
                if r['popularity'] and 9 <= r['popularity'] <= 11
                and r['prev_pop'] and 1 <= r['prev_pop'] <= 3
                and r['prev2_pos'] and r['prev_pos'] and r['prev_pos'] < r['prev2_pos']]
    roi_summary(sub_s1s4, "S1+S4重複(5.0点・★★帯)")

    # ============================================================
    # 指摘3: S4改善幅別ROI
    # ============================================================
    print("\n" + "="*60)
    print("【指摘3】S4 着順改善幅別ROI")
    print("="*60)

    s4_base = [r for r in rows
               if r['popularity'] and 7 <= r['popularity'] <= 9
               and r['prev_pos'] and r['prev2_pos']
               and r['prev_pos'] < r['prev2_pos']]

    for label, lo, hi in [
        ("1着分改善", 1, 1),
        ("2着分改善", 2, 2),
        ("3-5着分改善", 3, 5),
        ("6着分以上改善", 6, 99),
    ]:
        sub = [r for r in s4_base if lo <= (r['prev2_pos'] - r['prev_pos']) <= hi]
        roi_summary(sub, label)

    roi_summary(s4_base, "S4全体(参考)")

    # ============================================================
    # 指摘6: 混戦フラグ緩和案
    # ============================================================
    print("\n" + "="*60)
    print("【指摘6】混戦フラグ緩和案")
    print("="*60)

    # race_idごとに1-3人気の前走着順を収集
    race_axis = defaultdict(list)
    for r in rows:
        if r['popularity'] and 1 <= r['popularity'] <= 3 and r['prev_pos']:
            race_axis[r['race_id']].append(r['prev_pos'])

    # 各カテゴリのrace_idを分類
    cat_current  = set()  # 現行: 全員▲（全員7着以下）
    cat_2bad     = set()  # 緩和案: 2頭以上が7着以下
    cat_1bad     = set()  # 1頭だけ7着以下
    cat_all_ok   = set()  # 全員6着以内

    for race_id, positions in race_axis.items():
        if len(positions) < 2:
            continue
        bad = sum(1 for p in positions if p >= 7)
        if bad == 0:
            cat_all_ok.add(race_id)
        elif bad == 1:
            cat_1bad.add(race_id)
        elif bad >= 2 and bad < len(positions):
            cat_2bad.add(race_id)
        else:
            cat_current.add(race_id)

    for label, race_set in [
        ("全軸OK(全員6着以内)", cat_all_ok),
        ("軸1頭が7着以下", cat_1bad),
        ("軸2頭以上が7着以下(緩和案)", cat_2bad),
        ("全軸7着以下(現行混戦フラグ)", cat_current),
    ]:
        sub = [r for r in rows if r['race_id'] in race_set and r['popularity'] and 4 <= r['popularity']]
        print(f"  {label}: races={len(race_set)}", end="")
        # 穴馬シグナル該当馬のROI
        signal_sub = [r for r in sub if r['popularity'] and 7 <= r['popularity'] <= 11]
        if signal_sub:
            n = len(signal_sub)
            t = sum(r['tansho']/100 for r in signal_sub if r['finish_position']==1 and r['tansho'])
            print(f"  穴馬帯単勝ROI={t/n*100:.0f}円(n={n})")
        else:
            print()

    # ============================================================
    # 追加: 枠番×ROI（内枠有利の検証）
    # ============================================================
    print("\n" + "="*60)
    print("【追加】枠番別 ROI（重賞芝）")
    print("="*60)

    for frame in range(1, 9):
        sub = [r for r in rows if r['frame_number'] == frame]
        n = len(sub)
        if not n:
            continue
        t = sum(r['tansho']/100 for r in sub if r['finish_position']==1 and r['tansho'])
        f = sum(r['fukusho']/100 for r in sub if r['finish_position'] and r['finish_position']<=3 and r['fukusho'])
        win_rate = sum(1 for r in sub if r['finish_position']==1) / n * 100
        print(f"  {frame}枠: n={n}  勝率={win_rate:.1f}%  単勝ROI={t/n*100:.0f}円  複勝ROI={f/n*100:.0f}円")

    # 内枠(1-3枠)vs外枠(6-8枠)
    print()
    for label, lo, hi in [("内枠(1-3枠)", 1, 3), ("中枠(4-5枠)", 4, 5), ("外枠(6-8枠)", 6, 8)]:
        sub = [r for r in rows if r['frame_number'] and lo <= r['frame_number'] <= hi]
        roi_summary(sub, label)

    # 穴馬帯(7-11人気)での枠別
    print("\n  ── 穴馬帯(7-11人気)に限定 ──")
    for label, lo, hi in [("内枠(1-3枠)", 1, 3), ("中枠(4-5枠)", 4, 5), ("外枠(6-8枠)", 6, 8)]:
        sub = [r for r in rows
               if r['frame_number'] and lo <= r['frame_number'] <= hi
               and r['popularity'] and 7 <= r['popularity'] <= 11]
        roi_summary(sub, label)

    # ============================================================
    # 追加: S7改善案（逃先行×内枠）
    # ============================================================
    print("\n" + "="*60)
    print("【追加】S7改善案: 逃先行×枠番の組み合わせ")
    print("="*60)

    s7_base = [r for r in rows
               if r['popularity'] and 7 <= r['popularity'] <= 11
               and pace_style(r['prev_corner'], r['prev_headcount']) == "逃先行"]

    for label, lo, hi in [("内枠(1-3枠)", 1, 3), ("中枠(4-5枠)", 4, 5), ("外枠(6-8枠)", 6, 8), ("全枠", 1, 8)]:
        sub = [r for r in s7_base if r['frame_number'] and lo <= r['frame_number'] <= hi] if lo < 8 else s7_base
        roi_summary(sub, f"S7逃先行×{label}")

    conn.close()
    print("\n検証完了。結果をクロードに貼り付けてください。")


if __name__ == "__main__":
    main()
