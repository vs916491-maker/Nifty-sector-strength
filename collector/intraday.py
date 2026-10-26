"""Intraday (provisional) refresh of the website during market hours.

The normal update runs every evening on NSE's final end-of-day files. This
script lets the website be refreshed on demand during the day (the "Run scan"
button): it takes live prices from NSE, adds them as a provisional row for
today to the stored data in this (temporary) checkout, rebuilds everything
and uploads it to the private database. Nothing is committed: the evening
update replaces it with the final numbers.

Live data
  indices    /api/allIndices - last price of every NSE index
  stocks     /api/equity-stockIndices?index=NIFTY TOTAL MARKET (+ NIFTY 500)
             - open, high, low, last price and volume so far
  volume     scaled up to a full day (x 375 / minutes traded) so volume
             tests (breakouts, accumulation) compare like with like
  A/D        advances and declines of those stocks, scaled to the size of the
             whole NSE list (the evening file counts every NSE stock)
  delivery % not available intraday (left empty)

Run:  python -m collector.intraday [--probe] [--force]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.parse
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from .nse import NSEClient

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SITE = ROOT / "site" / "data"
API_ALL = "https://www.nseindia.com/api/allIndices"
API_IDX = "https://www.nseindia.com/api/equity-stockIndices?index={}"
STOCK_LISTS = ["NIFTY TOTAL MARKET", "NIFTY 500"]
MARKET_MINUTES = 375


def norm(name: str) -> str:
    return "".join(str(name).lower().split())


def get_json(client: NSEClient, url: str):
    text = client.get_text(url)
    return json.loads(text) if text else None


def num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return float("nan")


def probe(client: NSEClient) -> None:
    a = get_json(client, API_ALL) or {}
    rows = a.get("data", [])
    print(f"::notice title=allIndices::{len(rows)} rows; keys {sorted(rows[0].keys()) if rows else None}; "
          f"sample {rows[0] if rows else None}"[:1800])
    for name in STOCK_LISTS:
        j = get_json(client, API_IDX.format(urllib.parse.quote(name))) or {}
        d = j.get("data", [])
        print(f"::notice title={name}::{len(d)} rows; advance {j.get('advance')}; keys {sorted(d[1].keys()) if len(d) > 1 else None}; "
              f"sample {d[1] if len(d) > 1 else None}"[:1800])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--force", action="store_true", help="run outside market hours (testing)")
    args = ap.parse_args()
    client = NSEClient()
    if args.probe:
        probe(client)
        return 0

    now = dt.datetime.now(IST)
    today = now.date()
    hhmm = now.strftime("%H:%M")
    if not args.force and (now.weekday() >= 5 or not ("09:15" <= hhmm <= "15:45")):
        print(f"::notice title=Intraday scan::Market is closed ({now:%a %H:%M} IST). "
              "The evening update provides the final end-of-day data.")
        return 0

    # ------------------------------------------------------------- indices
    alli = (get_json(client, API_ALL) or {}).get("data", [])
    month_file = DATA / "indices" / f"{today:%Y-%m}.csv"
    stored = sorted((DATA / "indices").glob("*.csv"))
    known = pd.read_csv(stored[-1], usecols=["index"])["index"].unique() if stored else []
    names = {norm(n): n for n in known}
    idx_rows = []
    for r in alli:
        name = names.get(norm(r.get("index", "")))
        if not name:
            continue
        idx_rows.append({"date": today.isoformat(), "index": name, "open": num(r.get("open")),
                         "high": num(r.get("high")), "low": num(r.get("low")), "close": num(r.get("last")),
                         "pe": num(r.get("pe")), "pb": num(r.get("pb")), "div_yield": num(r.get("dy")),
                         "turnover_cr": float("nan")})
    if len(idx_rows) < 20:
        print(f"::error::Only {len(idx_rows)} indices matched from NSE's live feed; stopping.")
        return 1

    # ------------------------------------------------------------- stocks
    minutes = max(5, min(MARKET_MINUTES, (now - now.replace(hour=9, minute=15, second=0, microsecond=0)).seconds // 60))
    scale = MARKET_MINUTES / minutes
    stocks: dict[str, dict] = {}
    adv = dec = unch = 0
    for name in STOCK_LISTS:
        j = get_json(client, API_IDX.format(urllib.parse.quote(name))) or {}
        for r in j.get("data", []):
            sym = str(r.get("symbol", "")).strip()
            if not sym or sym.upper() == name.replace(" ", "").upper() or r.get("priority") == 1:
                continue                               # the index's own summary row
            if sym in stocks:
                continue
            last, prev = num(r.get("lastPrice")), num(r.get("previousClose"))
            stocks[sym] = {"date": today.isoformat(), "symbol": sym, "series": "EQ", "prev_close": prev,
                           "open": num(r.get("open")), "high": num(r.get("dayHigh")), "low": num(r.get("dayLow")),
                           "close": last, "volume": round(num(r.get("totalTradedVolume")) * scale),
                           "deliv_pct": float("nan")}
            if last > prev:
                adv += 1
            elif last < prev:
                dec += 1
            else:
                unch += 1
    if len(stocks) < 300:
        print(f"::error::Only {len(stocks)} stocks from NSE's live feed; stopping.")
        return 1

    # ------------------------------------------------------------- write provisional rows (not committed)
    def append(path: Path, rows: list[dict], key: list[str]):
        old = pd.read_csv(path) if path.exists() else pd.DataFrame(columns=list(rows[0].keys()))
        old = old[old["date"] != today.isoformat()]
        pd.concat([old, pd.DataFrame(rows)], ignore_index=True).sort_values(key).to_csv(path, index=False)

    append(month_file, idx_rows, ["date", "index"])
    append(DATA / "stocks" / f"{today:%Y-%m}.csv", list(stocks.values()), ["date", "symbol"])

    ad_path = DATA / "meta" / "advance_decline.csv"
    ad = pd.read_csv(ad_path)
    ad = ad[ad["date"] != today.isoformat()]
    recent = ad.tail(20)
    size = (recent["advances"] + recent["declines"] + recent["unchanged"]).mean()
    k = size / max(1, adv + dec + unch)          # scale ~800 stocks up to the full NSE list
    ad = pd.concat([ad, pd.DataFrame([{"date": today.isoformat(), "advances": round(adv * k),
                                       "declines": round(dec * k), "unchanged": round(unch * k)}])], ignore_index=True)
    ad.to_csv(ad_path, index=False)

    # ------------------------------------------------------------- rebuild and mark as provisional
    from analysis import build
    build.main()
    stamp = {"date": today.isoformat(), "time": hhmm, "stocks": len(stocks), "indices": len(idx_rows),
             "volume_scaled": round(scale, 2)}
    for path in SITE.glob("*.json"):
        d = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(d, dict):
            d["provisional"] = stamp
            path.write_text(json.dumps(d, separators=(",", ":")), encoding="utf-8")
    print(f"::notice title=Intraday scan::{today} {hhmm} IST: {len(idx_rows)} indices, {len(stocks)} stocks, "
          f"A/D {adv}/{dec} (scaled x{k:.1f}), volume scaled x{scale:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
