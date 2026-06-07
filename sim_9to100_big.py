#!/usr/bin/env python3
"""sim_9to100_big.py — Monte Carlo across 500 historical markets.

Parses race_test_*.log files from quant_bots_logs_replay/ and main folder.
Extracts per-market: winner + chronological fires (strategy, side, entry_price, won/lost).

Then runs bootstrap simulations with different ruin guard + fire size configs.
Reports % success ($100 reached), % wipe ($5 floor), median bal, etc.
"""
import os
import re
import json
import glob
import random
from collections import defaultdict


def parse_log(path):
    """Parse one race_test log. Returns {'winner': str, 'fires': [(strategy, side, entry_price, won_bool)]} or None."""
    try:
        with open(path) as f:
            text = f.read()
    except Exception:
        return None

    # Find winner
    m = re.search(r'MARKET RECAP.*\(winner=(\w+)\)', text)
    if not m:
        return None
    winner = m.group(1)
    if winner not in ('UP', 'DN'):
        return None

    # Find chronologically-ordered fires in RECAP block
    # Pattern: "  N. strategy_name  🔵 SHADOW|🟢 LIVE   SIDE @ $price"
    fires = []
    # Match fire lines in recap. Format:
    #   "HH:MM:SS  INFO          N. strategy_name      🔵 SHADOW UP @ $0.410 ...sh cd=NNN ..."
    # 2026-05-28: also capture cd to skip last-15s fires (unrealistic to execute)
    pattern = re.compile(
        r'\d+\.\s+(\S+)\s+(?:🔵 SHADOW|🟢 LIVE)\s+(UP|DN)\s+@\s+\$(\d+\.\d+)\s+[\d.]+sh\s+cd=(\d+)')
    MIN_CD_TO_EXECUTE = 15   # skip fires with cd <= 15 (too late to FOK reliably)
    for m in pattern.finditer(text):
        strategy = m.group(1)
        side = m.group(2)
        try:
            entry_price = float(m.group(3))
            cd = int(m.group(4))
        except Exception:
            continue
        if entry_price <= 0 or entry_price >= 1:
            continue
        if cd <= MIN_CD_TO_EXECUTE:
            continue   # skip — would have been impossible to execute in real time
        won = (side == winner)
        fires.append({
            'strategy': strategy,
            'side': side,
            'entry_price': entry_price,
            'cd': cd,
            'won': won,
        })
    if len(fires) < 1:
        return None
    return {'winner': winner, 'fires': fires}


def load_markets(max_markets=500, seed=42):
    """Load up to max_markets race_test logs."""
    paths = set()
    for pattern in [
        '/home/polybot/polymarket-bot/data/quant_bots_logs_replay/race_test_btc-updown-5m-*.log',
        '/home/polybot/polymarket-bot/data/race_test_btc-updown-5m-*.log',
    ]:
        for p in glob.glob(pattern):
            paths.add(p)

    random.seed(seed)
    paths = sorted(paths)
    if len(paths) > max_markets:
        paths = random.sample(paths, max_markets)

    markets = {}
    for p in paths:
        m = parse_log(p)
        if m:
            slug = os.path.basename(p).replace('race_test_btc-updown-5m-', '').replace('.log', '')
            markets[slug] = m

    return markets


def get_cap(bal, config):
    if bal < config.get('halt_thresh', 5.0):
        return 0
    if bal < config.get('pause_thresh', 7.0):
        return config.get('low_tier_cap', 0)
    if bal < 10:
        return 2 if config.get('force_cap2') else 1
    if bal < 20:
        return 2
    if bal < 50:
        return 3
    return 4


def get_fire_size(bal, config):
    if bal < 10:
        return config.get('low_tier_size', 1.00)
    return 1.00


