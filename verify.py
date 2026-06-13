"""
verify.py - レビュー指摘事項の一括検証（スタンドアロン版）
keiba.db と同じフォルダに置いて実行: python verify.py > verify_result.txt
"""

import sqlite3
from collections import defaultdict

DB_PATH = "keiba.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def roi_summary(rows, label):
    n = len(rows)
    if not n:
        print(f"  {label}: n=0")
        return
    t_hits = [r['tansho'] for r in rows if r['finish_position'] == 1 and r['tansho']]
    f_hits = [r['fukusho'] for r in rows if r['finish_position'] and r['finish_position'] <= 3 and r['fukusho']]
    t_roi = sum(t_hits) / n
    f_roi = sum(f_hits) / n
    t_rate = len(t_hits) / n * 100
    f_rate = len(f_hits) / n * 100
    print(f"  {label}: n={n}  単勝ROI={t_roi:.0f}円({t_rate:.1f}%)  複勝ROI={f_roi:.0f}円({f_rate:.1f}%)")


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


BASE_SQL = """
SELECT
    e.race_id, e.horse_number, e.popularity, e.frame_number,
    r.distance AS race_dist,
    res.finish_position,
    hh.popularity       AS prev_pop,
    hh.finish_position  AS prev_pos,
    hh2.finish_position AS prev2_pos,
    hh.corner_position  AS prev_corner,
    hh.headcount        AS prev_headcount,
    hh.distance         AS prev_dist,
    pay_t.payout  AS tansho,
    pay_f.payout  AS fukusho
FROM entries e
JOIN races r   ON r.race_id = e.race_id
JOIN results res ON res.race_id = e.race_id AND res.horse_id = e.horse_id
LEFT JOIN horse_histories hh ON hh.horse_id = e.horse_id
  AND hh.race_date = (
    SELECT MAX(h2.race_date) FROM horse_histories h2
    WHERE h2.horse_id = e.horse_id AND h2.race_date < r.date
  )
LEFT JOIN horse_histories hh2 ON hh2.horse_id = e.horse_id
  AND hh2.race_date = (
    SELECT MAX(h3.race_date) FROM horse_histories h3
    WHERE h3.horse_id = e.horse_id AND h3.race_date < hh.race_date
  )
LEFT JOIN payouts pay_t ON pay_t.race_id = e.race_id AND pay_t.bet_type = '単勝'
  AND pay_t.combination = CAST(e.horse_number AS TEXT)
LEFT JOIN payouts pay_f ON pay_f.race_id = e.race_id AND pay_f.bet_type = '複勝'
  AND pay_f.combination = CAST(e.horse_number AS TEXT)
WHERE (
    r.race_name LIKE '%(G1)%' OR r.race_name LIKE '%(G2)%' OR r.race_name LIKE '%(G3)%'
    OR r.race_name LIKE '%（G1）%' OR r.race_name LIKE '%（G2）%' OR r.race_name LIKE '%（G3）%'
  )
  AND TRIM(r.course_type) = '芝'
  AND res.finish_position IS NOT NULL
"""


