#!/usr/bin/env python3
"""sim_9to100_monte_carlo.py — bootstrap Monte Carlo of $9→$100 sim.

Uses shadow_predictor_log.jsonl (21 markets, 811 fires with M1 decisions per fire).
Resamples markets with replacement to simulate many $9→$100 paths.
Compares ruleset variants and reports:
  - % reach $100
  - % wipe to $5 floor
  - median final bal
  - median markets to reach $100
  - max drawdown
"""
import json
import random
from collections import defaultdict


SHADOW_LOG = '/home/polybot/polymarket-bot/data/shadow_predictor_log.jsonl'


def load_markets():
    """Returns {slug: {'winner': str, 'fires': [(ts, side, entry_price, m1_block_bool)]}}"""
    fires_by_mkt = defaultdict(list)
    winner_by_mkt = {}
    with open(SHADOW_LOG) as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            slug = d['slug']
            winner_by_mkt[slug] = d.get('winner')
            m1_block = d.get('decisions', {}).get('M1_winner_ml') == 'BLOCK'
            fires_by_mkt[slug].append({
                'ts': d['ts'],
                'side': d['side'],
                'entry_price': d['entry_price'],
                'm1_block': m1_block,
                'strategy': d.get('strategy', '?'),
            })
    # sort fires by ts within each market
    for slug in fires_by_mkt:
        fires_by_mkt[slug].sort(key=lambda x: x['ts'])
    # filter to markets with valid winners
    out = {}
    for slug, fires in fires_by_mkt.items():
        if winner_by_mkt[slug] in ('UP', 'DN'):
            out[slug] = {'winner': winner_by_mkt[slug], 'fires': fires}
    return out


def get_cap(bal, config):
    """Ruin guard cap. Returns # of fires allowed this market."""
    pause_thresh = config.get('pause_thresh', 7.0)
    halt_thresh = config.get('halt_thresh', 5.0)
    low_tier_cap = config.get('low_tier_cap', 0)  # cap in $5-$pause_thresh tier
    if bal < halt_thresh:
        return 0  # HALT — always
    if bal < pause_thresh:
        return low_tier_cap  # PAUSE tier
    if bal < 10:
        return 1
    if bal < 20:
        return 2
    if bal < 50:
        return 3
    return 4


def get_fire_size(bal, config):
    """Nominal fire size in dollars."""
    if bal < 10:
        return config.get('low_tier_size', 1.00)
    return 1.00


def simulate_one_path(markets_seq, config, max_mkts=500):
    """Run one $9→$100 path. Returns dict with results."""
    bal = 9.0
    peak = bal
    trough = bal
    max_dd = 0.0
    fires_taken = 0
    wins = 0
    losses = 0
    mkts = 0
    m1_blocks = 0

    for slug in markets_seq:
        mkts += 1
        if mkts > max_mkts:
            break
        m = markets_seq_data[slug]
        winner = m['winner']
        fires = m['fires']
        cap = get_cap(bal, config)
        if cap == 0:
            continue
        # Take first `cap` fires that pass M1 (if active)
        taken = []
        for f in fires:
            if len(taken) >= cap:
                break
            if config.get('m1_active', False) and f['m1_block']:
                m1_blocks += 1
                continue
            taken.append(f)
        # Apply PnL
        size = get_fire_size(bal, config)
        for f in taken:
            fires_taken += 1
            if f['side'] == winner:
                wins += 1
                pnl = size * (1.0 / f['entry_price'] - 1)
            else:
                losses += 1
                pnl = -size
            bal += pnl
            if bal > peak:
                peak = bal
            if peak - bal > max_dd:
                max_dd = peak - bal
            if bal < trough:
                trough = bal
            # Stop early on target/floor
            if bal >= 100:
                return dict(success=True, wiped=False, bal=bal, mkts=mkts,
                            fires=fires_taken, wins=wins, losses=losses,
                            max_dd=max_dd, m1_blocks=m1_blocks)
            if bal < 5:
                return dict(success=False, wiped=True, bal=bal, mkts=mkts,
                            fires=fires_taken, wins=wins, losses=losses,
                            max_dd=max_dd, m1_blocks=m1_blocks)

    return dict(success=(bal >= 100), wiped=(bal < 5), bal=bal, mkts=mkts,
                fires=fires_taken, wins=wins, losses=losses,
                max_dd=max_dd, m1_blocks=m1_blocks)


