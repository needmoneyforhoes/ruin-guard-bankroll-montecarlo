#!/usr/bin/env python3
"""sim_faster.py — target $0.25-$0.50/market while keeping 0% wipe.

Levers tried:
  - Higher Kelly % (5% → 10% → 15% → 20% → 25%)
  - Multi-fire per market at low tier (cap=2, 3, 4)
  - Broader strategy pool (more eligible fires per market)
  - Combined: best speed + safety
"""
import re
import glob
import random
from collections import defaultdict


PATH_PATTERN = 'data/quant_bots_logs_replay/race_test_btc-updown-5m-*.log'
MIN_CD = 15
HALT = 5.00

PERM_SIGNIFICANT = {'t4_ext', 'early_up_collapse_dn', 't6_early', 't4_late'}
LIVE_POSITIVE = {
    'depth_collapse_mid', 'depth_collapse_mid_v2', 'depth_collapse_mid_v3',
    'v5_shadow_b5_mod_plus', 'depth_surge', 'late_dip_recovery',
}
PERM_PLUS_BIG_LIVE = PERM_SIGNIFICANT | {'depth_collapse_mid', 'depth_collapse_mid_v2',
                                          'depth_collapse_mid_v3', 'depth_surge'}
ALL_POS_EV = PERM_SIGNIFICANT | LIVE_POSITIVE | {
    'deep_dip_filtered', 'up_deep_spread_collapse', 'fake_train_detector',
    'cusp', 'up_deep_accumulation', 'flip_medium', 'deep_dip_scout',
}


def load_markets():
    pattern = re.compile(
        r'(\d+)\.\s+(\S+)\s+(?:🔵 SHADOW|🟢 LIVE)\s+(UP|DN)\s+@\s+\$(\d+\.\d+)\s+[\d.]+sh\s+cd=(\d+)')
    winner_pattern = re.compile(r'MARKET RECAP.*\(winner=(\w+)\)')
    paths = sorted(set(glob.glob(PATH_PATTERN)))
    random.seed(42)
    if len(paths) > 500:
        paths = random.sample(paths, 500)
    markets = {}
    for p in paths:
        try: text = open(p).read()
        except: continue
        m = winner_pattern.search(text)
        if not m: continue
        winner = m.group(1)
        if winner not in ('UP','DN'): continue
        slug = p.split('-')[-1].replace('.log', '')
        fires = []
        for fm in pattern.finditer(text):
            try:
                strat = fm.group(2); side = fm.group(3)
                price = float(fm.group(4)); cd = int(fm.group(5))
            except: continue
            if price <= 0 or price >= 1 or cd <= MIN_CD: continue
            won = (side == winner)
            fires.append({'strategy': strat, 'side': side, 'price': price,
                          'cd': cd, 'won': won})
        if fires: markets[slug] = {'winner': winner, 'fires': fires}
    return markets


def floor_aware_size(bal, kelly_pct, buffer=0.5, min_size=0.05):
    if bal <= HALT: return 0.0
    kelly = max(min_size, bal * kelly_pct)
    safety = (bal - HALT) * buffer
    return max(0.0, min(kelly, safety))


def get_cap(bal, low_tier_cap=1):
    if bal <= HALT: return 0
    if bal < 10: return low_tier_cap
    if bal < 20: return max(2, low_tier_cap)
    if bal < 50: return max(3, low_tier_cap)
    return max(4, low_tier_cap)


def simulate(markets_data, slugs_seq, allowed, kelly_pct=0.05,
             low_tier_cap=1, buffer=0.5, max_mkts=3000):
    bal = 9.0
    peak = 9.0
    max_dd = 0.0
    fires_taken = 0
    wins = 0
    mkts_run = 0
    mkts_to_100 = None

    for slug in slugs_seq[:max_mkts]:
        mkts_run += 1
        m = markets_data[slug]
        cap = get_cap(bal, low_tier_cap)
        if cap == 0: continue
        eligible = sorted([f for f in m['fires'] if f['strategy'] in allowed],
                          key=lambda f: f['price'])
        if not eligible: continue
        taken = eligible[:cap]
        for f in taken:
            size = floor_aware_size(bal, kelly_pct, buffer)
            if size <= 0: break
            fires_taken += 1
            if f['won']:
                wins += 1
                bal += size * (1.0 / f['price'] - 1)
            else:
                bal -= size
            if bal > peak: peak = bal
            dd = peak - bal
            if dd > max_dd: max_dd = dd
            if bal >= 100 and mkts_to_100 is None:
                return {'success': True, 'wiped': bal < HALT, 'bal': bal,
                        'fires': fires_taken, 'wins': wins, 'max_dd': max_dd,
                        'mkts_to_100': mkts_run, 'mkts': mkts_run}
            if bal < HALT:
                return {'success': False, 'wiped': True, 'bal': bal,
                        'fires': fires_taken, 'wins': wins, 'max_dd': max_dd,
                        'mkts_to_100': None, 'mkts': mkts_run}
    return {'success': bal >= 100, 'wiped': bal < HALT, 'bal': bal,
            'fires': fires_taken, 'wins': wins, 'max_dd': max_dd,
            'mkts_to_100': mkts_to_100, 'mkts': mkts_run}