def main():
    conn = get_conn()
    rows = conn.execute(BASE_SQL).fetchall()
    print(f"重賞芝 総レコード数: {len(rows)}")

    # ============================================================
    # 指摘1: S1の人気帯別ROI
    # ============================================================
    print("\n" + "="*60)
    print("【指摘1】S1人気帯の空白地帯検証（前走1-3人気）")
    print("="*60)
    for pop_lo, pop_hi, label in [
        (9, 11, "既存S1 (9-11人気)"),
        (12, 13, "空白地帯 (12-13人気)"),
        (9, 13, "S1拡張案 (9-13人気)"),
        (11, 11, "境界 11人気"),
        (12, 12, "境界 12人気"),
    ]:
        sub = [r for r in rows
               if r['popularity'] and pop_lo <= r['popularity'] <= pop_hi
               and r['prev_pop'] and 1 <= r['prev_pop'] <= 3]
        roi_summary(sub, label)

    # ============================================================
    # 指摘2: シグナル重複時のROI
    # ============================================================
    print("\n" + "="*60)
    print("【指摘2】シグナル重複時のROI（加算モデル検証）")
    print("="*60)

    def count_signals(r):
        pop = r['popularity']
        prev_pop = r['prev_pop']
        prev_pos = r['prev_pos']
        prev2_pos = r['prev2_pos']
        race_dist = r['race_dist'] or 0
        prev_dist = r['prev_dist'] or 0
        dist_diff = race_dist - prev_dist
        sigs = []
        if not (pop and prev_pop and prev_pos):
            return sigs
        if 9 <= pop <= 11 and 1 <= prev_pop <= 3: sigs.append('S1')
        if 9 <= pop <= 13 and 4 <= prev_pop <= 6 and prev_pos >= 7: sigs.append('S2')
        if 7 <= pop <= 9 and 4 <= prev_pop <= 6 and 1 <= prev_pos <= 3: sigs.append('S3')
        if 7 <= pop <= 9 and prev2_pos and prev_pos < prev2_pos: sigs.append('S4')
        if 7 <= pop <= 9 and prev_pos == 1: sigs.append('S5')
        if 7 <= pop <= 11 and dist_diff > 100 and 1 <= prev_pos <= 3: sigs.append('S6')
        pace = pace_style(r['prev_corner'], r['prev_headcount'])
        if pace == "逃先行" and 7 <= pop <= 11 and abs(dist_diff) <= 100: sigs.append('S7')
        if pace == "後方" and prev_pos >= 7 and 7 <= pop <= 11: sigs.append('S8')
        return sigs

    for sig_count, label in [(0,"シグナルなし"), (1,"シグナル1個"), (2,"シグナル2個"), (3,"シグナル3個以上")]:
        if sig_count == 3:
            sub = [r for r in rows if len(count_signals(r)) >= 3]
        else:
            sub = [r for r in rows if len(count_signals(r)) == sig_count]
        roi_summary(sub, label)

    # スコア5.0以上相当の重複パターン
    print()
    combos = [
        ("S3+S4(6.0点★★)", lambda r: 'S3' in count_signals(r) and 'S4' in count_signals(r)),
        ("S1+S4(5.0点★★)", lambda r: 'S1' in count_signals(r) and 'S4' in count_signals(r)),
        ("S1+S5(5.5点★★)", lambda r: 'S1' in count_signals(r) and 'S5' in count_signals(r)),
        ("S3+S7(6.0点★★)", lambda r: 'S3' in count_signals(r) and 'S7' in count_signals(r)),
    ]
    for label, fn in combos:
        sub = [r for r in rows if fn(r)]
        roi_summary(sub, label)

    # ============================================================
    # 指摘3: S4改善幅別ROI
    # ============================================================
    print("\n" + "="*60)
    print("【指摘3】S4 着順改善幅別ROI（7-9人気）")
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
    print("【指摘6】混戦フラグ緩和案（軸候補の前走着順構成）")
    print("="*60)
    race_axis = defaultdict(list)
    for r in rows:
        if r['popularity'] and 1 <= r['popularity'] <= 3 and r['prev_pos']:
            race_axis[r['race_id']].append(r['prev_pos'])

    cat = {'all_ok': set(), 'one_bad': set(), 'two_bad': set(), 'all_bad': set()}
    for race_id, positions in race_axis.items():
        if len(positions) < 2:
            continue
        bad = sum(1 for p in positions if p >= 7)
        if bad == 0: cat['all_ok'].add(race_id)
        elif bad == 1: cat['one_bad'].add(race_id)
        elif bad < len(positions): cat['two_bad'].add(race_id)
        else: cat['all_bad'].add(race_id)

    for label, key in [
        ("全軸OK(全員6着以内)", 'all_ok'),
        ("軸1頭が7着以下", 'one_bad'),
        ("軸2頭以上が7着以下(緩和案)", 'two_bad'),
        ("全軸7着以下(現行混戦フラグ)", 'all_bad'),
    ]:
        rids = cat[key]
        # そのレースの穴馬帯(7-11人気)のROI
        sub = [r for r in rows if r['race_id'] in rids
               and r['popularity'] and 7 <= r['popularity'] <= 11]
        print(f"  {label}: races={len(rids)}", end="  ")
        if sub:
            n = len(sub)
            t = sum(r['tansho']/100 for r in sub if r['finish_position']==1 and r['tansho'])
            f = sum(r['fukusho']/100 for r in sub if r['finish_position'] and r['finish_position']<=3 and r['fukusho'])
            print(f"穴馬帯n={n} 単勝ROI={t/n*100:.0f}円  複勝ROI={f/n*100:.0f}円")
        else:
            print()

    # ============================================================
    # 追加: 枠番別ROI
    # ============================================================
    print("\n" + "="*60)
    print("【追加】枠番別ROI（重賞芝・全人気）")
    print("="*60)
    for frame in range(1, 9):
        sub = [r for r in rows if r['frame_number'] == frame]
        n = len(sub)
        if not n: continue
        t = sum(r['tansho']/100 for r in sub if r['finish_position']==1 and r['tansho'])
        f = sum(r['fukusho']/100 for r in sub if r['finish_position'] and r['finish_position']<=3 and r['fukusho'])
        win = sum(1 for r in sub if r['finish_position']==1) / n * 100
        print(f"  {frame}枠: n={n}  勝率={win:.1f}%  単勝ROI={t/n*100:.0f}円  複勝ROI={f/n*100:.0f}円")

    print()
    for label, lo, hi in [("内枠(1-3枠)",1,3),("中枠(4-5枠)",4,5),("外枠(6-8枠)",6,8)]:
        roi_summary([r for r in rows if r['frame_number'] and lo<=r['frame_number']<=hi], label)

    print("\n  ── 穴馬帯(7-11人気)に限定 ──")
    for label, lo, hi in [("内枠(1-3枠)",1,3),("中枠(4-5枠)",4,5),("外枠(6-8枠)",6,8)]:
        sub = [r for r in rows if r['frame_number'] and lo<=r['frame_number']<=hi
               and r['popularity'] and 7<=r['popularity']<=11]
        roi_summary(sub, label)

    # ============================================================
    # 追加: S7改善案（逃先行×枠番）
    # ============================================================
    print("\n" + "="*60)
    print("【追加】S7改善案: 逃先行(7-11人気)×枠番")
    print("="*60)
    s7_base = [r for r in rows
               if r['popularity'] and 7 <= r['popularity'] <= 11
               and pace_style(r['prev_corner'], r['prev_headcount']) == "逃先行"]
    roi_summary(s7_base, "S7全体(参考)")
    for label, lo, hi in [("内枠(1-3枠)",1,3),("中枠(4-5枠)",4,5),("外枠(6-8枠)",6,8)]:
        sub = [r for r in s7_base if r['frame_number'] and lo<=r['frame_number']<=hi]
        roi_summary(sub, f"S7×{label}")

    # ============================================================
    # 新シグナル候補1: 休み明け（前走から中10週以上）
    # ============================================================
    print("\n" + "="*60)
    print("【新候補1】休み明け（前走から中10週以上）× 穴馬帯")
    print("="*60)

    rows_dated = conn.execute(BASE_SQL.replace(
        "LEFT JOIN horse_histories hh ON hh.horse_id = e.horse_id",
        "LEFT JOIN horse_histories hh ON hh.horse_id = e.horse_id"
    ) + " AND hh.race_date IS NOT NULL").fetchall()

    # race_dateとhh.race_dateの差（日数）を計算
    import datetime
    def weeks_since_prev(race_date_str, prev_date_str):
        try:
            d1 = datetime.date.fromisoformat(race_date_str)
            d2 = datetime.date.fromisoformat(prev_date_str)
            return (d1 - d2).days / 7
        except:
            return None

    rows_w = conn.execute("""
        SELECT e.popularity, e.frame_number,
               res.finish_position,
               r.date AS race_date,
               hh.race_date AS prev_date,
               pay_t.payout AS tansho,
               pay_f.payout AS fukusho
        FROM entries e
        JOIN races r ON r.race_id = e.race_id
        JOIN results res ON res.race_id = e.race_id AND res.horse_id = e.horse_id
        LEFT JOIN horse_histories hh ON hh.horse_id = e.horse_id
          AND hh.race_date = (
            SELECT MAX(h2.race_date) FROM horse_histories h2
            WHERE h2.horse_id = e.horse_id AND h2.race_date < r.date
          )
        LEFT JOIN payouts pay_t ON pay_t.race_id = e.race_id AND pay_t.bet_type = '単勝'
          AND pay_t.combination = CAST(e.horse_number AS TEXT)
        LEFT JOIN payouts pay_f ON pay_f.race_id = e.race_id AND pay_f.bet_type = '複勝'
          AND pay_f.combination = CAST(e.horse_number AS TEXT)
        WHERE (r.race_name LIKE '%(G1)%' OR r.race_name LIKE '%(G2)%' OR r.race_name LIKE '%(G3)%'
            OR r.race_name LIKE '%（G1）%' OR r.race_name LIKE '%（G2）%' OR r.race_name LIKE '%（G3）%')
          AND TRIM(r.course_type) = '芝'
          AND res.finish_position IS NOT NULL
          AND hh.race_date IS NOT NULL
    """).fetchall()

    for label, w_lo, w_hi, pop_lo, pop_hi in [
        ("中10週以上(全人気)", 10, 999, 1, 18),
        ("中10週以上×穴馬7-11人気", 10, 999, 7, 11),
        ("中6-9週×穴馬7-11人気", 6, 9, 7, 11),
        ("中5週以内×穴馬7-11人気", 0, 5, 7, 11),
        ("連闘〜中2週×穴馬7-11人気", 0, 2, 7, 11),
    ]:
        sub = []
        for r in rows_w:
            if not (pop_lo <= (r['popularity'] or 0) <= pop_hi):
                continue
            w = weeks_since_prev(r['race_date'], r['prev_date'])
            if w is not None and w_lo <= w <= w_hi:
                sub.append(r)
        roi_summary(sub, label)

    # ============================================================
    # 新シグナル候補2: 前走頭数 → 今回多頭数
    # ============================================================
    print("\n" + "="*60)
    print("【新候補2】前走頭数変化 × 穴馬帯(7-11人気)")
    print("="*60)

    rows_hc = conn.execute("""
        SELECT e.popularity, res.finish_position,
               hh.headcount AS prev_hc,
               (SELECT COUNT(*) FROM entries e2 WHERE e2.race_id = e.race_id) AS cur_hc,
               pay_t.payout AS tansho, pay_f.payout AS fukusho
        FROM entries e
        JOIN races r ON r.race_id = e.race_id
        JOIN results res ON res.race_id = e.race_id AND res.horse_id = e.horse_id
        LEFT JOIN horse_histories hh ON hh.horse_id = e.horse_id
          AND hh.race_date = (
            SELECT MAX(h2.race_date) FROM horse_histories h2
            WHERE h2.horse_id = e.horse_id AND h2.race_date < r.date
          )
        LEFT JOIN payouts pay_t ON pay_t.race_id = e.race_id AND pay_t.bet_type = '単勝'
          AND pay_t.combination = CAST(e.horse_number AS TEXT)
        LEFT JOIN payouts pay_f ON pay_f.race_id = e.race_id AND pay_f.bet_type = '複勝'
          AND pay_f.combination = CAST(e.horse_number AS TEXT)
        WHERE (r.race_name LIKE '%(G1)%' OR r.race_name LIKE '%(G2)%' OR r.race_name LIKE '%(G3)%'
            OR r.race_name LIKE '%（G1）%' OR r.race_name LIKE '%（G2）%' OR r.race_name LIKE '%（G3）%')
          AND TRIM(r.course_type) = '芝'
          AND res.finish_position IS NOT NULL
          AND e.popularity BETWEEN 7 AND 11
          AND hh.headcount IS NOT NULL
    """).fetchall()

    for label, fn in [
        ("前走少頭数(8頭以下)→今回", lambda r: r['prev_hc'] and r['prev_hc'] <= 8),
        ("前走少頭数→今回多頭数(+4頭以上)", lambda r: r['prev_hc'] and r['prev_hc'] <= 8 and r['cur_hc'] and r['cur_hc'] >= r['prev_hc'] + 4),
        ("前走多頭数(14頭以上)", lambda r: r['prev_hc'] and r['prev_hc'] >= 14),
        ("頭数増加(+4頭以上)", lambda r: r['prev_hc'] and r['cur_hc'] and r['cur_hc'] >= r['prev_hc'] + 4),
        ("頭数減少(-4頭以下)", lambda r: r['prev_hc'] and r['cur_hc'] and r['cur_hc'] <= r['prev_hc'] - 4),
    ]:
        sub = [r for r in rows_hc if fn(r)]
        roi_summary(sub, label)

    # ============================================================
    # 新シグナル候補3: ダート→芝転換 × 穴馬帯
    # ============================================================
    print("\n" + "="*60)
    print("【新候補3】コース転換(ダート→芝) × 人気帯")
    print("="*60)

    rows_cs = conn.execute("""
        SELECT e.popularity, res.finish_position,
               hh.course_type AS prev_course,
               hh.finish_position AS prev_pos,
               hh.popularity AS prev_pop,
               pay_t.payout AS tansho, pay_f.payout AS fukusho
        FROM entries e
        JOIN races r ON r.race_id = e.race_id
        JOIN results res ON res.race_id = e.race_id AND res.horse_id = e.horse_id
        LEFT JOIN horse_histories hh ON hh.horse_id = e.horse_id
          AND hh.race_date = (
            SELECT MAX(h2.race_date) FROM horse_histories h2
            WHERE h2.horse_id = e.horse_id AND h2.race_date < r.date
          )
        LEFT JOIN payouts pay_t ON pay_t.race_id = e.race_id AND pay_t.bet_type = '単勝'
          AND pay_t.combination = CAST(e.horse_number AS TEXT)
        LEFT JOIN payouts pay_f ON pay_f.race_id = e.race_id AND pay_f.bet_type = '複勝'
          AND pay_f.combination = CAST(e.horse_number AS TEXT)
        WHERE (r.race_name LIKE '%(G1)%' OR r.race_name LIKE '%(G2)%' OR r.race_name LIKE '%(G3)%'
            OR r.race_name LIKE '%（G1）%' OR r.race_name LIKE '%（G2）%' OR r.race_name LIKE '%（G3）%')
          AND TRIM(r.course_type) = '芝'
          AND res.finish_position IS NOT NULL
    """).fetchall()

    for label, fn in [
        ("ダート→芝転換(全人気)", lambda r: r['prev_course'] and 'ダート' in r['prev_course']),
        ("ダート→芝転換×穴馬7-11人気", lambda r: r['prev_course'] and 'ダート' in r['prev_course'] and r['popularity'] and 7 <= r['popularity'] <= 11),
        ("ダート→芝転換×前走1-3着", lambda r: r['prev_course'] and 'ダート' in r['prev_course'] and r['prev_pos'] and r['prev_pos'] <= 3),
        ("芝→芝(参考・同コース継続)", lambda r: r['prev_course'] and '芝' in r['prev_course'] and r['popularity'] and 7 <= r['popularity'] <= 11),
    ]:
        sub = [r for r in rows_cs if fn(r)]
        roi_summary(sub, label)

    # ============================================================
    # 新シグナル候補4: 斤量変化 × 穴馬帯（ハンデ戦/別定戦で分離）
    # ============================================================
    print("\n" + "="*60)
    print("【新候補4】斤量変化 × 穴馬帯(7-11人気)")
    print("="*60)

    rows_wc = conn.execute("""
        SELECT e.popularity, e.weight_carried AS cur_wc, res.finish_position,
               r.race_name,
               hh.weight_carried AS prev_wc,
               pay_t.payout AS tansho, pay_f.payout AS fukusho
        FROM entries e
        JOIN races r ON r.race_id = e.race_id
        JOIN results res ON res.race_id = e.race_id AND res.horse_id = e.horse_id
        LEFT JOIN horse_histories hh ON hh.horse_id = e.horse_id
          AND hh.race_date = (
            SELECT MAX(h2.race_date) FROM horse_histories h2
            WHERE h2.horse_id = e.horse_id AND h2.race_date < r.date
          )
        LEFT JOIN payouts pay_t ON pay_t.race_id = e.race_id AND pay_t.bet_type = '単勝'
          AND pay_t.combination = CAST(e.horse_number AS TEXT)
        LEFT JOIN payouts pay_f ON pay_f.race_id = e.race_id AND pay_f.bet_type = '複勝'
          AND pay_f.combination = CAST(e.horse_number AS TEXT)
        WHERE (r.race_name LIKE '%(G1)%' OR r.race_name LIKE '%(G2)%' OR r.race_name LIKE '%(G3)%'
            OR r.race_name LIKE '%（G1）%' OR r.race_name LIKE '%（G2）%' OR r.race_name LIKE '%（G3）%')
          AND TRIM(r.course_type) = '芝'
          AND res.finish_position IS NOT NULL
          AND e.popularity BETWEEN 7 AND 11
          AND e.weight_carried IS NOT NULL
          AND hh.weight_carried IS NOT NULL
    """).fetchall()

    def wc_diff(r):
        try:
            return float(r['cur_wc']) - float(r['prev_wc'])
        except:
            return None

    def is_handicap(r):
        name = r['race_name'] or ''
        return 'ハンデ' in name or 'ハンディ' in name

    print("  ── 全レース ──")
    for label, lo, hi in [
        ("斤量増加(+1kg以上)", 1.0, 99),
        ("斤量増加(+2kg以上)", 2.0, 99),
        ("斤量変化なし(±0.5kg以内)", -0.5, 0.5),
        ("斤量減少(-1kg以下)", -99, -1.0),
    ]:
        sub = [r for r in rows_wc if wc_diff(r) is not None and lo <= wc_diff(r) <= hi]
        roi_summary(sub, label)

    print("\n  ── ハンデ戦のみ ──")
    rows_hc_only = [r for r in rows_wc if is_handicap(r)]
    rows_no_hc   = [r for r in rows_wc if not is_handicap(r)]
    print(f"  ハンデ戦n={len(rows_hc_only)}  別定戦n={len(rows_no_hc)}")
    for label, lo, hi in [
        ("ハンデ戦×斤量増加(+1kg以上)", 1.0, 99),
        ("ハンデ戦×斤量減少(-1kg以下)", -99, -1.0),
    ]:
        sub = [r for r in rows_hc_only if wc_diff(r) is not None and lo <= wc_diff(r) <= hi]
        roi_summary(sub, label)

    print("\n  ── 別定戦のみ（ハンデ戦除く）──")
    for label, lo, hi in [
        ("別定戦×斤量増加(+1kg以上)", 1.0, 99),
        ("別定戦×斤量増加(+2kg以上)", 2.0, 99),
        ("別定戦×斤量変化なし(±0.5kg)", -0.5, 0.5),
        ("別定戦×斤量減少(-1kg以下)", -99, -1.0),
    ]:
        sub = [r for r in rows_no_hc if wc_diff(r) is not None and lo <= wc_diff(r) <= hi]
        roi_summary(sub, label)

    # ============================================================
    # レビュー問題1: S3とS5の重複時のROI比較
    # 「前走4-6人気かつ前走1着」= S3もS5も満たす馬
    # → どちらの基準で評価すべきか
    # ============================================================
    print("\n" + "="*60)
    print("【レビュー問題1】S3 vs S5 重複馬のROI比較（7-9人気）")
    print("="*60)

    # S5単独（前走1着×7-9人気 かつ S3非該当: 前走人気が1-3人気 or 7人気以上）
    s5_only = [r for r in rows
               if r['popularity'] and 7 <= r['popularity'] <= 9
               and r['prev_pos'] and r['prev_pos'] == 1
               and not (r['prev_pop'] and 4 <= r['prev_pop'] <= 6)]
    roi_summary(s5_only, "S5のみ該当（前走1着×前走人気1-3or7以上）")

    # S3単独（前走4-6人気×前走1-3着 かつ 前走1着以外）
    s3_only = [r for r in rows
               if r['popularity'] and 7 <= r['popularity'] <= 9
               and r['prev_pop'] and 4 <= r['prev_pop'] <= 6
               and r['prev_pos'] and 2 <= r['prev_pos'] <= 3]
    roi_summary(s3_only, "S3のみ該当（前走4-6人気×前走2-3着）")

    # S3かつS5重複（前走4-6人気×前走1着×7-9人気）
    s3_and_s5 = [r for r in rows
                 if r['popularity'] and 7 <= r['popularity'] <= 9
                 and r['prev_pop'] and 4 <= r['prev_pop'] <= 6
                 and r['prev_pos'] and r['prev_pos'] == 1]
    roi_summary(s3_and_s5, "S3+S5重複（前走4-6人気×前走1着）← 問題の核心")

    # S3全体（前走4-6人気×前走1-3着、重複含む）
    s3_all = [r for r in rows
              if r['popularity'] and 7 <= r['popularity'] <= 9
              and r['prev_pop'] and 4 <= r['prev_pop'] <= 6
              and r['prev_pos'] and 1 <= r['prev_pos'] <= 3]
    roi_summary(s3_all, "S3全体（前走1着含む・参考）")

    # S5全体（前走1着×7-9人気、重複含む）
    s5_all = [r for r in rows
              if r['popularity'] and 7 <= r['popularity'] <= 9
              and r['prev_pos'] and r['prev_pos'] == 1]
    roi_summary(s5_all, "S5全体（前走4-6人気含む・参考）")

    # ============================================================
    # レビュー問題2: S1+S8重複馬のROI
    # 前走1-3人気かつ前走後方かつ前走7着以下 → 今回9-11人気
    # ============================================================
    print("\n" + "="*60)
    print("【レビュー問題2】S1+S8重複馬のROI（9-11人気）")
    print("="*60)

    # S1のみ（後方大敗ではない）
    s1_only = [r for r in rows
               if r['popularity'] and 9 <= r['popularity'] <= 11
               and r['prev_pop'] and 1 <= r['prev_pop'] <= 3
               and not (r['prev_pos'] and r['prev_pos'] >= 7
                        and pace_style(r['prev_corner'], r['prev_headcount']) == "後方")]
    roi_summary(s1_only, "S1のみ（後方大敗除く）")

    # S1+S8重複（前走1-3人気×後方大敗×7着以下×今回9-11人気）
    s1_and_s8 = [r for r in rows
                 if r['popularity'] and 9 <= r['popularity'] <= 11
                 and r['prev_pop'] and 1 <= r['prev_pop'] <= 3
                 and r['prev_pos'] and r['prev_pos'] >= 7
                 and pace_style(r['prev_corner'], r['prev_headcount']) == "後方"]
    roi_summary(s1_and_s8, "S1+S8重複（前走1-3人気×後方7着以下）← 問題の核心")

    # S8のみ（前走1-3人気ではない）
    s8_only = [r for r in rows
               if r['popularity'] and 7 <= r['popularity'] <= 11
               and r['prev_pos'] and r['prev_pos'] >= 7
               and pace_style(r['prev_corner'], r['prev_headcount']) == "後方"
               and not (r['prev_pop'] and 1 <= r['prev_pop'] <= 3)]
    roi_summary(s8_only, "S8のみ（前走1-3人気を除く）")

    # S1全体（参考）
    s1_all = [r for r in rows
              if r['popularity'] and 9 <= r['popularity'] <= 11
              and r['prev_pop'] and 1 <= r['prev_pop'] <= 3]
    roi_summary(s1_all, "S1全体（参考）")

    # ============================================================
    # 新検証: 14人気以上の三連複ヒモ候補
    # S1型（前走1-3人気→今回14人気以上）の複勝ROIを確認
    # ============================================================
    print("\n" + "="*60)
    print("【新検証】14人気以上の三連複ヒモ候補（複勝ROI重視）")
    print("="*60)

    # S1型の人気帯拡張（14人気以上）
    for pop_lo, pop_hi, label in [
        (9,  11, "S1現行 (9-11人気)×前走1-3人気"),
        (12, 13, "S2空白帯 (12-13人気)×前走1-3人気"),
        (14, 16, "拡張候補 (14-16人気)×前走1-3人気"),
        (17, 99, "超大穴 (17人気以上)×前走1-3人気"),
        (14, 99, "14人気以上×前走1-3人気（合計）"),
    ]:
        sub = [r for r in rows
               if r['popularity'] and pop_lo <= r['popularity'] <= pop_hi
               and r['prev_pop'] and 1 <= r['prev_pop'] <= 3]
        roi_summary(sub, label)

    print()
    # S2型の人気帯拡張（14人気以上）
    for pop_lo, pop_hi, label in [
        (9,  13, "S2現行 (9-13人気)×前走4-6人気×前走7着以下"),
        (14, 99, "S2拡張 (14人気以上)×前走4-6人気×前走7着以下"),
    ]:
        sub = [r for r in rows
               if r['popularity'] and pop_lo <= r['popularity'] <= pop_hi
               and r['prev_pop'] and 4 <= r['prev_pop'] <= 6
               and r['prev_pos'] and r['prev_pos'] >= 7]
        roi_summary(sub, label)

    print()
    # 14人気以上の全体ROIベースライン
    for pop_lo, pop_hi, label in [
        (14, 99, "14人気以上 全体ベースライン"),
        (14, 99, "14人気以上 前走1-6人気（合算）"),
    ]:
        if "前走" in label:
            sub = [r for r in rows
                   if r['popularity'] and r['popularity'] >= 14
                   and r['prev_pop'] and 1 <= r['prev_pop'] <= 6]
        else:
            sub = [r for r in rows if r['popularity'] and r['popularity'] >= 14]
        roi_summary(sub, label)

    # ============================================================
    # オッズ閾値検証: 人気帯条件をオッズ帯に置き換える可能性
    # ============================================================
    print("\n" + "="*60)
    print("[odds-1] jitsuryoku jouken nomi x odds tai betsu ROI")
    print("="*60)

    rows_odds = conn.execute("""
        SELECT
            e.odds AS cur_odds,
            e.popularity,
            res.finish_position,
            hh.popularity       AS prev_pop,
            hh.finish_position  AS prev_pos,
            pay_t.payout  AS tansho,
            pay_f.payout  AS fukusho
        FROM entries e
        JOIN races r   ON r.race_id = e.race_id
        JOIN results res ON res.race_id = e.race_id AND res.horse_id = e.horse_id
        LEFT JOIN horse_histories hh ON hh.horse_id = e.horse_id
          AND hh.race_date = (
            SELECT MAX(h2.race_date) FROM horse_histories h2
            WHERE h2.horse_id = e.horse_id AND h2.race_date < r.date
          )
        LEFT JOIN payouts pay_t ON pay_t.race_id = e.race_id AND pay_t.bet_type = '単勝'
          AND pay_t.combination = CAST(e.horse_number AS TEXT)
        LEFT JOIN payouts pay_f ON pay_f.race_id = e.race_id AND pay_f.bet_type = '複勝'
          AND pay_f.combination = CAST(e.horse_number AS TEXT)
        WHERE (r.race_name LIKE '%(G1)%' OR r.race_name LIKE '%(G2)%' OR r.race_name LIKE '%(G3)%'
            OR r.race_name LIKE '%（G1）%' OR r.race_name LIKE '%（G2）%' OR r.race_name LIKE '%（G3）%')
          AND TRIM(r.course_type) = '芝'
          AND res.finish_position IS NOT NULL
          AND e.odds IS NOT NULL
    """).fetchall()

    odds_bands = [
        ("3〜5倍",   3.0,  5.0),
        ("5〜10倍",  5.0, 10.0),
        ("10〜20倍",10.0, 20.0),
        ("20〜50倍",20.0, 50.0),
        ("50倍以上", 50.0, 9999),
    ]

    # 実力条件の定義（今回人気問わず）
    def match_s1_equiv(r):   # 前走1-3人気
        return r['prev_pop'] and 1 <= r['prev_pop'] <= 3

    def match_s2_equiv(r):   # 前走4-6人気 × 前走7着以下
        return r['prev_pop'] and 4 <= r['prev_pop'] <= 6 and r['prev_pos'] and r['prev_pos'] >= 7

    def match_s3_equiv(r):   # 前走4-6人気 × 前走1着
        return r['prev_pop'] and 4 <= r['prev_pop'] <= 6 and r['prev_pos'] and r['prev_pos'] == 1

    def match_s5_equiv(r):   # 前走1着
        return r['prev_pos'] and r['prev_pos'] == 1

    signals_def = [
        ("S1相当(前走1-3人気)", match_s1_equiv),
        ("S2相当(前走4-6人気×前走7着以下)", match_s2_equiv),
        ("S3相当(前走4-6人気×前走1着)", match_s3_equiv),
        ("S5相当(前走1着)", match_s5_equiv),
    ]

    for sig_label, sig_fn in signals_def:
        print(f"\n  ── {sig_label} ──")
        sig_rows = [r for r in rows_odds if sig_fn(r)]
        roi_summary(sig_rows, "  全オッズ（今回人気問わず）")
        for band_label, lo, hi in odds_bands:
            sub = [r for r in sig_rows if r['cur_odds'] and lo <= r['cur_odds'] < hi]
            roi_summary(sub, f"  {band_label}")

    # ============================================================
    # オッズ検証②: 現行人気帯のオッズ分布確認
    # ============================================================
    print("\n" + "="*60)
    print("[odds-2] genkou ninki tai ni taishou suru odds bunpu")
    print("="*60)

    import statistics
    for pop_lo, pop_hi, label in [
        (7, 9,  "7-9人気（S3/S4/S5対象帯）"),
        (9, 11, "9-11人気（S1対象帯）"),
        (9, 13, "9-13人気（S2対象帯）"),
        (7, 11, "7-11人気（S6/S7/S8/S9対象帯）"),
    ]:
        sub_odds = [r['cur_odds'] for r in rows_odds
                    if r['popularity'] and pop_lo <= r['popularity'] <= pop_hi
                    and r['cur_odds']]
        if not sub_odds:
            print(f"  {label}: n=0")
            continue
        sub_odds.sort()
        n = len(sub_odds)
        p10 = sub_odds[int(n*0.10)]
        p25 = sub_odds[int(n*0.25)]
        p50 = sub_odds[int(n*0.50)]
        p75 = sub_odds[int(n*0.75)]
        p90 = sub_odds[int(n*0.90)]
        print(f"  {label}: n={n}  "
              f"10%={p10:.1f}倍  25%={p25:.1f}倍  中央={p50:.1f}倍  "
              f"75%={p75:.1f}倍  90%={p90:.1f}倍")

    # ============================================================
    # オッズ検証③: 「実力条件のみ」vs「現行人気帯あり」vs「オッズ閾値あり」比較
    # ============================================================
    print("\n" + "="*60)
    print("[odds-3] 3 pattern hikaku (S1/S3/S5)")
    print("="*60)

    for sig_label, sig_fn, cur_pop_lo, cur_pop_hi in [
        ("S1", match_s1_equiv, 9, 11),
        ("S3", match_s3_equiv, 7, 9),
        ("S5", match_s5_equiv, 7, 9),
    ]:
        print(f"\n  ── {sig_label} ──")
        base = [r for r in rows_odds if sig_fn(r)]
        # パターンA: 実力条件のみ（人気・オッズ問わず）
        roi_summary(base, f"A) 実力条件のみ（人気問わず）")
        # パターンB: 現行（人気帯条件あり）
        b = [r for r in base if r['popularity'] and cur_pop_lo <= r['popularity'] <= cur_pop_hi]
        roi_summary(b, f"B) 現行人気帯 ({cur_pop_lo}-{cur_pop_hi}人気)")
        # パターンC: オッズ閾値 10倍以上
        c10 = [r for r in base if r['cur_odds'] and r['cur_odds'] >= 10.0]
        roi_summary(c10, f"C) オッズ10倍以上")
        # パターンD: オッズ閾値 15倍以上
        c15 = [r for r in base if r['cur_odds'] and r['cur_odds'] >= 15.0]
        roi_summary(c15, f"D) オッズ15倍以上")
        # パターンE: オッズ閾値 20倍以上
        c20 = [r for r in base if r['cur_odds'] and r['cur_odds'] >= 20.0]
        roi_summary(c20, f"E) オッズ20倍以上")

    # ============================================================
    # 確認②: S9の定量戦フィルタ（斤量増加の内訳検証）
    # ============================================================
    print("\n" + "="*60)
    print("[S9確認] 斤量増加パターン別ROI（定量移行 vs ハンデ→別定）")
    print("="*60)

    rows_s9 = conn.execute("""
        SELECT
            e.popularity    AS pop,
            e.weight_carried AS cur_wc,
            hh.weight_carried AS prev_wc,
            hh.race_class   AS prev_race_class,
            r.race_class    AS cur_race_class,
            res.finish_position,
            pay_t.payout    AS tansho,
            pay_f.payout    AS fukusho
        FROM entries e
        JOIN races r ON r.race_id = e.race_id
        JOIN results res ON res.race_id = e.race_id AND res.horse_id = e.horse_id
        LEFT JOIN horse_histories hh ON hh.horse_id = e.horse_id
          AND hh.race_date = (
            SELECT MAX(h2.race_date) FROM horse_histories h2
            WHERE h2.horse_id = e.horse_id AND h2.race_date < r.date
          )
        LEFT JOIN payouts pay_t ON pay_t.race_id=e.race_id AND pay_t.bet_type='単勝'
            AND pay_t.combination = CAST(e.horse_number AS TEXT)
        LEFT JOIN payouts pay_f ON pay_f.race_id=e.race_id AND pay_f.bet_type='複勝'
            AND pay_f.combination = CAST(e.horse_number AS TEXT)
        WHERE (r.race_name LIKE '%(G1)%' OR r.race_name LIKE '%(G2)%'
            OR r.race_name LIKE '%(G3)%'
            OR r.race_name LIKE '%（G1）%'
            OR r.race_name LIKE '%（G2）%'
            OR r.race_name LIKE '%（G3）%')
          AND TRIM(r.course_type) = '芝'
          AND res.finish_position IS NOT NULL
          AND e.weight_carried IS NOT NULL
          AND hh.weight_carried IS NOT NULL
          AND 7 <= e.popularity AND e.popularity <= 11
    """).fetchall()

    s9_all = [r for r in rows_s9
              if r['cur_wc'] and r['prev_wc']
              and (float(r['cur_wc']) - float(r['prev_wc'])) >= 1.0]

    s9_from_handicap = [r for r in s9_all
                        if r['prev_race_class'] and 'ハンデ' in str(r['prev_race_class'])]
    s9_fixed_to_fixed = [r for r in s9_all
                         if r['prev_race_class'] and 'ハンデ' not in str(r['prev_race_class'])]

    print(f"  S9全体（斤量+1以上 × 7-11人気）:")
    roi_summary(s9_all, "  S9全体")
    print(f"\n  グループA（前走ハンデ戦 → 今回）:")
    roi_summary(s9_from_handicap, "  A: 前走ハンデ")
    print(f"\n  グループB（前走非ハンデ → 今回）:")
    roi_summary(s9_fixed_to_fixed, "  B: 前走非ハンデ")

    # ============================================================
    # 4〜6人気帯 ROI検証（空白地帯の把握）
    # ============================================================
    print("\n" + "="*60)
    print("[4-6人気帯検証] 前走条件別ROI（市場評価が高い穴馬ゾーン）")
    print("="*60)

    mid_rows = [r for r in rows if r['popularity'] and 4 <= r['popularity'] <= 6]
    roi_summary(mid_rows, "4-6人気 全体")

    print()
    # 前走着順別
    for label, fn in [
        ("前走1着", lambda r: r['prev_pos'] == 1),
        ("前走2-3着", lambda r: r['prev_pos'] and 2 <= r['prev_pos'] <= 3),
        ("前走4-6着", lambda r: r['prev_pos'] and 4 <= r['prev_pos'] <= 6),
        ("前走7着以下", lambda r: r['prev_pos'] and r['prev_pos'] >= 7),
    ]:
        roi_summary([r for r in mid_rows if fn(r)], label)

    print()
    # 前走人気×前走着順（S3/S5相当パターン）
    roi_summary([r for r in mid_rows if r['prev_pop'] and 1 <= r['prev_pop'] <= 3 and r['prev_pos'] == 1],
                "前走1-3人気×前走1着（S1相当）")
    roi_summary([r for r in mid_rows if r['prev_pop'] and 4 <= r['prev_pop'] <= 6 and r['prev_pos'] == 1],
                "前走4-6人気×前走1着（S3+S5相当）")
    roi_summary([r for r in mid_rows if r['prev_pop'] and 1 <= r['prev_pop'] <= 3],
                "前走1-3人気（S1相当・着順問わず）")

    print()
    # オッズ帯別（market_value確認）
    print("  オッズ帯別:")
    for label, lo, hi in [
        ("3-5倍", 3.0, 5.0),
        ("5-8倍", 5.0, 8.0),
        ("8-15倍", 8.0, 15.0),
    ]:
        roi_summary([r for r in mid_rows if r['cur_odds'] and lo <= r['cur_odds'] < hi], f"  {label}")

    conn.close()
    print("\n検証完了。このテキストをクロードに貼り付けてください。")


if __name__ == "__main__":
    main()
