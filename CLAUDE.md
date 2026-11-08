# NIFTY Sector Strength — project notes

Owner: Vivek (GitHub `vs916491-maker`). Personal analysis only, not investment advice.
Repo: `vs916491-maker/Nifty-sector-strength` (public). Site: GitHub Pages, signs in with the F&O Desk email + password.

## What it is
Daily sector-rotation website for positional cash trades (held weeks to months). Ranks sectoral and thematic indices by relative strength and drills into the strongest stocks in leading sectors. Long ideas only.

## Pages
- **Overview** – Nifty 500 (default) / Nifty 50 toggle; Sectoral and Thematic tabs (15 + 13 indices); Relative Rotation Graph (RRG, "option D" style, dotted leader lines for labels); ranking table; market breadth; focus sectors with top stocks; **regime light**, **internals gauge**, seller-exhaustion and distribution trackers; Rotation watch.
- **Sector page** (`#/sector/IT`) – price + averages, RS, score history, breadth, member stocks.
- **Stock picks** (`#/picks`) – picks from focus sectors, F&O filter, positional setups (breakout, tight base, pullback to 50-DMA), Next leaders, position sizing.
- **Track record** (`#/record`) – did top-ranked sectors, picks, setups and the regime light actually work.
- **Watchlist** (`#/watch`) – Supabase table `fd_watchlist`, shared with the Fundamentals Desk (the F&O Desk has its own separate watchlist).
- **My Trades** (`#/trades`) – private cash-trade log (Supabase `cash_trades`).
- **Run scan** button (red) – intraday provisional rescan using live NSE prices.

## Scoring (details at top of `analysis/sectors.py`, `analysis/stocks.py`)
- Sector score: RS trend 30%, RS momentum 20%, excess return 20%, trend 20%, breadth 10%.
- Stock score: RS rating 35%, trend 25%, near 52-week high 15%, recent RS 15%, accumulation 10%.
- Picks: up to 5 per focus sector, mcap ≥ ₹500 cr, 20-day traded value ≥ ₹5 cr, score ≥ 60.
- Setups: RS rating 70+, stop at swing low (max 8%), exit on close below 50-DMA or 120 sessions.
- Caution (added 6 Nov 2026; Rotation watch column + chip under Quadrant in the ranking): **Stretched** = leader (RS-Ratio ≥ 100) > 8% above 50-DMA, or 2 of 3 (RSI 70+, > 8% above 50-DMA, breadth down 15+ pts in 20 sessions while within 2% of 20-day high). **Oversold** = laggard (RS-Ratio < 100) > 8% below 50-DMA, or RSI < 30 in last 5 sessions and now rising. Backtest Oct 2024–Nov 2026, next 10 sessions: Stretched −0.5% (46% up), Oversold +1.4% (55% up). "RS rolling over" signals tested and rejected (no edge). Rules in `analysis/sectors.py` (`CAUTION`, `caution()`). Not on Track record yet (his choice).

## Main files
- `collector/` – downloads NSE end-of-day files into `data/` (indices, stocks, constituents, corporate actions)
- `analysis/build.py` – runs all scoring; `regime.py`, `turning.py`, `setups.py`, `leaders.py`, `validate.py`
- `analysis/publish.py` – uploads outputs to Supabase `docs` table (keys `ss_<filename>`). `site/data/` is no longer published.
- `data/meta/manual_adjustments.csv` – hand-entered demerger factors (check `price_jump_check` in `status.json`)
- `site/` – plain HTML/CSS/JS, no build step

## How it runs
- Workflow `update-data.yml` (Daily data update) – weekday evenings. Started on time by Supabase pg_cron (`sector-eod-1` ~19:20 IST, `sector-eod-2` ~22:20 IST); GitHub cron at 19:17 / 22:17 IST is backup.
- Intraday "Run scan" and cash-trade checks run from the **fno-desk** repo (`sector-intraday.yml`, `cash-trades.yml`).
- Shared Supabase project, token and scheduling pattern: see F&O Desk notes.
- Secrets: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`.

## Rules / decisions to keep
- Data: free NSE files only (Yahoo as fallback). Raw prices stored; splits/bonuses applied at analysis time.
- My Trades: totals at the top cover the current financial year only (Apr–Mar, by sell date) and start fresh each 1 April; completed years show in "Year by year". Closed trades are locked: no editing and no Delete button (open trades can still be deleted). Exception (5 Nov 2026): a trade sold by hand can be edited (sell price/date/qty) or reopened until the next weekday 19:40 IST check (`closed_at` + `trade_fix_until`, fno-desk `supabase/011_fix_closed_trades.sql`); trades closed by the job lock at once.
- Seller exhaustion / trend continuation (8 Nov 2026, `analysis/turning.py`, both benchmarks): **Confirmed counts once per cycle** (`_cycle()`): the first day marks the date, later days are not new signals, and it re-arms only at the next Washout (before, "met today" showed on every day the reading held, and flickered). While Distribution stage 1 (Extended) is on, the Seller exhaustion badge shows "No signal" (`bottom_no_signal`) and keeps the last confirmation date. New **Trend continuation** box (`continuation()`), active from the confirmation until the next Washout: Up = 3 of 4 (index above 20-day and 50-day average, 50%+ of stocks above 50-day, internals gauge above 0); Down = index closes below the earlier low (lowest close in the 40 sessions up to the confirmation) or only 1 of 4 holds; else Watching. Track record stage events use the once-per-cycle Confirmed.
- Regime light lift (8 Nov 2026, both Nifty 500 and Nifty 50; `regime.adjust_light()`, constants `LIFT_*`): after a confirmed bottom, while trend continuation is not Down, a Red light shows Amber once 4+ of 6 checks pass (stays Amber while 3+ pass). Never lifts to Green. `light_checks` keeps the checks-only light; a note appears under the guidance line. Reason: the 5-session average + buffer kept the light Red for days after a confirmed bottom with 5 of 6 checks passing (Nifty 50, 5 Nov 2026: avg 2.8, needs 3.5). Backtest: fires on only 6 (Nifty 500) / 8 (Nifty 50) days in 15 months.
- Distribution "Extended" cap on the light (`EXTENDED_CAP`, built but **off**): would show Amber instead of Green while Extended is on. Off because Extended is on for ~44% (Nifty 500) / ~71% (Nifty 50) of Green days, and those days' next-21-session return was not worse than other Green days (+0.5% vs -0.8%; +0.3% vs -1.5%). Awaiting Vivek's decision.
- Stock names link to TradingView.
- Considered Chartink, decided to stay with TradingView.

## How to ask for changes
Give: page name, what's wrong or wanted, and a screenshot or symbol + date. Keep changes small.
