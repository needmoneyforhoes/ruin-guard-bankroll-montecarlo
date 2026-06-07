# ruin-guard-bankroll-montecarlo

Ruin-guard bankroll-growth Monte Carlo for Polymarket ($9 → $100): cap-by-bankroll, floor tuning, and 0%-wipe targeting.

## Why it exists

The live trading bot starts from a tiny bankroll ($9) and needs a staking policy that compounds toward $100 without ever wiping out below a hard floor. These scripts answer one question offline: *given the bot's actual historical fires, which ruin-guard configuration (per-bankroll fire cap, fire size, PAUSE/HALT thresholds, strategy whitelist) maximizes the reach-$100 rate while minimizing the wipe rate?* They are research harnesses, not the live bot.

## How it works

Each script replays the bot's recorded per-market fires, bootstrap-resamples thousands of $9→$100 paths (markets sampled *with* replacement), applies a candidate ruin-guard policy, and prints reach-$100 %, wipe %, balance percentiles, max drawdown, and markets-to-$100. The scripts are an iterative progression — each fixes a flaw found in the previous one:

| Script | Focus |
|---|---|
| `sim_9to100_big.py` | Broadest sweep. Parses 500 `race_test_*.log` files; compares 14 configs of PAUSE/HALT thresholds, low-tier cap/size, and EV-ranked strategy whitelists (`RELIABLE_TOP5/10`, `BIG_SAMPLE_POSITIVE`). |
| `sim_9to100_monte_carlo.py` | Tests the **M1 winner-ML veto** overlay. Sources fires (incl. per-fire M1 BLOCK decisions) from `shadow_predictor_log.jsonl`. |
| `sim_aggressive_no_halt.py` | No PAUSE/HALT — fire every signal. Adds DN-streak skip-UP gate and a stochastic M1 block model. Sweeps flat / staircase / Kelly-lite sizing. |
| `sim_no_stuck.py` | Fixes the "stuck at $5–$7" dead zone via **floor-aware sizing** (`fire = min(kelly, (bal − floor)·buffer)`), making a wipe mathematically impossible while still allowing recovery. |
| `sim_faster.py` | Pushes throughput ($/market) under the 0%-wipe constraint: ramps Kelly %, per-market cap, strategy-pool breadth, and the safety buffer. |
| `sim_final.py` | Fastest 0%-wipe config using only bot-gate-validated edges (`LIVE_POSITIVE`) ∪ permutation-significant edges (`PERM_SIGNIFICANT`); reports markets-to-$100 and est. days. |

All sims share the same core: regex-parse `MARKET RECAP (winner=…)` blocks and fire lines (`N. strategy 🟢 LIVE UP @ $0.41 …sh cd=NNN`), skip fires with `cd ≤ 15` (too late to execute in real time), then compute PnL as `size·(1/entry − 1)` on a win, `−size` on a loss.

## Requirements

- **Python 3.8+**, standard library only (`re`, `glob`, `json`, `random`, `collections`). No third-party packages, no virtualenv required.
- **No wallet, keys, or network.** These are pure offline simulators — they never touch a CLOB client or sign transactions.
- **Historical fire logs** (see Data). Without them the scripts load 0 markets and exit.

## Usage

Run any script directly; each is self-contained and prints a comparison table to stdout.

```bash
python3 sim_9to100_big.py            # broad config sweep (start here)
python3 sim_final.py                 # fastest validated 0%-wipe config
python3 sim_no_stuck.py              # floor-aware sizing, no dead zone
python3 sim_faster.py                # $/market throughput sweep
python3 sim_aggressive_no_halt.py    # no-guard, accept wipe risk
python3 sim_9to100_monte_carlo.py    # M1 winner-ML veto overlay
```

Tune policies by editing the strategy sets and the `configs` / `cfgs` lists near each `main()` / `__main__`.

## Data

These scripts read the bot's recorded outputs from the private **polymarket-data** repo, hard-coded under `/home/polybot/polymarket-bot/data/`:

- `quant_bots_logs_replay/race_test_btc-updown-5m-*.log` (and the top-level copies) — replayed by 5 of the 6 scripts.
- `shadow_predictor_log.jsonl` — used only by `sim_9to100_monte_carlo.py`.

Point the `PATH_PATTERN` / `SHADOW_LOG` constants at your local copy of polymarket-data if your layout differs.

> Private research software. No warranty; trades/handles real funds at your own risk.
