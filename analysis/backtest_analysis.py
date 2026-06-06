"""
Comprehensive backtest analysis for signal_rules.py tuning.
"""
import csv
import math
from collections import defaultdict

DATA_PATH = '/root/.claude/uploads/399386ab-90ee-5e54-b833-76894dff6fa4/6110de4a-analysis_data.csv'
JOCKEY_PATH = '/root/.claude/uploads/399386ab-90ee-5e54-b833-76894dff6fa4/4d7d3f12-jockey_stats.csv'
RACE_3F_PATH = '/root/.claude/uploads/399386ab-90ee-5e54-b833-76894dff6fa4/6c8b64fc-race_3f_stats.csv'


def load_csv(path):
    rows = []
    with open(path, encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def roi(bets, payouts):
    """ROI = sum(payouts) / count(bets) * 100"""
    if not bets:
        return 0
    return sum(payouts) / len(bets) * 100


def analyze_bucket(rows, label, cond_fn, payout_field='tansho_payout'):
    matched = [r for r in rows if cond_fn(r)]
    payouts = []
    for r in matched:
        p = to_float(r.get(payout_field, ''))
        if p is None:
            p = 0
        payouts.append(p)
    tan_roi = roi(matched, payouts)

    fuku_payouts = []
    for r in matched:
        p = to_float(r.get('fukusho_payout', ''))
        if p is None:
            p = 0
        fuku_payouts.append(p)
    fuku_roi = roi(matched, fuku_payouts)

    return len(matched), tan_roi, fuku_roi


def print_bucket(label, n, tan, fuku):
    flag = '✓' if tan > 100 and n >= 30 else ('△' if tan > 100 else ' ')
    print(f"  {flag} {label:<50} n={n:5d}  単勝ROI={tan:6.1f}  複勝ROI={fuku:6.1f}")


# Load data
print("Loading data...")
rows = load_csv(DATA_PATH)
jockey_rows = load_csv(JOCKEY_PATH)
race_3f_rows = load_csv(RACE_3F_PATH)

# Pre-process
race_3f = {}
for r in race_3f_rows:
    rid = r['race_id']
    v = to_float(r.get('avg_3f'))
    if v:
        race_3f[rid] = v

jockey_stats = {}
for r in jockey_rows:
    total = to_int(r['total']) or 0
    wins = to_int(r['wins']) or 0
    if total >= 20:
        jockey_stats[(r['jockey_name'], r['course_type'])] = wins / total

# Augment rows
for r in rows:
    r['_pop'] = to_int(r.get('popularity'))
    r['_odds'] = to_float(r.get('odds'))
    r['_prev_pop'] = to_int(r.get('prev_pop'))
    r['_prev_pos'] = to_int(r.get('prev_pos'))
    r['_prev2_pos'] = to_int(r.get('prev2_pos'))
    r['_finish'] = to_int(r.get('finish_position'))
    r['_headcount'] = to_int(r.get('headcount'))
    r['_prev_hc'] = to_int(r.get('prev_hc'))
    r['_weight_diff'] = to_float(r.get('horse_weight_diff'))
    r['_prev_3f'] = to_float(r.get('prev_last3f')) or to_float(r.get('last_3f'))  # prev_last3f from data
    r['_course'] = r.get('course_type', '')
    r['_prev_course'] = r.get('prev_course', '')
    r['_distance'] = to_int(r.get('distance'))
    r['_prev_dist'] = to_int(r.get('prev_dist'))
    r['_venue'] = r.get('venue', '')
    r['_race_class'] = r.get('race_class', '')
    r['_prev_class'] = r.get('prev_class', '')
    r['_track_cond'] = r.get('track_condition', '')

    # 3F deviation
    avg3f = race_3f.get(r.get('race_id', ''))
    prev3f = to_float(r.get('prev_last3f'))
    if avg3f and prev3f:
        r['_3f_diff'] = avg3f - prev3f
    else:
        r['_3f_diff'] = None

    # Jockey win rate
    jr = jockey_stats.get((r.get('jockey_name', ''), r['_course']))
    r['_jockey_wr'] = jr

# Base: all longshots (pop >= 6)
longshots = [r for r in rows if r['_pop'] and r['_pop'] >= 6]
print(f"\nTotal rows: {len(rows)}, Longshots (pop>=6): {len(longshots)}")

print("\n" + "="*80)
print("AXIS B1: 3F deviation analysis")
print("="*80)

b1_rows = [r for r in longshots if r['_3f_diff'] is not None]
print(f"Rows with 3F data: {len(b1_rows)}")

bins = [
    ("diff >= 3.0", lambda r: r['_3f_diff'] >= 3.0),
    ("diff 2.0-3.0", lambda r: 2.0 <= r['_3f_diff'] < 3.0),
    ("diff 1.5-2.0", lambda r: 1.5 <= r['_3f_diff'] < 2.0),
    ("diff 1.0-1.5", lambda r: 1.0 <= r['_3f_diff'] < 1.5),
    ("diff 0.5-1.0", lambda r: 0.5 <= r['_3f_diff'] < 1.0),
    ("diff 0.0-0.5", lambda r: 0.0 <= r['_3f_diff'] < 0.5),
    ("diff -0.5 to 0", lambda r: -0.5 <= r['_3f_diff'] < 0.0),
    ("diff -1.0 to -0.5", lambda r: -1.0 <= r['_3f_diff'] < -0.5),
    ("diff <= -1.0", lambda r: r['_3f_diff'] <= -1.0),
    ("diff <= -2.0", lambda r: r['_3f_diff'] <= -2.0),
]
for label, fn in bins:
    n, tan, fuku = analyze_bucket(b1_rows, label, fn)
    print_bucket(label, n, tan, fuku)

print("\n" + "="*80)
print("AXIS B2: Performance trend analysis")
print("="*80)

b2_rows = [r for r in longshots if r['_prev_pos'] and r['_prev2_pos']]
print(f"Rows with 2 prev races: {len(b2_rows)}")

trend_bins = [
    ("improved (prev_pos < prev2_pos)", lambda r: r['_prev_pos'] < r['_prev2_pos']),
    ("same (prev_pos == prev2_pos)", lambda r: r['_prev_pos'] == r['_prev2_pos']),
    ("worsened (prev_pos > prev2_pos)", lambda r: r['_prev_pos'] > r['_prev2_pos']),
    ("big improve (diff >= 3)", lambda r: r['_prev2_pos'] - r['_prev_pos'] >= 3),
    ("small improve (diff 1-2)", lambda r: 1 <= r['_prev2_pos'] - r['_prev_pos'] <= 2),
    ("big worsen (diff >= 3)", lambda r: r['_prev_pos'] - r['_prev2_pos'] >= 3),
]
for label, fn in trend_bins:
    n, tan, fuku = analyze_bucket(b2_rows, label, fn)
    print_bucket(label, n, tan, fuku)

print("\n" + "="*80)
print("AXIS C: Jockey win rate thresholds")
print("="*80)

c_rows = [r for r in longshots if r['_jockey_wr'] is not None]
print(f"Rows with jockey data: {len(c_rows)}")

c_bins = [
    ("win_rate >= 0.30", lambda r: r['_jockey_wr'] >= 0.30),
    ("win_rate 0.25-0.30", lambda r: 0.25 <= r['_jockey_wr'] < 0.30),
    ("win_rate 0.20-0.25", lambda r: 0.20 <= r['_jockey_wr'] < 0.25),
    ("win_rate 0.15-0.20", lambda r: 0.15 <= r['_jockey_wr'] < 0.20),
    ("win_rate 0.10-0.15", lambda r: 0.10 <= r['_jockey_wr'] < 0.15),
    ("win_rate 0.05-0.10", lambda r: 0.05 <= r['_jockey_wr'] < 0.10),
    ("win_rate < 0.05", lambda r: r['_jockey_wr'] < 0.05),
    ("win_rate < 0.03", lambda r: r['_jockey_wr'] < 0.03),
]
for label, fn in c_bins:
    n, tan, fuku = analyze_bucket(c_rows, label, fn)
    print_bucket(label, n, tan, fuku)

print("\n" + "="*80)
print("TASK 4: NEW SIGNAL DISCOVERY")
print("="*80)

print("\n--- Distance change ---")
dist_bins = [
    ("dist increase >= 400", lambda r: r['_distance'] and r['_prev_dist'] and r['_distance'] - r['_prev_dist'] >= 400),
    ("dist increase 200-400", lambda r: r['_distance'] and r['_prev_dist'] and 200 <= r['_distance'] - r['_prev_dist'] < 400),
    ("dist increase 1-200", lambda r: r['_distance'] and r['_prev_dist'] and 1 <= r['_distance'] - r['_prev_dist'] < 200),
    ("same distance", lambda r: r['_distance'] and r['_prev_dist'] and r['_distance'] == r['_prev_dist']),
    ("dist decrease -1 to -200", lambda r: r['_distance'] and r['_prev_dist'] and -200 <= r['_distance'] - r['_prev_dist'] < 0),
    ("dist decrease -200 to -400", lambda r: r['_distance'] and r['_prev_dist'] and -400 <= r['_distance'] - r['_prev_dist'] < -200),
    ("dist decrease <= -400", lambda r: r['_distance'] and r['_prev_dist'] and r['_distance'] - r['_prev_dist'] <= -400),
]
for label, fn in dist_bins:
    n, tan, fuku = analyze_bucket(longshots, label, fn)
    print_bucket(label, n, tan, fuku)

print("\n--- Course switch ---")
course_bins = [
    ("芝→ダート switch", lambda r: r['_course'] == 'ダート' and r['_prev_course'] == '芝'),
    ("ダート→芝 switch", lambda r: r['_course'] == '芝' and r['_prev_course'] == 'ダート'),
    ("same course (芝)", lambda r: r['_course'] == '芝' and r['_prev_course'] == '芝'),
    ("same course (ダート)", lambda r: r['_course'] == 'ダート' and r['_prev_course'] == 'ダート'),
]
for label, fn in course_bins:
    n, tan, fuku = analyze_bucket(longshots, label, fn)
    print_bucket(label, n, tan, fuku)

print("\n--- Track condition ---")
# Get unique track conditions
conds = set(r['_track_cond'] for r in longshots if r['_track_cond'])
print(f"  Track conditions found: {sorted(conds)}")
for cond in sorted(conds):
    fn = lambda r, c=cond: r['_track_cond'] == c
    n, tan, fuku = analyze_bucket(longshots, f"track_cond={cond}", fn)
    print_bucket(f"track_cond={cond}", n, tan, fuku)

print("\n--- Headcount ranges ---")
hc_bins = [
    ("headcount <= 8", lambda r: r['_headcount'] and r['_headcount'] <= 8),
    ("headcount 9-10", lambda r: r['_headcount'] and 9 <= r['_headcount'] <= 10),
    ("headcount 11-12", lambda r: r['_headcount'] and 11 <= r['_headcount'] <= 12),
    ("headcount 13-14", lambda r: r['_headcount'] and 13 <= r['_headcount'] <= 14),
    ("headcount 15-16", lambda r: r['_headcount'] and 15 <= r['_headcount'] <= 16),
    ("headcount >= 17", lambda r: r['_headcount'] and r['_headcount'] >= 17),
    ("headcount <= 6", lambda r: r['_headcount'] and r['_headcount'] <= 6),
]
for label, fn in hc_bins:
    n, tan, fuku = analyze_bucket(longshots, label, fn)
    print_bucket(label, n, tan, fuku)

print("\n--- Weight diff granular ---")
wt_bins = [
    ("weight_diff <= -10", lambda r: r['_weight_diff'] is not None and r['_weight_diff'] <= -10),
    ("weight_diff -8 to -10", lambda r: r['_weight_diff'] is not None and -10 < r['_weight_diff'] <= -8),
    ("weight_diff -6 to -8", lambda r: r['_weight_diff'] is not None and -8 < r['_weight_diff'] <= -6),
    ("weight_diff -4 to -6", lambda r: r['_weight_diff'] is not None and -6 < r['_weight_diff'] <= -4),
    ("weight_diff -2 to -4", lambda r: r['_weight_diff'] is not None and -4 < r['_weight_diff'] <= -2),
    ("weight_diff -2 to +2", lambda r: r['_weight_diff'] is not None and -2 < r['_weight_diff'] <= 2),
    ("weight_diff >= 6", lambda r: r['_weight_diff'] is not None and r['_weight_diff'] >= 6),
    ("weight_diff >= 10", lambda r: r['_weight_diff'] is not None and r['_weight_diff'] >= 10),
]
for label, fn in wt_bins:
    n, tan, fuku = analyze_bucket(longshots, label, fn)
    print_bucket(label, n, tan, fuku)

print("\n--- Popularity exact ranges ---")
pop_bins = [
    ("pop = 6", lambda r: r['_pop'] == 6),
    ("pop = 7", lambda r: r['_pop'] == 7),
    ("pop = 8", lambda r: r['_pop'] == 8),
    ("pop = 9", lambda r: r['_pop'] == 9),
    ("pop = 10", lambda r: r['_pop'] == 10),
    ("pop = 11", lambda r: r['_pop'] == 11),
    ("pop = 12", lambda r: r['_pop'] == 12),
    ("pop = 13", lambda r: r['_pop'] == 13),
    ("pop >= 14", lambda r: r['_pop'] and r['_pop'] >= 14),
    ("pop >= 12", lambda r: r['_pop'] and r['_pop'] >= 12),
]
for label, fn in pop_bins:
    n, tan, fuku = analyze_bucket(longshots, label, fn)
    print_bucket(label, n, tan, fuku)

print("\n--- prev_pos exact (all longshots) ---")
pos_bins = [(f"prev_pos={p}", lambda r, p=p: r['_prev_pos'] == p) for p in range(1, 10)]
for label, fn in pos_bins:
    n, tan, fuku = analyze_bucket(longshots, label, fn)
    print_bucket(label, n, tan, fuku)

print("\n--- N1 sub-analysis (pop 9-11 AND prev_pop 1-3) ---")
n1_rows = [r for r in rows if r['_pop'] and 9 <= r['_pop'] <= 11 and r['_prev_pop'] and 1 <= r['_prev_pop'] <= 3]
print(f"  N1 total: {len(n1_rows)}")
n1_bins = [
    ("N1 + odds >= 20", lambda r: r['_odds'] and r['_odds'] >= 20),
    ("N1 + odds 10-20", lambda r: r['_odds'] and 10 <= r['_odds'] < 20),
    ("N1 + odds < 10", lambda r: r['_odds'] and r['_odds'] < 10),
    ("N1 + prev_pos 1", lambda r: r['_prev_pos'] == 1),
    ("N1 + prev_pos 2-3", lambda r: r['_prev_pos'] and 2 <= r['_prev_pos'] <= 3),
    ("N1 + prev_pos 4-6", lambda r: r['_prev_pos'] and 4 <= r['_prev_pos'] <= 6),
    ("N1 + prev_pos 7+", lambda r: r['_prev_pos'] and r['_prev_pos'] >= 7),
]
for label, fn in n1_bins:
    n, tan, fuku = analyze_bucket(n1_rows, label, fn)
    print_bucket(label, n, tan, fuku)

print("\n--- N1 + B1 combined signal ---")
n1b1_rows = [r for r in n1_rows if r['_3f_diff'] is not None]
print(f"  N1 with 3F data: {len(n1b1_rows)}")
n1b1_bins = [
    ("N1 + 3F diff >= 1.0", lambda r: r['_3f_diff'] is not None and r['_3f_diff'] >= 1.0),
    ("N1 + 3F diff >= 0.5", lambda r: r['_3f_diff'] is not None and r['_3f_diff'] >= 0.5),
    ("N1 + 3F diff < 0.5", lambda r: r['_3f_diff'] is not None and r['_3f_diff'] < 0.5),
]
for label, fn in n1b1_bins:
    n, tan, fuku = analyze_bucket(n1b1_rows, label, fn)
    print_bucket(label, n, tan, fuku)

print("\n--- Venue analysis (longshots) ---")
venues = sorted(set(r['_venue'] for r in longshots if r['_venue']))
print(f"  Venues: {venues}")
for v in venues:
    fn = lambda r, v=v: r['_venue'] == v
    n, tan, fuku = analyze_bucket(longshots, f"venue={v}", fn)
    print_bucket(f"venue={v}", n, tan, fuku)

print("\n--- Class patterns (prev_class → race_class) ---")
# Class drop (降級) detection - check if class string changed
# Show raw class values
classes = set(r['_race_class'] for r in rows if r['_race_class'])
prev_classes = set(r['_prev_class'] for r in rows if r['_prev_class'])
print(f"  race_class values: {sorted(classes)[:20]}")
print(f"  prev_class values: {sorted(prev_classes)[:20]}")

# Check if class dropped (very basic - same or different)
class_rows = [r for r in longshots if r['_race_class'] and r['_prev_class']]
print(f"  Rows with class data: {len(class_rows)}")
same_class = [r for r in class_rows if r['_race_class'] == r['_prev_class']]
diff_class = [r for r in class_rows if r['_race_class'] != r['_prev_class']]
print(f"  Same class: {len(same_class)}, Diff class: {len(diff_class)}")

for label, rlist in [("same class", same_class), ("changed class", diff_class)]:
    payouts = [to_float(r.get('tansho_payout') or '0') or 0 for r in rlist]
    fuku_p = [to_float(r.get('fukusho_payout') or '0') or 0 for r in rlist]
    tan = roi(rlist, payouts)
    fuku = roi(rlist, fuku_p)
    print_bucket(label, len(rlist), tan, fuku)

print("\n--- ダート少頭数 more granular (N6 extension) ---")
dart_hc_bins = [
    ("ダート headcount <= 6", lambda r: r['_course'] == 'ダート' and r['_headcount'] and r['_headcount'] <= 6),
    ("ダート headcount 7-8", lambda r: r['_course'] == 'ダート' and r['_headcount'] and 7 <= r['_headcount'] <= 8),
    ("ダート headcount 9-10", lambda r: r['_course'] == 'ダート' and r['_headcount'] and 9 <= r['_headcount'] <= 10),
    ("ダート headcount 11-12", lambda r: r['_course'] == 'ダート' and r['_headcount'] and 11 <= r['_headcount'] <= 12),
    ("ダート headcount >= 13", lambda r: r['_course'] == 'ダート' and r['_headcount'] and r['_headcount'] >= 13),
]
for label, fn in dart_hc_bins:
    n, tan, fuku = analyze_bucket(longshots, label, fn)
    print_bucket(label, n, tan, fuku)

print("\n--- prev_pos for N1/N2 specific ---")
# N2 sub-analysis
n2_rows = [r for r in rows if r['_pop'] and 9 <= r['_pop'] <= 11 and r['_prev_pop'] and 4 <= r['_prev_pop'] <= 6]
print(f"  N2 total: {len(n2_rows)}")
n2_bins = [
    ("N2 + prev_pos 1-3", lambda r: r['_prev_pos'] and 1 <= r['_prev_pos'] <= 3),
    ("N2 + prev_pos 4-6", lambda r: r['_prev_pos'] and 4 <= r['_prev_pos'] <= 6),
    ("N2 + prev_pos 7+", lambda r: r['_prev_pos'] and r['_prev_pos'] >= 7),
    ("N2 + odds >= 30", lambda r: r['_odds'] and r['_odds'] >= 30),
    ("N2 + odds 15-30", lambda r: r['_odds'] and 15 <= r['_odds'] < 30),
]
for label, fn in n2_bins:
    n, tan, fuku = analyze_bucket(n2_rows, label, fn)
    print_bucket(label, n, tan, fuku)

print("\n--- pop 9-11 with various prev_pop ranges (expanding N1/N2) ---")
pop911_rows = [r for r in rows if r['_pop'] and 9 <= r['_pop'] <= 11]
pp_bins = [
    ("prev_pop 1", lambda r: r['_prev_pop'] == 1),
    ("prev_pop 2", lambda r: r['_prev_pop'] == 2),
    ("prev_pop 3", lambda r: r['_prev_pop'] == 3),
    ("prev_pop 4", lambda r: r['_prev_pop'] == 4),
    ("prev_pop 5", lambda r: r['_prev_pop'] == 5),
    ("prev_pop 6", lambda r: r['_prev_pop'] == 6),
    ("prev_pop 7", lambda r: r['_prev_pop'] == 7),
    ("prev_pop 8", lambda r: r['_prev_pop'] == 8),
    ("prev_pop 9-10", lambda r: r['_prev_pop'] and 9 <= r['_prev_pop'] <= 10),
]
print(f"  pop 9-11 total: {len(pop911_rows)}")
for label, fn in pp_bins:
    n, tan, fuku = analyze_bucket(pop911_rows, label, fn)
    print_bucket(label, n, tan, fuku)

print("\n--- pop 12+ analysis ---")
pop12_rows = [r for r in rows if r['_pop'] and r['_pop'] >= 12]
print(f"  pop 12+ total: {len(pop12_rows)}")
pp12_bins = [
    ("prev_pop 1-3", lambda r: r['_prev_pop'] and 1 <= r['_prev_pop'] <= 3),
    ("prev_pop 1-2", lambda r: r['_prev_pop'] and 1 <= r['_prev_pop'] <= 2),
    ("prev_pop 1 only", lambda r: r['_prev_pop'] == 1),
]
for label, fn in pp12_bins:
    n, tan, fuku = analyze_bucket(pop12_rows, label, fn)
    print_bucket(label, n, tan, fuku)

print("\n--- Distance × Course combinations ---")
combo_bins = [
    ("芝 short (<=1400)", lambda r: r['_course'] == '芝' and r['_distance'] and r['_distance'] <= 1400),
    ("芝 mile (1400-1800)", lambda r: r['_course'] == '芝' and r['_distance'] and 1400 < r['_distance'] <= 1800),
    ("芝 mid (1800-2200)", lambda r: r['_course'] == '芝' and r['_distance'] and 1800 < r['_distance'] <= 2200),
    ("芝 long (>2200)", lambda r: r['_course'] == '芝' and r['_distance'] and r['_distance'] > 2200),
    ("ダート short (<=1200)", lambda r: r['_course'] == 'ダート' and r['_distance'] and r['_distance'] <= 1200),
    ("ダート mid (1200-1800)", lambda r: r['_course'] == 'ダート' and r['_distance'] and 1200 < r['_distance'] <= 1800),
    ("ダート long (>1800)", lambda r: r['_course'] == 'ダート' and r['_distance'] and r['_distance'] > 1800),
]
for label, fn in combo_bins:
    n, tan, fuku = analyze_bucket(longshots, label, fn)
    print_bucket(label, n, tan, fuku)

print("\n--- N3 + same course + distance same/different ---")
n3_rows = [r for r in longshots if r['_prev_pos'] and 4 <= r['_prev_pos'] <= 6 and r['_course'] == r['_prev_course']]
print(f"  N3-eligible: {len(n3_rows)}")
n3_bins = [
    ("N3 + same distance", lambda r: r['_distance'] == r['_prev_dist']),
    ("N3 + distance changed", lambda r: r['_distance'] != r['_prev_dist']),
    ("N3 + ダート", lambda r: r['_course'] == 'ダート'),
    ("N3 + 芝", lambda r: r['_course'] == '芝'),
]
for label, fn in n3_bins:
    n, tan, fuku = analyze_bucket(n3_rows, label, fn)
    print_bucket(label, n, tan, fuku)

print("\n--- N4 (weight) × pop ranges ---")
n4_rows = [r for r in rows if r['_weight_diff'] is not None and r['_weight_diff'] <= -6]
print(f"  N4-eligible total: {len(n4_rows)}")
n4_bins = [
    ("N4 + pop 6-8", lambda r: r['_pop'] and 6 <= r['_pop'] <= 8),
    ("N4 + pop 9-11", lambda r: r['_pop'] and 9 <= r['_pop'] <= 11),
    ("N4 + pop >= 12", lambda r: r['_pop'] and r['_pop'] >= 12),
    ("N4 + pop >= 6", lambda r: r['_pop'] and r['_pop'] >= 6),
]
for label, fn in n4_bins:
    n, tan, fuku = analyze_bucket(n4_rows, label, fn)
    print_bucket(label, n, tan, fuku)

print("\n--- Odds range × signal interactions ---")
odds_bins = [
    ("pop 6-8 + odds 6-15", lambda r: r['_pop'] and 6 <= r['_pop'] <= 8 and r['_odds'] and 6 <= r['_odds'] < 15),
    ("pop 9-11 + odds 15-40", lambda r: r['_pop'] and 9 <= r['_pop'] <= 11 and r['_odds'] and 15 <= r['_odds'] < 40),
    ("pop 9-11 + odds >= 40", lambda r: r['_pop'] and 9 <= r['_pop'] <= 11 and r['_odds'] and r['_odds'] >= 40),
    ("pop >= 12 + odds >= 50", lambda r: r['_pop'] and r['_pop'] >= 12 and r['_odds'] and r['_odds'] >= 50),
]
for label, fn in odds_bins:
    n, tan, fuku = analyze_bucket(longshots, label, fn)
    print_bucket(label, n, tan, fuku)

print("\n--- 芝→ダート switch × other conditions ---")
switch_rows = [r for r in longshots if r['_course'] == 'ダート' and r['_prev_course'] == '芝']
print(f"  芝→ダート: {len(switch_rows)}")
sw_bins = [
    ("芝→ダート + pop 9-11", lambda r: r['_pop'] and 9 <= r['_pop'] <= 11),
    ("芝→ダート + prev_pop 1-3", lambda r: r['_prev_pop'] and 1 <= r['_prev_pop'] <= 3),
    ("芝→ダート + prev_pos 1-3", lambda r: r['_prev_pos'] and 1 <= r['_prev_pos'] <= 3),
]
for label, fn in sw_bins:
    n, tan, fuku = analyze_bucket(switch_rows, label, fn)
    print_bucket(label, n, tan, fuku)

print("\n--- Final comprehensive summary of signals >= 105 ROI ---")
print("\nAll signals with tansho_ROI >= 105 and n >= 30 (from longshots):")
all_tests = [
    # B1
    ("B1: 3F diff >= 2.0", lambda r: r['_3f_diff'] is not None and r['_3f_diff'] >= 2.0, longshots),
    ("B1: 3F diff 1.0-2.0", lambda r: r['_3f_diff'] is not None and 1.0 <= r['_3f_diff'] < 2.0, longshots),
    ("B1: 3F diff 0.5-1.0", lambda r: r['_3f_diff'] is not None and 0.5 <= r['_3f_diff'] < 1.0, longshots),
    # Course switch
    ("芝→ダート", lambda r: r['_course'] == 'ダート' and r['_prev_course'] == '芝', longshots),
    ("ダート→芝", lambda r: r['_course'] == '芝' and r['_prev_course'] == 'ダート', longshots),
    # Distance
    ("dist increase >= 400", lambda r: r['_distance'] and r['_prev_dist'] and r['_distance'] - r['_prev_dist'] >= 400, longshots),
    ("dist decrease <= -400", lambda r: r['_distance'] and r['_prev_dist'] and r['_distance'] - r['_prev_dist'] <= -400, longshots),
    # N1 combinations
    ("N1 base (pop 9-11, prev_pop 1-3)", lambda r: r['_pop'] and 9 <= r['_pop'] <= 11 and r['_prev_pop'] and 1 <= r['_prev_pop'] <= 3, rows),
    ("N2 base (pop 9-11, prev_pop 4-6)", lambda r: r['_pop'] and 9 <= r['_pop'] <= 11 and r['_prev_pop'] and 4 <= r['_prev_pop'] <= 6, rows),
]

print(f"\n{'Condition':<55} {'n':>6}  {'単勝ROI':>8}  {'複勝ROI':>8}")
print("-" * 85)
for label, fn, base in all_tests:
    matched = [r for r in base if fn(r)]
    payouts = [to_float(r.get('tansho_payout') or '0') or 0 for r in matched]
    fuku_p = [to_float(r.get('fukusho_payout') or '0') or 0 for r in matched]
    tan = roi(matched, payouts)
    fuku = roi(matched, fuku_p)
    flag = '✓' if tan >= 105 and len(matched) >= 30 else ' '
    print(f"  {flag} {label:<53} {len(matched):>6}  {tan:>8.1f}  {fuku:>8.1f}")

print("\nDone.")
