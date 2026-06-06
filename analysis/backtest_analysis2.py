"""
Corrected backtest analysis.
ROI = sum(tansho_payout where present, else 0) / count(all in group)
Payout values are already in yen per 100yen bet.
"""
import csv

DATA_PATH = '/root/.claude/uploads/399386ab-90ee-5e54-b833-76894dff6fa4/6110de4a-analysis_data.csv'
JOCKEY_PATH = '/root/.claude/uploads/399386ab-90ee-5e54-b833-76894dff6fa4/4d7d3f12-jockey_stats.csv'
RACE_3F_PATH = '/root/.claude/uploads/399386ab-90ee-5e54-b833-76894dff6fa4/6c8b64fc-race_3f_stats.csv'


def load_csv(path):
    rows = []
    with open(path, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def f(v):
    try: return float(v)
    except: return None

def i(v):
    try: return int(v)
    except: return None

def roi(rows, field='tansho_payout'):
    if not rows: return 0.0
    total = sum(f(r.get(field) or '0') or 0 for r in rows)
    return total / len(rows)

def show(label, rows_subset, base_rows=None):
    if base_rows is None:
        base_rows = rows_subset
    n = len(rows_subset)
    tan = roi(rows_subset, 'tansho_payout')
    fuku = roi(rows_subset, 'fukusho_payout')
    flag = '✓' if tan >= 105 and n >= 30 else ('△' if tan >= 100 and n >= 30 else ' ')
    print(f"  {flag} {label:<55} n={n:5d}  単={tan:6.1f}  複={fuku:6.1f}")


print("Loading data...")
rows = load_csv(DATA_PATH)
jockey_rows = load_csv(JOCKEY_PATH)
race_3f_rows = load_csv(RACE_3F_PATH)

# Build lookup tables
race_3f = {r['race_id']: f(r.get('avg_3f')) for r in race_3f_rows if f(r.get('avg_3f'))}

jockey_stats = {}
for r in jockey_rows:
    total = i(r['total']) or 0
    wins = i(r['wins']) or 0
    if total >= 20:
        jockey_stats[(r['jockey_name'], r['course_type'])] = wins / total

# Augment rows
for r in rows:
    r['_pop'] = i(r.get('popularity'))
    r['_odds'] = f(r.get('odds'))
    r['_prev_pop'] = i(r.get('prev_pop'))
    r['_prev_pos'] = i(r.get('prev_pos'))
    r['_prev2_pos'] = None  # not in CSV
    r['_finish'] = i(r.get('finish_position'))
    r['_headcount'] = i(r.get('headcount'))
    r['_prev_hc'] = i(r.get('prev_hc'))
    r['_weight_diff'] = f(r.get('horse_weight_diff'))
    r['_course'] = r.get('course_type', '')
    r['_prev_course'] = r.get('prev_course', '')
    r['_distance'] = i(r.get('distance'))
    r['_prev_dist'] = i(r.get('prev_dist'))
    r['_venue'] = r.get('venue', '')
    r['_jockey_wr'] = jockey_stats.get((r.get('jockey_name', ''), r['_course']))

    # 3F deviation: race_avg_3f - horse_last_3f (positive = horse was faster than avg)
    # last_3f is current race's horse 3F time, we use race_3f as the baseline
    # For B1 we need prev race's horse last_3f vs that race's avg
    # We don't have prev race's avg, but we have current race's avg and current horse's last_3f
    # Actually for prediction we compare prev_last3f against current race avg? No that doesn't make sense.
    # We compare prev race's horse time vs prev race's average.
    # We have race_3f[race_id] = current race avg, but we need PREV race's avg.
    # The horse's prev_last3f is not in CSV. last_3f = this race's 3F for this horse.
    # For signal B1, it should be: prev race avg - horse's prev_last3f
    # We don't have horse's prev_last3f directly.
    # BUT: we can compute it differently: compare this horse's last_3f to this race's avg
    # That would be current-race performance vs avg, which is also a useful signal.
    avg3f = race_3f.get(r.get('race_id', ''))
    last3f = f(r.get('last_3f'))
    if avg3f and last3f:
        r['_3f_diff'] = avg3f - last3f  # positive = horse was faster than avg
    else:
        r['_3f_diff'] = None

longshots = [r for r in rows if r['_pop'] and r['_pop'] >= 6]
print(f"Total: {len(rows)}, Longshots (pop>=6): {len(longshots)}\n")
print(f"Baseline - all horses: ROI単={roi(rows):.1f}  ROI複={roi(rows,'fukusho_payout'):.1f}")
print(f"Baseline - longshots:  ROI単={roi(longshots):.1f}  ROI複={roi(longshots,'fukusho_payout'):.1f}\n")

# ========================
# AXIS B1: 3F analysis
# Note: _3f_diff here is THIS race's (avg - horse_3f),
# i.e., how the horse performed in the race they JUST RAN.
# This is a post-hoc signal but let's see the distribution.
# ========================
print("="*70)
print("B1: 3F deviation (this race: avg_3f - horse_last_3f)")
print("Note: This is the horse's performance in the CURRENT race - used to")
print("understand if 3F speed is predictive. For actual prediction we need")
print("prev race data which is not directly available as prev_last3f column.")
print("="*70)
b1_rows = [r for r in longshots if r['_3f_diff'] is not None]
print(f"Rows with 3F data: {len(b1_rows)} / {len(longshots)}")
for label, fn in [
    ("3f_diff >= 2.0 (much faster than avg)", lambda r: r['_3f_diff'] >= 2.0),
    ("3f_diff 1.0-2.0", lambda r: 1.0 <= r['_3f_diff'] < 2.0),
    ("3f_diff 0.5-1.0", lambda r: 0.5 <= r['_3f_diff'] < 1.0),
    ("3f_diff 0.0-0.5", lambda r: 0.0 <= r['_3f_diff'] < 0.5),
    ("3f_diff -0.5 to 0", lambda r: -0.5 <= r['_3f_diff'] < 0.0),
    ("3f_diff -1.0 to -0.5", lambda r: -1.0 <= r['_3f_diff'] < -0.5),
    ("3f_diff <= -1.0 (much slower)", lambda r: r['_3f_diff'] <= -1.0),
]:
    show(label, [r for r in b1_rows if fn(r)])

print()
print("NOTE: prev_last3f and prev2_pos columns are NOT in the CSV.")
print("B1 and B2 signals cannot be backtested directly with this dataset.")
print("They require prev-race 3F times and 2-race-back finish positions.")
print()

# ========================
# AXIS C: Jockey win rate
# ========================
print("="*70)
print("AXIS C: Jockey x course win rate thresholds (longshots pop>=6)")
print("="*70)
c_rows = [r for r in longshots if r['_jockey_wr'] is not None]
no_data = [r for r in longshots if r['_jockey_wr'] is None]
print(f"With jockey data: {len(c_rows)}, without: {len(no_data)}")
show("no jockey data", no_data)
for label, fn in [
    ("win_rate >= 0.30", lambda r: r['_jockey_wr'] >= 0.30),
    ("win_rate 0.25-0.30", lambda r: 0.25 <= r['_jockey_wr'] < 0.30),
    ("win_rate 0.20-0.25", lambda r: 0.20 <= r['_jockey_wr'] < 0.25),
    ("win_rate 0.15-0.20", lambda r: 0.15 <= r['_jockey_wr'] < 0.20),
    ("win_rate 0.10-0.15", lambda r: 0.10 <= r['_jockey_wr'] < 0.15),
    ("win_rate 0.05-0.10", lambda r: 0.05 <= r['_jockey_wr'] < 0.10),
    ("win_rate 0.03-0.05", lambda r: 0.03 <= r['_jockey_wr'] < 0.05),
    ("win_rate < 0.03", lambda r: r['_jockey_wr'] < 0.03),
]:
    show(label, [r for r in c_rows if fn(r)])

# ========================
# AXIS A: Validate existing signals
# ========================
print()
print("="*70)
print("AXIS A: Signal validation")
print("="*70)
# N1
n1 = [r for r in rows if r['_pop'] and 9 <= r['_pop'] <= 11 and r['_prev_pop'] and 1 <= r['_prev_pop'] <= 3]
show("N1: pop 9-11, prev_pop 1-3", n1, rows)

# N2
n2 = [r for r in rows if r['_pop'] and 9 <= r['_pop'] <= 11 and r['_prev_pop'] and 4 <= r['_prev_pop'] <= 6]
show("N2: pop 9-11, prev_pop 4-6", n2, rows)

# N3
n3 = [r for r in longshots if r['_prev_pos'] and 4 <= r['_prev_pos'] <= 6 and r['_course'] == r['_prev_course']]
show("N3: pop>=6, prev_pos 4-6, same course", n3, longshots)

# N4
n4 = [r for r in longshots if r['_weight_diff'] is not None and r['_weight_diff'] <= -6]
show("N4: pop>=6, weight_diff <= -6", n4, longshots)

# N5
n5 = [r for r in rows if r['_pop'] and 6 <= r['_pop'] <= 8 and r['_prev_pop'] and 7 <= r['_prev_pop'] <= 10]
show("N5: pop 6-8, prev_pop 7-10", n5, rows)

# N6
n6 = [r for r in longshots if r['_course'] == 'ダート' and r['_headcount'] and 0 < r['_headcount'] <= 10]
show("N6: pop>=6, ダート, headcount<=10", n6, longshots)

# N7
n7 = [r for r in longshots if r['_prev_pos'] and 4 <= r['_prev_pos'] <= 6
      and r['_prev_hc'] and r['_prev_hc'] > 0 and r['_headcount'] and r['_headcount'] <= r['_prev_hc'] - 2]
show("N7: pop>=6, prev_pos 4-6, headcount reduced 2+", n7, longshots)

# ========================
# TASK 4: New signal discovery
# ========================
print()
print("="*70)
print("TASK 4: NEW SIGNAL DISCOVERY")
print("="*70)

print("\n--- Distance change ---")
for label, fn in [
    ("dist increase >= 400", lambda r: r['_distance'] and r['_prev_dist'] and r['_distance'] - r['_prev_dist'] >= 400),
    ("dist increase 200-400", lambda r: r['_distance'] and r['_prev_dist'] and 200 <= r['_distance'] - r['_prev_dist'] < 400),
    ("dist increase 1-200", lambda r: r['_distance'] and r['_prev_dist'] and 1 <= r['_distance'] - r['_prev_dist'] < 200),
    ("same distance", lambda r: r['_distance'] and r['_prev_dist'] and r['_distance'] == r['_prev_dist']),
    ("dist decrease -1 to -200", lambda r: r['_distance'] and r['_prev_dist'] and -200 <= r['_distance'] - r['_prev_dist'] < 0),
    ("dist decrease -200 to -400", lambda r: r['_distance'] and r['_prev_dist'] and -400 <= r['_distance'] - r['_prev_dist'] < -200),
    ("dist decrease <= -400", lambda r: r['_distance'] and r['_prev_dist'] and r['_distance'] - r['_prev_dist'] <= -400),
]:
    show(label, [r for r in longshots if fn(r)])

print("\n--- Course switch ---")
for label, fn in [
    ("芝→ダート switch", lambda r: r['_course'] == 'ダート' and r['_prev_course'] == '芝'),
    ("ダート→芝 switch", lambda r: r['_course'] == '芝' and r['_prev_course'] == 'ダート'),
    ("same course 芝", lambda r: r['_course'] == '芝' and r['_prev_course'] == '芝'),
    ("same course ダート", lambda r: r['_course'] == 'ダート' and r['_prev_course'] == 'ダート'),
]:
    show(label, [r for r in longshots if fn(r)])

print("\n--- Headcount ranges ---")
for label, fn in [
    ("headcount <= 8", lambda r: r['_headcount'] and r['_headcount'] <= 8),
    ("headcount 9-10", lambda r: r['_headcount'] and 9 <= r['_headcount'] <= 10),
    ("headcount 11-12", lambda r: r['_headcount'] and 11 <= r['_headcount'] <= 12),
    ("headcount 13-14", lambda r: r['_headcount'] and 13 <= r['_headcount'] <= 14),
    ("headcount 15-16", lambda r: r['_headcount'] and 15 <= r['_headcount'] <= 16),
    ("headcount >= 17", lambda r: r['_headcount'] and r['_headcount'] >= 17),
]:
    show(label, [r for r in longshots if fn(r)])

print("\n--- Weight diff granular ---")
for label, fn in [
    ("weight_diff <= -10", lambda r: r['_weight_diff'] is not None and r['_weight_diff'] <= -10),
    ("weight_diff -8 to -10", lambda r: r['_weight_diff'] is not None and -10 < r['_weight_diff'] <= -8),
    ("weight_diff -6 to -8", lambda r: r['_weight_diff'] is not None and -8 < r['_weight_diff'] <= -6),
    ("weight_diff -4 to -6", lambda r: r['_weight_diff'] is not None and -4 < r['_weight_diff'] <= -6),
    ("weight_diff -2 to -4", lambda r: r['_weight_diff'] is not None and -4 < r['_weight_diff'] <= -2),
    ("weight_diff -2 to +2 (stable)", lambda r: r['_weight_diff'] is not None and -2 < r['_weight_diff'] <= 2),
    ("weight_diff >= 6 (heavy gain)", lambda r: r['_weight_diff'] is not None and r['_weight_diff'] >= 6),
    ("weight_diff >= 10", lambda r: r['_weight_diff'] is not None and r['_weight_diff'] >= 10),
]:
    show(label, [r for r in longshots if fn(r)])

print("\n--- Popularity exact ranges (pop 6-18) ---")
for p in range(6, 19):
    show(f"pop = {p}", [r for r in rows if r['_pop'] == p])

print("\n--- prev_pos exact for longshots ---")
for p in range(1, 12):
    show(f"prev_pos = {p}", [r for r in longshots if r['_prev_pos'] == p])

print("\n--- pop 9-11 (N1/N2 zone) vs each prev_pop ---")
pop911 = [r for r in rows if r['_pop'] and 9 <= r['_pop'] <= 11]
print(f"  pop 9-11 total: {len(pop911)}")
for pp in range(1, 12):
    show(f"pop 9-11, prev_pop={pp}", [r for r in pop911 if r['_prev_pop'] == pp])

print("\n--- pop 12+ vs prev_pop (new signal candidate) ---")
pop12 = [r for r in rows if r['_pop'] and r['_pop'] >= 12]
print(f"  pop 12+ total: {len(pop12)}")
for label, fn in [
    ("pop>=12, prev_pop 1", lambda r: r['_prev_pop'] == 1),
    ("pop>=12, prev_pop 1-2", lambda r: r['_prev_pop'] and 1 <= r['_prev_pop'] <= 2),
    ("pop>=12, prev_pop 1-3", lambda r: r['_prev_pop'] and 1 <= r['_prev_pop'] <= 3),
    ("pop>=12, prev_pop 4-6", lambda r: r['_prev_pop'] and 4 <= r['_prev_pop'] <= 6),
]:
    show(label, [r for r in pop12 if fn(r)])

print("\n--- Venue analysis (longshots) ---")
venues = sorted(set(r['_venue'] for r in longshots if r['_venue']))
for v in venues:
    show(f"venue={v}", [r for r in longshots if r['_venue'] == v])

print("\n--- Venue × N1 ---")
n1_rows = [r for r in rows if r['_pop'] and 9 <= r['_pop'] <= 11 and r['_prev_pop'] and 1 <= r['_prev_pop'] <= 3]
for v in venues:
    sub = [r for r in n1_rows if r['_venue'] == v]
    if len(sub) >= 10:
        show(f"N1 × venue={v}", sub)

print("\n--- ダート distance × headcount ---")
for label, fn in [
    ("ダート <=1200 AND headcount<=12", lambda r: r['_course']=='ダート' and r['_distance'] and r['_distance']<=1200 and r['_headcount'] and r['_headcount']<=12),
    ("ダート <=1200 AND pop 9-11", lambda r: r['_course']=='ダート' and r['_distance'] and r['_distance']<=1200 and r['_pop'] and 9<=r['_pop']<=11),
    ("ダート >1800", lambda r: r['_course']=='ダート' and r['_distance'] and r['_distance']>1800),
    ("芝 <=1400", lambda r: r['_course']=='芝' and r['_distance'] and r['_distance']<=1400),
    ("芝 >2000", lambda r: r['_course']=='芝' and r['_distance'] and r['_distance']>2000),
]:
    show(label, [r for r in longshots if fn(r)])

print("\n--- 芝→ダート switch combinations ---")
switch = [r for r in longshots if r['_course'] == 'ダート' and r['_prev_course'] == '芝']
for label, fn in [
    ("芝→ダート, pop 9-11", lambda r: r['_pop'] and 9 <= r['_pop'] <= 11),
    ("芝→ダート, pop 6-8", lambda r: r['_pop'] and 6 <= r['_pop'] <= 8),
    ("芝→ダート, prev_pop 1-3", lambda r: r['_prev_pop'] and 1 <= r['_prev_pop'] <= 3),
    ("芝→ダート, prev_pop 1-6", lambda r: r['_prev_pop'] and 1 <= r['_prev_pop'] <= 6),
    ("芝→ダート, prev_pos 1-3", lambda r: r['_prev_pos'] and 1 <= r['_prev_pos'] <= 3),
]:
    sub = [r for r in switch if fn(r)]
    show(label, sub)

print("\n--- ダート→芝 switch combinations ---")
switch2 = [r for r in longshots if r['_course'] == '芝' and r['_prev_course'] == 'ダート']
for label, fn in [
    ("ダート→芝, pop 9-11", lambda r: r['_pop'] and 9 <= r['_pop'] <= 11),
    ("ダート→芝, prev_pop 1-3", lambda r: r['_prev_pop'] and 1 <= r['_prev_pop'] <= 3),
    ("ダート→芝, prev_pos 1-3", lambda r: r['_prev_pos'] and 1 <= r['_prev_pos'] <= 3),
]:
    sub = [r for r in switch2 if fn(r)]
    show(label, sub)

print("\n--- N1 sub-analysis by prev_pos ---")
for label, fn in [
    ("N1, prev_pos 1-3 (前走好走)", lambda r: r['_prev_pos'] and 1 <= r['_prev_pos'] <= 3),
    ("N1, prev_pos 4-6", lambda r: r['_prev_pos'] and 4 <= r['_prev_pos'] <= 6),
    ("N1, prev_pos 7+", lambda r: r['_prev_pos'] and r['_prev_pos'] >= 7),
    ("N1, same course", lambda r: r['_course'] == r['_prev_course']),
    ("N1, course switched", lambda r: r['_course'] != r['_prev_course'] and r['_prev_course']),
    ("N1, headcount 15-16", lambda r: r['_headcount'] and 15 <= r['_headcount'] <= 16),
    ("N1, weight_diff <= -6", lambda r: r['_weight_diff'] is not None and r['_weight_diff'] <= -6),
]:
    sub = [r for r in n1_rows if fn(r)]
    show(f"N1 + {label}", sub)

print("\n--- N2 sub-analysis ---")
n2_rows = [r for r in rows if r['_pop'] and 9 <= r['_pop'] <= 11 and r['_prev_pop'] and 4 <= r['_prev_pop'] <= 6]
for label, fn in [
    ("N2, prev_pos 1-3", lambda r: r['_prev_pos'] and 1 <= r['_prev_pos'] <= 3),
    ("N2, prev_pos 4-6", lambda r: r['_prev_pos'] and 4 <= r['_prev_pos'] <= 6),
    ("N2, prev_pos 7+", lambda r: r['_prev_pos'] and r['_prev_pos'] >= 7),
    ("N2, 芝→ダート", lambda r: r['_course']=='ダート' and r['_prev_course']=='芝'),
    ("N2, weight_diff<=-6", lambda r: r['_weight_diff'] is not None and r['_weight_diff'] <= -6),
]:
    sub = [r for r in n2_rows if fn(r)]
    show(f"N2 + {label}", sub)

print("\n--- N4 (weight) with expanded pop ---")
for label, fn in [
    ("pop>=6, weight_diff<=-6", lambda r: r['_weight_diff'] is not None and r['_weight_diff'] <= -6),
    ("pop>=6, weight_diff<=-8", lambda r: r['_weight_diff'] is not None and r['_weight_diff'] <= -8),
    ("pop>=6, weight_diff<=-10", lambda r: r['_weight_diff'] is not None and r['_weight_diff'] <= -10),
    ("pop 6-8, weight_diff<=-6", lambda r: r['_pop'] and 6<=r['_pop']<=8 and r['_weight_diff'] is not None and r['_weight_diff']<=-6),
    ("pop 9-11, weight_diff<=-6", lambda r: r['_pop'] and 9<=r['_pop']<=11 and r['_weight_diff'] is not None and r['_weight_diff']<=-6),
    ("pop>=12, weight_diff<=-6", lambda r: r['_pop'] and r['_pop']>=12 and r['_weight_diff'] is not None and r['_weight_diff']<=-6),
    ("pop>=6, weight_diff<=-6, ダート", lambda r: r['_weight_diff'] is not None and r['_weight_diff']<=-6 and r['_course']=='ダート'),
    ("pop>=6, weight_diff<=-6, 芝", lambda r: r['_weight_diff'] is not None and r['_weight_diff']<=-6 and r['_course']=='芝'),
]:
    show(label, [r for r in longshots if fn(r)])

print("\n--- prev_pos 4-6 + same course combos ---")
for label, fn in [
    ("prev_pos 4-6, same course, pop 6-8", lambda r: r['_prev_pos'] and 4<=r['_prev_pos']<=6 and r['_course']==r['_prev_course'] and r['_pop'] and 6<=r['_pop']<=8),
    ("prev_pos 4-6, same course, pop 9-11", lambda r: r['_prev_pos'] and 4<=r['_prev_pos']<=6 and r['_course']==r['_prev_course'] and r['_pop'] and 9<=r['_pop']<=11),
    ("prev_pos 4-6, same course, same dist", lambda r: r['_prev_pos'] and 4<=r['_prev_pos']<=6 and r['_course']==r['_prev_course'] and r['_distance']==r['_prev_dist']),
    ("prev_pos 1-3, pop 6-8 (前走好走穴)", lambda r: r['_prev_pos'] and 1<=r['_prev_pos']<=3 and r['_pop'] and 6<=r['_pop']<=8),
    ("prev_pos 1-3, pop 9-11", lambda r: r['_prev_pos'] and 1<=r['_prev_pos']<=3 and r['_pop'] and 9<=r['_pop']<=11),
]:
    show(label, [r for r in longshots if fn(r)])

print("\n--- Specific combined signals with n>=30 ---")
# Check headcount reduced 3+ vs 2+
n7_strict = [r for r in longshots if r['_prev_pos'] and 4 <= r['_prev_pos'] <= 6
             and r['_prev_hc'] and r['_prev_hc'] > 0 and r['_headcount'] and r['_headcount'] <= r['_prev_hc'] - 3]
show("N7 strict (headcount down 3+)", n7_strict)

# Pop 9-11 AND prev_pop 7-9 (extending N1/N2)
p9_pp79 = [r for r in rows if r['_pop'] and 9<=r['_pop']<=11 and r['_prev_pop'] and 7<=r['_prev_pop']<=9]
show("pop 9-11, prev_pop 7-9", p9_pp79)

# Small field ダート + previous good finish
dart_small = [r for r in longshots if r['_course']=='ダート' and r['_headcount'] and r['_headcount']<=10 and r['_prev_pos'] and r['_prev_pos']<=3]
show("ダート headcount<=10, prev_pos 1-3", dart_small)

# N6 extension: ダート headcount 11-14 (larger)
n6_ext = [r for r in longshots if r['_course']=='ダート' and r['_headcount'] and 11<=r['_headcount']<=14]
show("ダート headcount 11-14", n6_ext)

# 前走大敗から巻き返し: prev_pos 7+ AND pop 9-11
prev_bad_now_mid = [r for r in rows if r['_pop'] and 9<=r['_pop']<=11 and r['_prev_pos'] and r['_prev_pos']>=8]
show("pop 9-11, prev_pos 8+ (前走大敗巻き返し)", prev_bad_now_mid)

# prev_pop low (was fav), prev_pos bad, now high pop
fav_flop = [r for r in rows if r['_pop'] and r['_pop']>=9 and r['_prev_pop'] and r['_prev_pop']<=3 and r['_prev_pos'] and r['_prev_pos']>=5]
show("pop>=9, prev_pop 1-3, prev_pos 5+ (人気裏切り型)", fav_flop)

# 前走1人気 prev_pos 1-3 → now 9-11 (N1 refined: prev won)
n1_prev_good = [r for r in n1_rows if r['_prev_pop'] == 1 and r['_prev_pos'] and r['_prev_pos'] <= 3]
show("N1: prev_pop=1, prev_pos 1-3 (前走1人気好走)", n1_prev_good)

print("\n" + "="*70)
print("SUMMARY: Signals with 単勝ROI >= 105 and n >= 50")
print("="*70)
summary_tests = [
    # Existing signals
    ("N1: pop 9-11, prev_pop 1-3", [r for r in rows if r['_pop'] and 9<=r['_pop']<=11 and r['_prev_pop'] and 1<=r['_prev_pop']<=3]),
    ("N2: pop 9-11, prev_pop 4-6", [r for r in rows if r['_pop'] and 9<=r['_pop']<=11 and r['_prev_pop'] and 4<=r['_prev_pop']<=6]),
    ("N3: pop>=6, prev_pos 4-6, same course", [r for r in longshots if r['_prev_pos'] and 4<=r['_prev_pos']<=6 and r['_course']==r['_prev_course']]),
    ("N4: pop>=6, weight_diff<=-6", [r for r in longshots if r['_weight_diff'] is not None and r['_weight_diff']<=-6]),
    ("N5: pop 6-8, prev_pop 7-10", [r for r in rows if r['_pop'] and 6<=r['_pop']<=8 and r['_prev_pop'] and 7<=r['_prev_pop']<=10]),
    ("N6: ダート, pop>=6, headcount<=10", [r for r in longshots if r['_course']=='ダート' and r['_headcount'] and r['_headcount']<=10]),
    ("N7: prev_pos 4-6, headcount down 2+", n7),
    # New candidate signals
    ("C1_cand: jockey wr>=0.20", [r for r in c_rows if r['_jockey_wr'] >= 0.20]),
    ("C2_cand: jockey wr>=0.25", [r for r in c_rows if r['_jockey_wr'] >= 0.25]),
    ("C_neg: jockey wr<0.03", [r for r in c_rows if r['_jockey_wr'] < 0.03]),
    # New signals from analysis
    ("NEW: pop>=12, prev_pop 1-2", [r for r in pop12 if r['_prev_pop'] and 1<=r['_prev_pop']<=2]),
    ("NEW: pop 9-11, prev_pop 7-9", p9_pp79),
    ("NEW: prev_pos 1-3, pop 6-8", [r for r in longshots if r['_prev_pos'] and 1<=r['_prev_pos']<=3 and r['_pop'] and 6<=r['_pop']<=8]),
    ("NEW: 芝→ダート, prev_pop 1-3", [r for r in switch if r['_prev_pop'] and 1<=r['_prev_pop']<=3]),
    ("NEW: weight_diff<=-8, pop>=6", [r for r in longshots if r['_weight_diff'] is not None and r['_weight_diff']<=-8]),
    ("NEW: weight_diff<=-10, pop>=6", [r for r in longshots if r['_weight_diff'] is not None and r['_weight_diff']<=-10]),
    ("NEW: pop 9-11, prev_pos 4-6 (N1+bad prev finish)", [r for r in rows if r['_pop'] and 9<=r['_pop']<=11 and r['_prev_pos'] and 4<=r['_prev_pos']<=6]),
]
print(f"\n{'Signal':<50} {'n':>6}  {'単勝ROI':>8}  {'複勝ROI':>8}")
print("-"*80)
for label, rlist in summary_tests:
    n = len(rlist)
    tan = roi(rlist, 'tansho_payout')
    fuku = roi(rlist, 'fukusho_payout')
    flag = '✓' if tan >= 105 and n >= 50 else ('△' if tan >= 100 and n >= 50 else ' ')
    print(f"  {flag} {label:<48} {n:>6}  {tan:>8.1f}  {fuku:>8.1f}")

print("\nDone.")