def simulate_one(markets_data, slugs_seq, config, max_mkts=500):
    bal = 9.0
    peak = bal
    max_dd = 0.0
    fires_taken = 0
    wins = 0
    losses = 0
    mkts = 0
    allowed = config.get('allowed_strategies')  # None = all; set = filter

    for slug in slugs_seq[:max_mkts]:
        mkts += 1
        m = markets_data[slug]
        winner = m['winner']
        cap = get_cap(bal, config)
        if cap == 0:
            continue

        # Filter by allowed strategies if set
        eligible = m['fires']
        if allowed is not None:
            eligible = [f for f in m['fires'] if f['strategy'] in allowed]
        taken = eligible[:cap]  # take first `cap` chronologically of eligible
        size = get_fire_size(bal, config)

        for f in taken:
            fires_taken += 1
            if f['won']:
                wins += 1
                pnl = size * (1.0 / f['entry_price'] - 1)
            else:
                losses += 1
                pnl = -size
            bal += pnl
            if bal > peak:
                peak = bal
            dd = peak - bal
            if dd > max_dd:
                max_dd = dd
            if bal >= 100:
                return dict(success=True, wiped=False, bal=bal, mkts=mkts,
                            fires=fires_taken, wins=wins, losses=losses, max_dd=max_dd)
            if bal < 5:
                return dict(success=False, wiped=True, bal=bal, mkts=mkts,
                            fires=fires_taken, wins=wins, losses=losses, max_dd=max_dd)

    return dict(success=(bal >= 100), wiped=(bal < 5), bal=bal, mkts=mkts,
                fires=fires_taken, wins=wins, losses=losses, max_dd=max_dd)


def run_config(markets_data, config, n_runs=500, mkt_budget=600):
    all_slugs = list(markets_data.keys())
    results = []
    for i in range(n_runs):
        # Bootstrap WITH replacement
        seq = [random.choice(all_slugs) for _ in range(mkt_budget)]
        r = simulate_one(markets_data, seq, config, max_mkts=mkt_budget)
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
    print(f"\n=== {name} ({n} runs, {600} mkt budget each) ===")
    print(f"  reach $100:     {succ:4d} ({100*succ/n:5.1f}%)")
    print(f"  wipe to $5:     {wipe:4d} ({100*wipe/n:5.1f}%)")
    print(f"  stuck (neither):{stuck:4d} ({100*stuck/n:5.1f}%)")
    print(f"  bal p10/p50/p90/max: ${bals[n//10]:.2f} / ${bals[n//2]:.2f} / ${bals[9*n//10]:.2f} / ${bals[-1]:.2f}")
    print(f"  max_dd p50/p90:      ${dds[n//2]:.2f} / ${dds[9*n//10]:.2f}")
    if succ_mkts:
        print(f"  mkts to $100 (success runs): p50={succ_mkts[len(succ_mkts)//2]} p90={succ_mkts[9*len(succ_mkts)//10]}")


