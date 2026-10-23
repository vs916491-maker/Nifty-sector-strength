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
| 1 | Data source feasibility test | In progress |
| 2 | Data collector + ~1.5 year backfill | Pending |
| 3 | Sector scoring + Relative Rotation Graph (RRG) | Pending |
| 4 | Stock drill-down inside leading sectors | Pending |
| 5 | Website + daily schedule | Pending |
| 6 | Validation (did top-ranked sectors outperform?) | Pending |

## Phase 1: data source test

`scripts/probe_sources.py` checks which free sources can be downloaded from
GitHub's servers. It runs automatically on push, or manually from
**Actions → Phase 1 - Data source test → Run workflow**. The results table
appears on the run's summary page.

*For personal analysis only. Not investment advice.*
