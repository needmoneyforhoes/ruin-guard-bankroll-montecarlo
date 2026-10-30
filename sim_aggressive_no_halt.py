#!/usr/bin/env python3
"""sim_aggressive_no_halt.py — fire every signal, no PAUSE/HALT protection.
User accepts wipe risk for faster growth."""
import re, glob, random
from collections import defaultdict

PATH = 'data/quant_bots_logs_replay/race_test_btc-updown-5m-*.log'
MIN_CD = 15
M1_BL = 0.58
M1_BW = 0.23


def load():
    pat = re.compile(r'(\d+)\.\s+(\S+)\s+(?:🔵 SHADOW|🟢 LIVE)\s+(UP|DN)\s+@\s+\$(\d+\.\d+)\s+[\d.]+sh\s+cd=(\d+)')
    wp = re.compile(r'MARKET RECAP.*\(winner=(\w+)\)')
    paths = sorted(set(glob.glob(PATH))); random.seed(42)
    if len(paths) > 500: paths = random.sample(paths, 500)
    M = {}
    for p in paths:
        try: t = open(p).read()
        except: continue
        m = wp.search(t)
        if not m: continue
        w = m.group(1)
        if w not in ('UP','DN'): continue
        slug = p.split('-')[-1].replace('.log','')
        fires = []
        for fm in pat.finditer(t):
            try:
                s = fm.group(2); sd = fm.group(3); pr = float(fm.group(4)); cd = int(fm.group(5))
            except: continue
            if pr<=0 or pr>=1 or cd<=MIN_CD: continue
            fires.append({'strategy':s,'side':sd,'price':pr,'won':(sd==w)})
        if fires: M[slug] = {'winner':w, 'fires':fires}
    return M


def compute_ev(M, me=0.50):
    by = defaultdict(list)
    for m in M.values():
        for f in m['fires']:
            if f['price'] <= me: by[f['strategy']].append((f['price'],f['won']))
    return set(s for s,it in by.items() if len(it)>=20 and sum((1/p-1) if w else -1.0 for p,w in it)/len(it) > 0)


def sim_run(M, seq, allowed, start, target, stage_fn, me, max_m=2000, rng=None):
    """stage_fn(bal) -> (fire_size, cap)"""
    if rng is None: rng = random
    bal = start; mkts = 0; rec = []
    for slug in seq[:max_m]:
        mkts += 1
        if bal >= target: return ('win', mkts, bal)
        if bal <= 0: return ('wipe', mkts, bal)
        fs, cap = stage_fn(bal)
        if bal < fs: return ('wipe', mkts, bal)  # can't afford min fire
        m = M[slug]; w = m['winner']
        dn6 = sum(1 for x in rec[-6:] if x=='DN')
        skip_up = dn6 >= 4
        elig = [f for f in m['fires'] if f['strategy'] in allowed and f['price']<=me and (not skip_up or f['side']!='UP')]
        if not elig: rec.append(w); continue
        elig.sort(key=lambda f: f['price'])
        c = 0
        for f in elig:
            if c >= cap: break
            p_blk = M1_BL if not f['won'] else M1_BW
            if rng.random() < p_blk: continue
            if bal - fs <= 0: break  # last $1, can't fire
            c += 1
            if f['won']: bal += fs * (1.0/f['price'] - 1)
            else: bal -= fs
            if bal >= target: return ('win', mkts, bal)
            if bal <= 0: return ('wipe', mkts, bal)
        rec.append(w)
    return ('stuck', mkts, bal)


def run_cfg(M, allowed, name, start, target, stage_fn, me=0.50, n=2000):
    slugs = list(M.keys()); rng = random.Random(42); res = []
    for _ in range(n):
        sq = [rng.choice(slugs) for _ in range(2000)]
        res.append(sim_run(M, sq, allowed, start, target, stage_fn, me, 2000, rng))
    n_ = len(res)
    won = sum(1 for r,_,_ in res if r=='win')
    wip = sum(1 for r,_,_ in res if r=='wipe')
    stk = sum(1 for r,_,_ in res if r=='stuck')
    wm = sorted([m for r,m,_ in res if r=='win'])
    p50 = wm[len(wm)//2] if wm else 0
    p25 = wm[len(wm)//4] if wm else 0
    p90 = wm[9*len(wm)//10] if wm else 0
    final_avg = sum(b for _,_,b in res)/n_
    mk = '⭐' if won/n_>=0.95 else ('🟢' if won/n_>=0.80 else ('🟡' if won/n_>=0.60 else '  '))
    print(f"  {mk}{name:50s} win={100*won/n_:5.1f}% WIPE={100*wip/n_:5.1f}% stuck={100*stk/n_:4.1f}% p25/50/90={p25}/{p50}/{p90} avg_final=${final_avg:.1f}")


def main():
    M = load()
    A = compute_ev(M, 0.50)
    print(f"Loaded {len(M)} mkts, {len(A)} pos-EV cheap strategies")
    print("Going $9 → $100 end-to-end (no stages between). Fire $1+ per signal, no HALT/PAUSE.\n")

    # Try several aggression levels — end-to-end $9 → $100
    print("=" * 100)
    print("END-TO-END $9 → $100 (no stage gating, no PAUSE)")
    print("=" * 100)

    def fn_flat_1_1(b): return (1.00, 1)
    def fn_flat_1_2(b): return (1.00, 2)
    def fn_flat_1_3(b): return (1.00, 3)
    def fn_stair_low(b):  # gentle scaling
        if b < 20: return (1.00, 2)
        if b < 30: return (1.00, 3)
        if b < 50: return (1.50, 3)
        return (2.00, 3)
    def fn_stair_aggressive(b):
        if b < 20: return (1.00, 3)
        if b < 30: return (1.50, 3)
        if b < 50: return (2.00, 3)
        return (3.00, 4)
    def fn_kelly_lite(b):  # scale w/ bankroll
        fs = max(1.00, b * 0.05)  # 5% per fire, min $1
        cap = 2 if b < 30 else 3
        return (round(fs, 2), cap)

    cfgs = [
        ("flat $1×1 (1 fire/mkt)", fn_flat_1_1),
        ("flat $1×2 (2 fires/mkt)", fn_flat_1_2),
        ("flat $1×3 (3 fires/mkt)", fn_flat_1_3),
        ("staircase gentle ($1→$2)", fn_stair_low),
        ("staircase aggressive ($1→$3)", fn_stair_aggressive),
        ("5%-of-bal (kelly-lite, min $1)", fn_kelly_lite),
    ]
    for name, fn in cfgs:
        run_cfg(M, A, name, 9.0, 100.0, fn)


if __name__ == "__main__":
    main()