def run_config(markets_seq_data, config, n_runs=500, mkt_budget=500):
    """Run N bootstrap simulations for a config. Resamples markets WITH replacement."""
    all_slugs = list(markets_seq_data.keys())
    results = []
    for _ in range(n_runs):
        seq = [random.choice(all_slugs) for _ in range(mkt_budget)]
        r = simulate_one_path(seq, config, max_mkts=mkt_budget)
        results.append(r)
    return results


def summarize(name, results):
    n = len(results)
    succ = sum(1 for r in results if r['success'])
    wipe = sum(1 for r in results if r['wiped'])
    stuck = n - succ - wipe
    bals = sorted([r['bal'] for r in results])
    dds = sorted([r['max_dd'] for r in results])
    succ_mkts = sorted([r['mkts'] for r in results if r['success']])
    print(f"\n=== {name} ({n} runs) ===")
    print(f"  reach $100:    {succ:4d} ({100*succ/n:.1f}%)")
    print(f"  wipe to $5:    {wipe:4d} ({100*wipe/n:.1f}%)")
    print(f"  stuck (neither): {stuck:4d} ({100*stuck/n:.1f}%)")
    print(f"  bal p50/p90:   ${bals[n//2]:.2f} / ${bals[9*n//10]:.2f}")
    print(f"  max_dd p50/p90: ${dds[n//2]:.2f} / ${dds[9*n//10]:.2f}")
    if succ_mkts:
        print(f"  mkts to $100 (when success): p50={succ_mkts[len(succ_mkts)//2]} p90={succ_mkts[9*len(succ_mkts)//10]}")


if __name__ == "__main__":
    random.seed(42)
    markets_seq_data = load_markets()
    print(f"loaded {len(markets_seq_data)} markets")

    # Define configs to test
    configs = [
        ("A: Baseline (no M1)",
         {'pause_thresh': 7.0, 'halt_thresh': 5.0, 'low_tier_cap': 0,
          'm1_active': False, 'halve_low_tier': False}),

        ("B: + M1 active",
         {'pause_thresh': 7.0, 'halt_thresh': 5.0, 'low_tier_cap': 0,
          'm1_active': True, 'halve_low_tier': False}),

        ("C: + M1 + halve fire size at <$10",
         {'pause_thresh': 7.0, 'halt_thresh': 5.0, 'low_tier_cap': 0,
          'm1_active': True, 'halve_low_tier': True}),

        ("D: + M1 + lower PAUSE to $5 (1 fire at $5-$7)",
         {'pause_thresh': 5.0, 'halt_thresh': 5.0, 'low_tier_cap': 1,
          'm1_active': True, 'halve_low_tier': False}),

        ("E: + M1 + lower PAUSE to $5 + halve size",
         {'pause_thresh': 5.0, 'halt_thresh': 5.0, 'low_tier_cap': 1,
          'm1_active': True, 'halve_low_tier': True}),

        ("F: STRICT — M1 + only fire at $10+ (skip $5-$10)",
         {'pause_thresh': 10.0, 'halt_thresh': 5.0, 'low_tier_cap': 0,
          'm1_active': True, 'halve_low_tier': False}),
    ]

    for name, cfg in configs:
        results = run_config(markets_seq_data, cfg, n_runs=500, mkt_budget=300)
        summarize(name, results)

    print("\n=== INTERPRETATION ===")
    print("Best = highest % reach $100 AND lowest % wipe to $5.")
    print("Tradeoff: aggressive recovery (allow low-tier fires) helps reach $100 but risks wipe.")