if __name__ == "__main__":
    print("Loading markets...")
    markets = load_markets(max_markets=500)
    print(f"loaded {len(markets)} markets with valid winners and fires")
    if not markets:
        print("ERROR: no markets loaded")
        exit(1)

    # Quick data overview
    winners = [m['winner'] for m in markets.values()]
    fires_per_mkt = [len(m['fires']) for m in markets.values()]
    print(f"\nwinner distribution: UP={winners.count('UP')} ({100*winners.count('UP')//len(winners)}%)  DN={winners.count('DN')} ({100*winners.count('DN')//len(winners)}%)")
    print(f"fires per market: min={min(fires_per_mkt)} p50={sorted(fires_per_mkt)[len(fires_per_mkt)//2]} max={max(fires_per_mkt)}")

    # Win rate of first fire
    first_fire_wins = sum(1 for m in markets.values() if m['fires'][0]['won'])
    print(f"first-fire win rate (BASELINE): {first_fire_wins}/{len(markets)} = {100*first_fire_wins/len(markets):.1f}%")

    # 2026-05-28: RANKED BY EV per fire (cd>15 only — exclude last-15s fires).
    # Filter sets prefer strategies with larger samples (n>=50) for reliable EV.
    #
    # Small-sample positives (n=20-49, EV $0.74-$0.80) excluded due to high variance.

    # Top by EV with n>=50 fires (statistically reliable)
    RELIABLE_TOP5 = {
        'deep_dip_filtered',          # n=53,  EV +$0.74
        'up_deep_spread_collapse',    # n=105, EV +$0.38
        'fake_train_detector',        # n=148, EV +$0.23
        'cusp',                       # n=149, EV +$0.19
        'up_deep_accumulation',       # n=88,  EV +$0.18
    }
    RELIABLE_TOP10 = RELIABLE_TOP5 | {
        'depth_surge',                # n=249, EV +$0.16
        't4_ext',                     # n=55,  EV +$0.14
        'early_up_collapse_dn',       # n=55,  EV +$0.08
        't6_early',                   # n=53,  EV +$0.07
        'deep_dip_scout',             # n=448, EV +$0.07
    }
    # All positive-EV with n>=100 fires (extra safety)
    BIG_SAMPLE_POSITIVE = {
        'up_deep_spread_collapse',    # n=105
        'fake_train_detector',        # n=148
        'cusp',                       # n=149
        'depth_surge',                # n=249
        'deep_dip_scout',             # n=448
        'depth_collapse_mid_v2',      # n=233, EV +$0.06
    }

    # Configs
    configs = [
        ("A: Baseline (current — all strategies allowed)",
         {'pause_thresh': 7.0, 'halt_thresh': 5.0, 'low_tier_cap': 0,
          'low_tier_size': 1.00}),

        ("R5: RELIABLE_TOP5 (n>=50, EV/fire) — current ruin guard",
         {'pause_thresh': 7.0, 'halt_thresh': 5.0, 'low_tier_cap': 0,
          'low_tier_size': 1.00, 'allowed_strategies': RELIABLE_TOP5}),

        ("R10: RELIABLE_TOP10 — current ruin guard",
         {'pause_thresh': 7.0, 'halt_thresh': 5.0, 'low_tier_cap': 0,
          'low_tier_size': 1.00, 'allowed_strategies': RELIABLE_TOP10}),

        ("R5 + lower PAUSE to $5 (full size)",
         {'pause_thresh': 5.0, 'halt_thresh': 5.0, 'low_tier_cap': 1,
          'low_tier_size': 1.00, 'allowed_strategies': RELIABLE_TOP5}),

        ("R5 + lower PAUSE to $5 + halve size",
         {'pause_thresh': 5.0, 'halt_thresh': 5.0, 'low_tier_cap': 1,
          'low_tier_size': 0.50, 'allowed_strategies': RELIABLE_TOP5}),

        ("R10 + lower PAUSE to $5 + halve size",
         {'pause_thresh': 5.0, 'halt_thresh': 5.0, 'low_tier_cap': 1,
          'low_tier_size': 0.50, 'allowed_strategies': RELIABLE_TOP10}),

        ("BIG_SAMPLE (n>=100, positive EV) + PAUSE $5 + halve size",
         {'pause_thresh': 5.0, 'halt_thresh': 5.0, 'low_tier_cap': 1,
          'low_tier_size': 0.50, 'allowed_strategies': BIG_SAMPLE_POSITIVE}),

        ("R5 + PAUSE $5 + QUARTER size (safest aggressive)",
         {'pause_thresh': 5.0, 'halt_thresh': 5.0, 'low_tier_cap': 1,
          'low_tier_size': 0.25, 'allowed_strategies': RELIABLE_TOP5}),

        ("R5 + cap=2 always (even at low tier) — fire twice in good markets",
         {'pause_thresh': 7.0, 'halt_thresh': 5.0, 'low_tier_cap': 0,
          'low_tier_size': 1.00, 'allowed_strategies': RELIABLE_TOP5,
          'force_cap2': True}),

        ("B: + halve fire size <$10",
         {'pause_thresh': 7.0, 'halt_thresh': 5.0, 'low_tier_cap': 0,
          'low_tier_size': 0.50}),

        ("C: + lower PAUSE to $5 (1 fire at $5-$10) full size",
         {'pause_thresh': 5.0, 'halt_thresh': 5.0, 'low_tier_cap': 1,
          'low_tier_size': 1.00}),

        ("D: + lower PAUSE to $5 + halve size",
         {'pause_thresh': 5.0, 'halt_thresh': 5.0, 'low_tier_cap': 1,
          'low_tier_size': 0.50}),

        ("E: + lower PAUSE to $5 + QUARTER size (smallest)",
         {'pause_thresh': 5.0, 'halt_thresh': 5.0, 'low_tier_cap': 1,
          'low_tier_size': 0.25}),

        ("F: PAUSE at $6 (smaller dead zone) + halve size",
         {'pause_thresh': 6.0, 'halt_thresh': 5.0, 'low_tier_cap': 1,
          'low_tier_size': 0.50}),
    ]

    random.seed(42)
    for name, cfg in configs:
        results = run_config(markets, cfg, n_runs=500, mkt_budget=600)
        summarize(name, results)

    print("\n=== READ THIS ===")
    print("Target: highest reach-$100 rate WITH lowest wipe rate.")
    print("Trade-off space:")
    print("  - Aggressive (lower PAUSE) = more reach AND more wipe")
    print("  - Conservative (no fires below $7) = ZERO wipe but stuck at low bal often")
    print("  - Halve/quarter fire size = safety knob (limits per-loss damage)")
