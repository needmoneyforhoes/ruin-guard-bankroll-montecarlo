# ruin-guard-bankroll-montecarlo

Offline Monte Carlo simulators that tune a $9 to $100 ruin-guard staking policy from the Polymarket bot's recorded fires.

Each script replays recorded per-market fires, bootstrap-resamples thousands of $9 to $100 paths (markets drawn with replacement), applies a candidate policy (per-bankroll fire cap, fire size, PAUSE/HALT thresholds, strategy whitelist), and prints reach-$100 %, wipe %, balance percentiles, max drawdown, and markets-to-$100. Research harnesses, not the live bot.

Shared core: regex-parse `MARKET RECAP (winner=...)` blocks and fire lines, skip fires with `cd <= 15` (too late to execute), then score PnL as `size*(1/entry - 1)` on a win and `-size` on a loss.

## Scripts

- `sim_9to100_big.py`: broad sweep. Parses up to 500 `race_test_*.log` files, compares 14 configs of PAUSE/HALT thresholds, low-tier cap/size, and EV-ranked whitelists (`RELIABLE_TOP5/10`, `BIG_SAMPLE_POSITIVE`). Start here.
- `sim_9to100_monte_carlo.py`: adds the M1 winner-ML veto overlay. Sources fires and per-fire M1 BLOCK decisions from `shadow_predictor_log.jsonl`.
- `sim_aggressive_no_halt.py`: no PAUSE/HALT, fires every signal. Adds a DN-streak skip-UP gate and a stochastic M1 block model. Sweeps flat / staircase / Kelly-lite sizing.
- `sim_no_stuck.py`: floor-aware sizing (`fire = min(kelly, (bal - floor)*buffer)`) to remove the $5 to $7 dead zone and make a wipe impossible while still allowing recovery.
- `sim_faster.py`: pushes $/market throughput under the 0%-wipe constraint by ramping Kelly %, per-market cap, pool breadth, and safety buffer.
- `sim_final.py`: fastest 0%-wipe config using bot-gate-validated edges (`LIVE_POSITIVE`) plus permutation-significant edges (`PERM_SIGNIFICANT`). Reports markets-to-$100 and est. days.

## Usage

Python 3.8+, standard library only. Each script is self-contained and prints a comparison table to stdout.

```bash
python3 sim_9to100_big.py
python3 sim_final.py
python3 sim_no_stuck.py
python3 sim_faster.py
python3 sim_aggressive_no_halt.py
python3 sim_9to100_monte_carlo.py
```

Tune policies by editing the strategy sets and the `configs` / `cfgs` lists near each `main()`.

## Data

Reads recorded outputs from the private polymarket-data repo. Without the logs the scripts load 0 markets and exit.

- `$DATA_DIR/quant_bots_logs_replay/race_test_btc-updown-5m-*.log`: replayed by 5 of the 6 scripts.
- `$DATA_DIR/shadow_predictor_log.jsonl`: used only by `sim_9to100_monte_carlo.py`.

Repoint the `PATH_PATTERN` / `SHADOW_LOG` constants if your layout differs. Pure offline; no wallet, keys, or network.

Models real-money staking. Validate any policy before trusting it live.
