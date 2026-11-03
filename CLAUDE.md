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
- Stock names link to TradingView.
- Considered Chartink, decided to stay with TradingView.

## How to ask for changes
Give: page name, what's wrong or wanted, and a screenshot or symbol + date. Keep changes small.
