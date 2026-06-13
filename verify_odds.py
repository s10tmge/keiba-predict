"""
verify_odds.py - Odds threshold verification
Run: python verify_odds.py > verify_odds_result.txt
"""
import sqlite3

DB_PATH = "keiba.db"

def get_conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def roi(rows, label):
    n = len(rows)
    if not n:
        print(f"  {label}: n=0")
        return
    t_hits = [r['tansho'] for r in rows if r['finish_position'] == 1 and r['tansho']]
    f_hits = [r['fukusho'] for r in rows
              if r['finish_position'] and r['finish_position'] <= 3 and r['fukusho']]
    t_roi = sum(t_hits) / n
    f_roi = sum(f_hits) / n
    t_pct = len(t_hits) / n * 100
    f_pct = len(f_hits) / n * 100
    print(f"  {label}: n={n}  tan={t_roi:.0f}yen({t_pct:.1f}%)  fuku={f_roi:.0f}yen({f_pct:.1f}%)")

def main():
    db = get_conn()

    rows = db.execute("""
        SELECT
            e.odds          AS cur_odds,
            e.popularity    AS cur_pop,
            res.finish_position,
            hh.popularity   AS prev_pop,
            hh.finish_position AS prev_pos,
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
        LEFT JOIN payouts pay_t
            ON pay_t.race_id = e.race_id
           AND pay_t.bet_type = '単勝'
           AND pay_t.combination = CAST(e.horse_number AS TEXT)
        LEFT JOIN payouts pay_f
            ON pay_f.race_id = e.race_id
           AND pay_f.bet_type = '複勝'
           AND pay_f.combination = CAST(e.horse_number AS TEXT)
        WHERE (r.race_name LIKE '%(G1)%' OR r.race_name LIKE '%(G2)%'
            OR r.race_name LIKE '%(G3)%'
            OR r.race_name LIKE '%（G1）%'
            OR r.race_name LIKE '%（G2）%'
            OR r.race_name LIKE '%（G3）%')
          AND TRIM(r.course_type) = '芝'
          AND res.finish_position IS NOT NULL
          AND e.odds IS NOT NULL
    """).fetchall()

    print(f"Total records: {len(rows)}")
    if not rows:
        print("No data. Check DB.")
        db.close()
        return
    print()

    odds_bands = [
        ("3-5x",   3.0,  5.0),
        ("5-10x",  5.0, 10.0),
        ("10-20x", 10.0, 20.0),
        ("20-50x", 20.0, 50.0),
        ("50x+",   50.0, 9999),
    ]

    def s1(r): return r['prev_pop'] and 1 <= r['prev_pop'] <= 3
    def s2(r): return (r['prev_pop'] and 4 <= r['prev_pop'] <= 6
                       and r['prev_pos'] and r['prev_pos'] >= 7)
    def s3(r): return (r['prev_pop'] and 4 <= r['prev_pop'] <= 6
                       and r['prev_pos'] and r['prev_pos'] == 1)
    def s5(r): return r['prev_pos'] and r['prev_pos'] == 1

    # ---- [1] ability filter only x odds band ----
    print("=" * 60)
    print("[1] Ability filter only x odds band ROI")
    print("=" * 60)
    for sig_name, sig_fn in [
        ("S1 prev1-3pop", s1),
        ("S2 prev4-6pop+7th+", s2),
        ("S3 prev4-6pop+1st", s3),
        ("S5 prev1st", s5),
    ]:
        base = [r for r in rows if sig_fn(r)]
        print(f"\n  -- {sig_name} --")
        roi(base, "all odds")
        for bl, lo, hi in odds_bands:
            sub = [r for r in base if r['cur_odds'] and lo <= r['cur_odds'] < hi]
            roi(sub, bl)

    # ---- [2] odds distribution per popularity band ----
    print()
    print("=" * 60)
    print("[2] Odds distribution per popularity band")
    print("=" * 60)
    for pop_lo, pop_hi, label in [
        (7, 9,  "pop7-9  (S3/S4/S5)"),
        (9, 11, "pop9-11 (S1)"),
        (9, 13, "pop9-13 (S2)"),
        (7, 11, "pop7-11 (S6-S9)"),
    ]:
        od = sorted([r['cur_odds'] for r in rows
                     if r['cur_pop'] and pop_lo <= r['cur_pop'] <= pop_hi
                     and r['cur_odds']])
        if not od:
            print(f"  {label}: n=0")
            continue
        n = len(od)
        def p(q): return od[int(n * q)]
        print(f"  {label}: n={n}  p10={p(.1):.1f}x  p25={p(.25):.1f}x  "
              f"med={p(.5):.1f}x  p75={p(.75):.1f}x  p90={p(.9):.1f}x")

    # ---- [3] 3-way comparison ----
    print()
    print("=" * 60)
    print("[3] 3-way: ability-only / pop-band / odds-threshold")
    print("=" * 60)
    for sig_name, sig_fn, pop_lo, pop_hi in [
        ("S1", s1, 9, 11),
        ("S3", s3, 7, 9),
        ("S5", s5, 7, 9),
    ]:
        base = [r for r in rows if sig_fn(r)]
        print(f"\n  -- {sig_name} --")
        roi(base, "A) ability only")
        roi([r for r in base if r['cur_pop'] and pop_lo <= r['cur_pop'] <= pop_hi],
            f"B) pop{pop_lo}-{pop_hi}")
        roi([r for r in base if r['cur_odds'] and r['cur_odds'] >= 10.0], "C) odds>=10x")
        roi([r for r in base if r['cur_odds'] and r['cur_odds'] >= 15.0], "D) odds>=15x")
        roi([r for r in base if r['cur_odds'] and r['cur_odds'] >= 20.0], "E) odds>=20x")

    db.close()
    print("\nDone. Paste this output to Claude.")

if __name__ == "__main__":
    main()
