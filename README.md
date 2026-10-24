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
| 3 | Sector scoring + Relative Rotation Graph (RRG) | Done - `analysis/`, outputs in `site/data/` |
| 4 | Stock drill-down inside leading sectors | Done - `analysis/stocks.py`, output `site/data/stocks.json` |
| 5 | Website + daily schedule | Done - `site/`, published to GitHub Pages after every update |
| 6 | Validation (did top-ranked sectors outperform?) | Done - `analysis/validate.py`, *Track record* page |
| 7 | Market regime light + positional setups | Done - `analysis/regime.py`, `analysis/setups.py` |
| 8 | Next leaders + sector rotation in corrections | Done - `analysis/leaders.py` |
| 9 | My Trades (private cash-trade log) | Done - `site/app.js` (#/trades), checker in the fno-desk repo |

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

## Sector scoring (Phase 3)

`python -m analysis.build` (run after every data update) scores the 15
sectoral and 13 thematic indices against **Nifty 500** (default) and
**Nifty 50**, and writes `site/data/sectors.json` and
`site/data/sector_history.json` for the website. Method and weights are
documented at the top of `analysis/sectors.py`:

| Component | Weight | What it measures |
|---|---|---|
| RS trend | 30% | Relative strength vs its 50-day average, its 150-day average, and whether the 50-day average is rising |
| RS momentum | 20% | 10-day change in relative strength, and whether the gap to its 50-day average is widening |
| Excess return | 20% | 1-month and 3-month return minus the benchmark's |
| Trend | 20% | Price above 50/150/200-day averages, 50 above 200, 50 rising |
| Breadth | 10% | % of the sector's stocks above their own 50-day average |

Ranked parts are percentile ranks within the same tab (sectoral or
thematic). The Relative Rotation Graph uses weekly data: RS-Ratio = relative
strength vs its 10-week average (x100), RS-Momentum = its week-on-week change
(x100).

## Stock drill-down (Phase 4)

**Focus sectors** (per tab and benchmark): every sector in the Leading or
Improving RRG quadrant, plus the top 5 by score.

**Universe:** Nifty Total Market (~750 largest stocks) plus all tracked index
constituents. Sectoral indices with a clear NSE industry (Auto, Financial
Services, FMCG, Healthcare, IT, Media, Metal, Realty, Consumer Durables,
Oil & Gas, Chemicals) also include every other Total Market stock of that
industry. Bank, Private Bank, PSU Bank, Pharma and all thematic indices use
their official constituents only.

| Stock score component | Weight | What it measures |
|---|---|---|
| RS rating | 35% | Weighted 3/6/9/12-month return, ranked across the universe (1-99) |
| Trend | 25% | Above 50/150/200-day averages, 50 above 200, 200 rising |
| Near 52-week high | 15% | 100 at the high, 0 at 25% or more below |
| Recent RS | 15% | 1-month return, ranked across the universe |
| Accumulation | 10% | Up-day vs down-day volume (50 days), rising delivery % |

**Picks:** up to 5 per focus sector, with market cap >= Rs 500 cr (NSE daily
market-cap file), 20-day traded value >= Rs 5 cr, 6+ months of history and
score >= 60. Flags: F&O, Extended (>25% above 50-DMA or RSI > 78), New listing.

## Website (Phase 5)

A static site in `site/` (plain HTML, CSS and JavaScript, no build step) that
reads the JSON in `site/data/`. The *Publish website* workflow deploys it to
GitHub Pages whenever the site changes and after every *Daily data update*.

- **Overview:** Nifty 500 / Nifty 50 toggle, Sectoral / Thematic tabs,
  Relative Rotation Graph, ranking table, market breadth (advance/decline
  line, net advances, % of Nifty 500 above 50/200-day averages, 52-week
  highs and lows) and the focus sectors with their top stocks.
- **Sector page** (`#/sector/IT`): price with averages, relative strength,
  score history, breadth, score breakdown and every member stock.
- **Stock picks** (`#/picks`): all picks from the focus sectors, sortable,
  with an F&O-only filter.

Preview locally: `cd site && python -m http.server`, then open
http://localhost:8000.

## Market regime, setups and track record (Phases 6-7)

- **Regime light** (`analysis/regime.py`, Overview): six checks on Nifty 500's
  trend and breadth, averaged over 5 sessions with a buffer (Green at 5+,
  leaves Green below 4; Red below 2.5, leaves Red at 3.5+) so it doesn't
  flip back and forth. **Market internals gauge** (-100..+100: A/D line vs
  its 50-day average, breadth trend, RSI of Nifty 500 Equal Weight vs its
  average, highs minus lows, equal weight vs cap weight) with topping and
  bottoming early warnings. **Turning-point trackers** (`analysis/turning.py`):
  seller exhaustion (washout -> positive divergence -> confirmation) and
  distribution (extended -> negative divergence / heavy-volume down days ->
  breakdown), each stage with its conditions and a track record. The whole
  regime panel also runs for Nifty 50 (breadth, highs/lows and advances/
  declines from its 50 stocks) and follows the Nifty 500 / Nifty 50 switch. Washout (<20% of stocks
  above their 50-day average) and breadth thrust (<20% to >50% within 15
  sessions) are flagged separately.
- **Positional setups** (`analysis/setups.py`, Stock picks): breakout, tight
  base and pullback to the 50-day average, for stocks in a long-term uptrend
  with RS rating 70+. Stop at the recent swing low (max 8%), exit on the first
  close below the 50-day average or after 120 sessions. Grade A = RS rating
  90+ or RS line at a 52-week high. Position size from capital, risk per
  trade and a max-per-stock cap (saved in the browser).
- **Next leaders and Rotation watch** (`analysis/leaders.py`, Stock picks and
  Overview): during the market's latest decline (6-month high to the low
  since), stocks and sectors are ranked on how little they fell, how they
  have done since the low, their RS line vs its 52-week high, and (stocks)
  accumulation. Sectors get a status: Emerging, Steady leader, Old leader
  bouncing, Fading leader. Past corrections are tested on the Track record.
- **Track record** (`analysis/validate.py`, `site/data/validation.json`):
  forward returns of sector ranks, stock score bands, the picks, every
  historical setup, and the regime light, rebuilt every evening.

## Private access

The whole website signs in with the F&O Desk email and password. Its data is
uploaded after every daily update (`analysis/publish.py`) to the private
Supabase `docs` table (keys `ss_sectors`, `ss_stocks`, ...), readable only by
that email; `site/data/` is no longer committed or published. Needs the
repository secrets `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` (same values as
the fno-desk repo). The raw NSE files in `data/` stay in this public repo.

## My Trades (Phase 9)

`#/trades` is a private log of cash-market positional trades, stored in the
same Supabase database as the F&O Desk (table `cash_trades`, created by
`fno-desk/supabase/003_cash_trades.sql`; only the owner's email can read or
write it). Sign in with the F&O Desk email and password. "I took this trade"
on a setup in Stock picks pre-fills the buy price, stop, quantity and setup.

Every weekday evening the fno-desk workflow *Cash trades check* updates each
open trade's last close, 50-day average and sessions held, and closes it by
its exit rule: setup rules (stop, target, first close below the 50-day
average, 120 sessions), stop/target only, or manual. P&L = (sell - buy) x
quantity - charges (0.25% of the buy value if no charges are entered).

## Phase 1: data source test

`scripts/probe_sources.py` checks which free sources can be downloaded from
GitHub's servers. It runs automatically on push, or manually from
**Actions → Phase 1 - Data source test → Run workflow**. The results table
appears on the run's summary page.

*For personal analysis only. Not investment advice.*