def run(markets_data, allowed, kelly_pct=0.05, cap=1, buffer=0.5,
        n_runs=2000, budget=2500):
    all_slugs = list(markets_data.keys())
    results = []
    for _ in range(n_runs):
        seq = [random.choice(all_slugs) for _ in range(budget)]
        results.append(simulate(markets_data, seq, allowed, kelly_pct, cap, buffer, budget))
    return results


def summarize(name, results):
    n = len(results)
    succ = sum(1 for r in results if r['success'])
    wipe = sum(1 for r in results if r['wiped'])
    bals = sorted([r['bal'] for r in results])
    succ_mkts = sorted([r['mkts_to_100'] for r in results if r['mkts_to_100']])
    print(f"\n{name}")
    print(f"  reach $100: {succ:5d}/{n} ({100*succ/n:.1f}%)   wipe: {wipe:5d} ({100*wipe/n:.1f}%)")
    print(f"  bal p10/50/90: ${bals[n//10]:.2f} / ${bals[n//2]:.2f} / ${bals[9*n//10]:.2f}")
    if succ_mkts:
        nm = len(succ_mkts)
        m_med = succ_mkts[nm//2]
        print(f"  mkts to $100: p25={succ_mkts[nm//4]} p50={m_med} p75={succ_mkts[3*nm//4]}")
        print(f"  → $/mkt at p50: ${91/m_med:.3f}")


def main():
    markets = load_markets()
    print(f"Loaded {len(markets)} markets\n")
    random.seed(42)

    print("="*80)
    print("BASELINE (current safest): PERM_SIGNIFICANT + Kelly 5% + cap=1 + buffer=0.5")
    print("="*80)
    r = run(markets, PERM_SIGNIFICANT, kelly_pct=0.05, cap=1, buffer=0.5)
    summarize("baseline", r)

    print("\n" + "="*80)
    print("KELLY RAMP — keep PERM, cap=1, increase Kelly")
    print("="*80)
    for kelly in [0.10, 0.15, 0.20, 0.25, 0.30]:
        r = run(markets, PERM_SIGNIFICANT, kelly_pct=kelly, cap=1, buffer=0.5)
        summarize(f"PERM + Kelly={int(kelly*100)}% cap=1", r)

    print("\n" + "="*80)
    print("CAP RAMP — keep PERM + Kelly 10%, increase cap (multi-fire/mkt)")
    print("="*80)
    for cap in [2, 3, 4]:
        r = run(markets, PERM_SIGNIFICANT, kelly_pct=0.10, cap=cap, buffer=0.5)
        summarize(f"PERM + Kelly=10% cap={cap}", r)

    print("\n" + "="*80)
    print("BROADER POOL + aggressive Kelly")
    print("="*80)
    for name, pool in [('PERM_PLUS_BIG_LIVE (8)', PERM_PLUS_BIG_LIVE),
                       ('ALL_POS_EV (17)', ALL_POS_EV)]:
        for kelly in [0.10, 0.20]:
            for cap in [1, 3]:
                r = run(markets, pool, kelly_pct=kelly, cap=cap, buffer=0.5)
                summarize(f"{name} + Kelly={int(kelly*100)}% cap={cap}", r)

    print("\n" + "="*80)
    print("SAFETY BUFFER RAMP — PERM + Kelly 15% cap=2, buffer higher (closer to floor)")
    print("="*80)
    for buf in [0.7, 0.9, 0.99]:
        r = run(markets, PERM_SIGNIFICANT, kelly_pct=0.15, cap=2, buffer=buf)
        summarize(f"PERM + Kelly=15% cap=2 buffer={buf}", r)


if __name__ == "__main__":
    main()
