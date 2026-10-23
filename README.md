# NIFTY Sector Strength

A daily-updated website that ranks NIFTY sectoral indices by relative strength
against NIFTY 50 (swing / positional view) and drills into the strongest stocks
inside the leading sectors.

- **Runs on:** GitHub Actions, once a day after market close
- **Shown on:** GitHub Pages (static site that opens on any device)
- **Data:** free end-of-day files from NSE (Yahoo Finance as fallback)

## Build phases

| Phase | What | Status |
|---|---|---|
| 1 | Data source feasibility test | Done - NSE archive files work from GitHub Actions |
| 2 | Data collector + 2-year backfill | Done - Oct 2024 onwards, updated every weekday evening |
| 3 | Sector scoring + Relative Rotation Graph (RRG) | Pending |
| 4 | Stock drill-down inside leading sectors | Pending |
| 5 | Website + daily schedule | Pending |
| 6 | Validation (did top-ranked sectors outperform?) | Pending |

## Data (Phase 2)

`collector/` downloads NSE's free end-of-day files every weekday evening
(GitHub Actions, *Daily data update*) and commits them under `data/`:

| Path | Contents |
|---|---|
| `data/indices/YYYY-MM.csv` | Daily OHLC, P/E, P/B, dividend yield for every NSE index |
| `data/stocks/YYYY-MM.csv` | Daily OHLC, previous close, volume, delivery % for EQ/BE stocks |
| `data/constituents/KEY.csv` | Current constituents of each tracked index |
| `data/meta/fno_symbols.csv` | Stocks with F&O contracts |
| `data/meta/corporate_actions.csv` | NSE split / bonus events with their price factor |
| `data/meta/manual_adjustments.csv` | Hand-entered price factors (demergers) |
| `data/meta/status.json` | What the last update fetched, and any problems |

Stored prices are raw NSE prices. Splits, bonuses and demergers are applied
at analysis time from the two adjustment files. Each update also lists big
overnight drops that no adjustment explains (`price_jump_check` in
`status.json`) so new demergers can be added to `manual_adjustments.csv`.

Tracked indices are listed in `collector/config.py`. Run locally with
`pip install -r requirements.txt` then `python -m collector.update`.

## Phase 1: data source test

`scripts/probe_sources.py` checks which free sources can be downloaded from
GitHub's servers. It runs automatically on push, or manually from
**Actions → Phase 1 - Data source test → Run workflow**. The results table
appears on the run's summary page.

*For personal analysis only. Not investment advice.*
