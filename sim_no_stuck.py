#!/usr/bin/env python3
"""sim_no_stuck.py — fix the stuck problem with floor-aware fire sizing.

Old problem: PAUSE at $7 = cap=0 → no fires → no recovery from $5-$7 range
                                                = STUCK forever

Fix: allow 1 fire/mkt at $5-$7 tier BUT with fire_size = min(kelly, (bal-$5)*0.5)
     This GUARANTEES a single loss can't push us below $5 (wipe floor).
     Each loss at most halves the gap to floor. Multiple losses asymptote
     toward but never cross $5.

Result: recovery from low bal IS possible. Wipe is still mathematically impossible.
"""
import re
import glob
import random
from collections import defaultdict


PATH_PATTERN = 'data/quant_bots_logs_replay/race_test_btc-updown-5m-*.log'
MIN_CD = 15
HALT = 5.00     # never go below this

PERM_SIGNIFICANT = {
    't4_ext', 'early_up_collapse_dn', 't6_early', 't4_late',
}
LIVE_POSITIVE = {
    'depth_collapse_mid', 'depth_collapse_mid_v2', 'depth_collapse_mid_v3',
    'v5_shadow_b5_mod_plus', 'depth_surge', 'late_dip_recovery',
}
UNION = PERM_SIGNIFICANT | LIVE_POSITIVE
ALL_POS_EV = UNION | {
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
        if fires:
            markets[slug] = {'winner': winner, 'fires': fires}
    return markets


def floor_aware_fire_size(bal, kelly_pct=0.05, min_size=0.05, buffer=0.5):
    """Return fire size that mathematically can't push us below HALT.

    fire_size = min(kelly_size, (bal - HALT) * buffer)

    With buffer=0.5: each loss reduces gap-to-floor by 50% (asymptotic safety).
    With buffer=0.99: each loss could leave us $0.01 from floor (one more loss = HALT)

    Default buffer=0.5 → mathematically can't wipe even with infinite losses.
    """
    if bal <= HALT:
        return 0.0
    kelly = max(min_size, bal * kelly_pct)
    safety_cap = (bal - HALT) * buffer
    return min(kelly, max(safety_cap, 0.0))


def get_cap(bal, low_tier_cap=1):
    """Cap = max number of fires per market.
    Below HALT: 0. Otherwise: 1 (single-fire keeps math safe with floor-aware sizing)
    Above $10: scale up like before.
    """
    if bal <= HALT: return 0
    if bal < 10: return low_tier_cap
    if bal < 20: return 2
    if bal < 50: return 3
    return 4


def simulate(markets_data, slugs_seq, allowed, low_tier_cap=1, max_mkts=3000,
             kelly_pct=0.05, safety_buffer=0.5):
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
        if cap == 0:
            continue
        eligible = [f for f in m['fires'] if f['strategy'] in allowed]
        if not eligible:
            continue
        eligible.sort(key=lambda f: f['price'])  # cheapest first
        taken = eligible[:cap]
        for f in taken:
            size = floor_aware_fire_size(bal, kelly_pct, buffer=safety_buffer)
            if size <= 0:
                continue
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


def run(markets_data, allowed, n_runs=2000, mkt_budget=3000, kelly_pct=0.05,
        safety_buffer=0.5, low_tier_cap=1):
    all_slugs = list(markets_data.keys())
    results = []
    for _ in range(n_runs):
        seq = [random.choice(all_slugs) for _ in range(mkt_budget)]
        results.append(simulate(markets_data, seq, allowed, low_tier_cap,
                                mkt_budget, kelly_pct, safety_buffer))
    return results


def summarize(name, results):
    n = len(results)
    succ = sum(1 for r in results if r['success'])
    wipe = sum(1 for r in results if r['wiped'])
    bals = sorted([r['bal'] for r in results])
    succ_mkts = sorted([r['mkts_to_100'] for r in results if r['mkts_to_100']])
    fires = sorted([r['fires'] for r in results])
    print(f"\n{'='*78}")
    print(f"{name}")
    print(f"{'='*78}")
    print(f"  reach $100: {succ:5d}/{n} ({100*succ/n:.1f}%)   wipe: {wipe:5d}/{n} ({100*wipe/n:.1f}%)")
    print(f"  bal p10/50/90: ${bals[n//10]:.2f} / ${bals[n//2]:.2f} / ${bals[9*n//10]:.2f}")
    print(f"  fires used p50: {fires[n//2]}")
    if succ_mkts:
        nm = len(succ_mkts)
        print(f"  mkts to $100: p25={succ_mkts[nm//4]} p50={succ_mkts[nm//2]} p75={succ_mkts[3*nm//4]}")
        print(f"  avg gain/mkt at p50: ${91/succ_mkts[nm//2]:.3f}")


def main():
    markets = load_markets()
    print(f"Loaded {len(markets)} markets")
    random.seed(42)

    print("\n=== Same setup with NEW floor-aware sizing (no stuck) ===")

    for name, pool in [('PERM_SIGNIFICANT (n=4)', PERM_SIGNIFICANT),
                       ('LIVE_POSITIVE (n=6)', LIVE_POSITIVE),
                       ('UNION (n=10)', UNION),
                       ('ALL_POS_EV (n=17)', ALL_POS_EV)]:
        results = run(markets, pool, n_runs=2000, mkt_budget=3000,
                      kelly_pct=0.05, safety_buffer=0.5)
        summarize(f"{name} + Kelly 5% + safety_buffer=0.5", results)

    print("\n=== Push safety_buffer higher (more aggressive recovery) ===")
    for buf in [0.7, 0.9, 0.99]:
        results = run(markets, PERM_SIGNIFICANT, n_runs=2000, mkt_budget=3000,
                      kelly_pct=0.05, safety_buffer=buf)
        summarize(f"PERM_SIGNIFICANT + Kelly 5% + safety_buffer={buf}", results)


if __name__ == "__main__":
    main()
