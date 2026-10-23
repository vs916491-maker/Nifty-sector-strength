"""Incremental data collector.

Run:  python -m collector.update            (fetch everything missing up to today)
      python -m collector.update --start 2024-10-01   (force an earlier start)

What it stores (all plain CSV under data/):
  data/indices/YYYY-MM.csv   daily OHLC + P/E, P/B for every NSE index
  data/stocks/YYYY-MM.csv    daily OHLC, volume, delivery % for EQ/BE stocks
  data/constituents/KEY.csv  current constituents of each tracked index
  data/meta/fno_symbols.csv  stocks with F&O contracts
  data/meta/status.json      what the last run did (dates, counts, problems)
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import zipfile
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from . import config, corporate_actions
from .nse import BlockedError, NSEClient

IST = ZoneInfo("Asia/Kolkata")
DATA = Path(__file__).resolve().parent.parent / "data"
IDX_DIR = DATA / "indices"
STK_DIR = DATA / "stocks"
CON_DIR = DATA / "constituents"
META = DATA / "meta"

IDX_COLS = ["date", "index", "open", "high", "low", "close",
            "pe", "pb", "div_yield", "turnover_cr"]
STK_COLS = ["date", "symbol", "series", "prev_close", "open", "high", "low",
            "close", "volume", "deliv_pct"]


# ----------------------------------------------------------------- helpers
def num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.astype(str).str.strip().str.replace(",", ""),
                         errors="coerce")


def last_stored_date(folder: Path) -> dt.date | None:
    files = sorted(folder.glob("*.csv"))
    if not files:
        return None
    df = pd.read_csv(files[-1], usecols=["date"])
    return dt.date.fromisoformat(df["date"].max()) if len(df) else None


def merge_month(folder: Path, month: str, new: pd.DataFrame, key: list[str]) -> None:
    path = folder / f"{month}.csv"
    if path.exists():
        new = pd.concat([pd.read_csv(path), new], ignore_index=True)
    new = new.drop_duplicates(subset=key, keep="last").sort_values(key)
    folder.mkdir(parents=True, exist_ok=True)
    new.to_csv(path, index=False, float_format="%.2f")


# Stocks kept from the bhavcopy: constituents of every tracked index
# (incl. Nifty Total Market) plus F&O stocks. Empty set = keep all.
UNIVERSE: set[str] = set()
MIN_UNIVERSE = 500  # sanity check: below this the lists did not download


def build_universe() -> set[str]:
    symbols: set[str] = set()
    for path in CON_DIR.glob("*.csv"):
        symbols |= set(pd.read_csv(path, dtype=str)["symbol"].dropna().str.strip())
    fno = META / "fno_symbols.csv"
    if fno.exists():
        symbols |= set(pd.read_csv(fno, dtype=str)["symbol"].dropna().str.strip())
    return symbols if len(symbols) >= MIN_UNIVERSE else set()


def compact_stocks() -> dict:
    """One-off clean-up of stored stock files: drop non-trading days (dates
    with no index data) and stocks outside the universe."""
    trading_days: set[str] = set()
    for path in IDX_DIR.glob("*.csv"):
        trading_days |= set(pd.read_csv(path, usecols=["date"])["date"])
    before = after = 0
    for path in sorted(STK_DIR.glob("*.csv")):
        df = pd.read_csv(path)
        before += len(df)
        df = df[df["date"].isin(trading_days)]
        if UNIVERSE:
            df = df[df["symbol"].isin(UNIVERSE)]
        after += len(df)
        df.to_csv(path, index=False, float_format="%.2f")
    return {"rows_before": before, "rows_after": after}


def update_corporate_actions(client: NSEClient, today: dt.date) -> dict:
    path = META / "corporate_actions.csv"
    old = pd.read_csv(path, dtype={"factor": float}) if path.exists() else None
    start = config.BACKFILL_START
    if old is not None and len(old):
        start = max(start, today - dt.timedelta(days=120))
    new = corporate_actions.fetch(client, start, today + dt.timedelta(days=60))
    df = new if old is None else pd.concat([old, new], ignore_index=True)
    df = df.drop_duplicates(subset=["symbol", "ex_date", "subject"], keep="last")
    df = df.sort_values(["ex_date", "symbol"])
    META.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return {"ok": True, "events": int(df["factor"].notna().sum()), "fetched": len(new)}


def adjustment_factors() -> dict[tuple[str, str], float]:
    """(symbol, ex_date) -> combined price factor from NSE split/bonus events
    plus data/meta/manual_adjustments.csv (demergers etc.). Several events on
    the same day (e.g. bonus + split) multiply."""
    frames = []
    for name in ("corporate_actions.csv", "manual_adjustments.csv"):
        path = META / name
        if path.exists():
            frames.append(pd.read_csv(path, usecols=["symbol", "ex_date", "factor"]))
    if not frames:
        return {}
    ca = pd.concat(frames).dropna(subset=["factor"])
    combined = ca.groupby(["symbol", "ex_date"])["factor"].prod()
    return {k: float(v) for k, v in combined.items()}


def check_price_jumps() -> dict:
    """Self-check: big overnight drops (> 30%) should mostly be explained by a
    split/bonus. Unexplained ones are listed for review (demergers, crashes,
    or a missing corporate action)."""
    events = adjustment_factors()
    stk = pd.concat(pd.read_csv(f, usecols=["date", "symbol", "close"])
                    for f in sorted(STK_DIR.glob("*.csv")))
    stk = stk.sort_values(["symbol", "date"])
    stk["ratio"] = stk["close"] / stk.groupby("symbol")["close"].shift()
    drops = stk[stk["ratio"] < 0.7]
    explained, unexplained = 0, []
    for r in drops.itertuples():
        f = events.get((r.symbol, r.date))
        if f is not None and abs(r.ratio / f - 1) < 0.25:
            explained += 1
        else:
            unexplained.append(f"{r.date} {r.symbol} {r.ratio:.2f}")
    return {"big_drops": len(drops), "explained_by_split_bonus": explained,
            "unexplained": unexplained[:40]}


# ----------------------------------------------------------------- parsers
def parse_index_file(text: str, day: dt.date) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(text))
    df.columns = [c.strip() for c in df.columns]
    if "Index Date" in df.columns:
        dates = pd.to_datetime(df["Index Date"].astype(str).str.strip(),
                               format="%d-%m-%Y", errors="coerce").dt.date
        df = df[dates == day]
    out = pd.DataFrame({
        "date": day.isoformat(),
        "index": df["Index Name"].astype(str).str.strip(),
        "open": num(df["Open Index Value"]),
        "high": num(df["High Index Value"]),
        "low": num(df["Low Index Value"]),
        "close": num(df["Closing Index Value"]),
        "pe": num(df.get("P/E", pd.Series(dtype=str))),
        "pb": num(df.get("P/B", pd.Series(dtype=str))),
        "div_yield": num(df.get("Div Yield", pd.Series(dtype=str))),
        "turnover_cr": num(df.get("Turnover (Rs. Cr.)", pd.Series(dtype=str))),
    })
    return out.dropna(subset=["close"])[IDX_COLS]


AD_ROWS: list[dict] = []
AD_PATH = META / "advance_decline.csv"


def ad_counts(df: pd.DataFrame, day: dt.date) -> dict:
    """Advances / declines / unchanged across ALL EQ+BE stocks that traded,
    measured close vs previous close (before the universe filter)."""
    close, prev = num(df["CLOSE_PRICE"]), num(df["PREV_CLOSE"])
    ok = close.notna() & prev.notna() & (prev > 0)
    chg = (close[ok] - prev[ok])
    return {"date": day.isoformat(), "advances": int((chg > 0).sum()),
            "declines": int((chg < 0).sum()), "unchanged": int((chg == 0).sum())}


def save_ad_rows() -> dict:
    if not AD_ROWS:
        return {"days_added": 0}
    new = pd.DataFrame(AD_ROWS)
    if AD_PATH.exists():
        new = pd.concat([pd.read_csv(AD_PATH), new], ignore_index=True)
    new = new.drop_duplicates("date", keep="last").sort_values("date")
    META.mkdir(parents=True, exist_ok=True)
    new.to_csv(AD_PATH, index=False)
    added = len(AD_ROWS)
    AD_ROWS.clear()
    return {"days_added": added, "total_days": len(new)}


def rebuild_ad(client: NSEClient) -> dict:
    """One-off: count advances/declines for every stored trading day."""
    days: set[str] = set()
    for path in IDX_DIR.glob("*.csv"):
        days |= set(pd.read_csv(path, usecols=["date"])["date"])
    for i, d in enumerate(sorted(days)):
        day = dt.date.fromisoformat(d)
        text = client.get_text(config.BHAVCOPY_URL.format(ddmmyyyy=day.strftime("%d%m%Y")))
        if text:
            df = pd.read_csv(io.StringIO(text), dtype=str)
            df.columns = [c.strip() for c in df.columns]
            df["SERIES"] = df["SERIES"].str.strip()
            df = df[df["SERIES"].isin(config.STOCK_SERIES)]
            dates = pd.to_datetime(df["DATE1"].str.strip(), format="%d-%b-%Y",
                                   errors="coerce").dt.date
            df = df[dates == day]
            if len(df):
                AD_ROWS.append(ad_counts(df, day))
        if i % 50 == 49:
            save_ad_rows()
    return save_ad_rows()


def parse_bhavcopy(text: str, day: dt.date) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(text), dtype=str)
    df.columns = [c.strip() for c in df.columns]
    df["SERIES"] = df["SERIES"].str.strip()
    df = df[df["SERIES"].isin(config.STOCK_SERIES)]
    # NSE serves a copy of the previous session's file for some holidays
    # and Sundays; DATE1 tells the real trading date.
    dates = pd.to_datetime(df["DATE1"].str.strip(), format="%d-%b-%Y",
                           errors="coerce").dt.date
    df = df[dates == day]
    if len(df):
        AD_ROWS.append(ad_counts(df, day))
    if UNIVERSE:
        df = df[df["SYMBOL"].str.strip().isin(UNIVERSE)]
    out = pd.DataFrame({
        "date": day.isoformat(),
        "symbol": df["SYMBOL"].str.strip(),
        "series": df["SERIES"],
        "prev_close": num(df["PREV_CLOSE"]),
        "open": num(df["OPEN_PRICE"]),
        "high": num(df["HIGH_PRICE"]),
        "low": num(df["LOW_PRICE"]),
        "close": num(df["CLOSE_PRICE"]),
        "volume": num(df["TTL_TRD_QNTY"]),
        "deliv_pct": num(df["DELIV_PER"]),
    })
    out = out.dropna(subset=["close"])
    out["volume"] = out["volume"].fillna(0).astype("int64")
    return out[STK_COLS]


# --------------------------------------------------------------- collectors
def collect_daily(client: NSEClient, folder: Path, url_tpl: str, parser,
                  key: list[str], start: dt.date, end: dt.date) -> dict:
    """Fetch every calendar day in [start, end]; missing files are skipped."""
    found, missing, bad = [], 0, []
    by_month: dict[str, list[pd.DataFrame]] = {}
    day = start
    while day <= end:
        text = client.get_text(url_tpl.format(ddmmyyyy=day.strftime("%d%m%Y")))
        if text is not None:
            try:
                frame = parser(text, day)
                if len(frame):
                    by_month.setdefault(day.strftime("%Y-%m"), []).append(frame)
                    found.append(day.isoformat())
                else:
                    missing += 1
            except Exception as exc:  # noqa: BLE001 - one bad file must not stop the run
                bad.append(f"{day}: {type(exc).__name__}: {exc}"[:200])
        else:
            missing += 1
        # flush a finished month so a crash later keeps earlier work
        nxt = day + dt.timedelta(days=1)
        month = day.strftime("%Y-%m")
        if (nxt.month != day.month or nxt > end) and by_month.get(month):
            merge_month(folder, month, pd.concat(by_month.pop(month)), key)
            print(f"  {folder.name}: saved {month}")
        day = nxt
    return {"days_added": len(found), "first": found[0] if found else None,
            "last": found[-1] if found else None, "days_without_file": missing,
            "unreadable_files": bad}


def collect_constituents(client: NSEClient) -> dict:
    CON_DIR.mkdir(parents=True, exist_ok=True)
    status = {}
    for item in config.ALL_INDICES:
        got = None
        for slug in item["slugs"]:
            for tpl in config.CONSTITUENT_URLS:
                url = tpl.format(slug=slug)
                try:
                    text = client.get_text(url, attempts=2)
                except BlockedError:
                    text = None
                if text and "Symbol" in text.splitlines()[0]:
                    got = (url, text)
                    break
            if got:
                break
        path = CON_DIR / f"{item['key']}.csv"
        if not got:
            status[item["key"]] = {"ok": False, "kept_old_file": path.exists()}
            continue
        try:
            df = pd.read_csv(io.StringIO(got[1]), dtype=str)
            # Column spelling varies between files ("Company Name" vs
            # "Company name"), so look columns up case-insensitively.
            cols = {c.strip().lower(): c for c in df.columns}

            def col(*names: str) -> pd.Series:
                for n in names:
                    if n in cols:
                        return df[cols[n]].astype(str).str.strip()
                return pd.Series([""] * len(df), index=df.index)

            out = pd.DataFrame({
                "symbol": col("symbol"),
                "company": col("company name", "company", "name"),
                "industry": col("industry", "sector"),
                "isin": col("isin code", "isin"),
            })
            out = out[(out["symbol"] != "") & (out["symbol"] != "nan")]
        except Exception as exc:  # noqa: BLE001
            status[item["key"]] = {"ok": False, "kept_old_file": path.exists(),
                                   "error": f"{type(exc).__name__}: {exc}"[:200]}
            continue
        out.to_csv(path, index=False)
        status[item["key"]] = {"ok": True, "stocks": len(out), "source": got[0]}
    return status


def collect_mcap(client: NSEClient) -> dict:
    """Latest market-cap snapshot (Rs crore) for every EQ/BE stock."""
    day = last_stored_date(STK_DIR) or dt.datetime.now(IST).date()
    for _ in range(7):
        blob = client.get_bytes(config.PR_ZIP_URL.format(ddmmyy=day.strftime("%d%m%y")), timeout=60)
        if blob and blob[:2] == b"PK":
            zf = zipfile.ZipFile(io.BytesIO(blob))
            name = next((n for n in zf.namelist() if n.lower().startswith("mcap")), None)
            if name:
                df = pd.read_csv(io.BytesIO(zf.read(name)), dtype=str)
                df.columns = [c.strip() for c in df.columns]
                df = df[df["Series"].str.strip().isin(config.STOCK_SERIES)]
                out = pd.DataFrame({
                    "symbol": df["Symbol"].str.strip(),
                    "mcap_cr": num(df["Market Cap(Rs.)"]) / 1e7,
                    "shares": num(df["Issue Size"]),
                }).dropna(subset=["mcap_cr"])
                out = out.sort_values("mcap_cr", ascending=False).drop_duplicates("symbol")
                out.insert(0, "date", day.isoformat())
                META.mkdir(parents=True, exist_ok=True)
                out.to_csv(META / "mcap.csv", index=False, float_format="%.2f")
                return {"ok": True, "date": day.isoformat(), "stocks": len(out)}
        day -= dt.timedelta(days=1)
    return {"ok": False}


def collect_fno(client: NSEClient) -> dict:
    text = client.get_text(config.FNO_LOTS_URL)
    if not text:
        return {"ok": False}
    df = pd.read_csv(io.StringIO(text), dtype=str)
    df.columns = [c.strip() for c in df.columns]
    out = pd.DataFrame({"symbol": df["SYMBOL"].str.strip(),
                        "underlying": df["UNDERLYING"].str.strip()})
    out = out[out["symbol"].notna() & (out["symbol"] != "Symbol")
              & (out["symbol"] != "SYMBOL")]
    META.mkdir(parents=True, exist_ok=True)
    out.to_csv(META / "fno_symbols.csv", index=False)
    return {"ok": True, "symbols": len(out)}


def index_name_check() -> dict:
    """Which configured indices are found in the stored index data."""
    files = sorted(IDX_DIR.glob("*.csv"))
    if not files:
        return {}
    latest = pd.read_csv(files[-1])
    names = sorted(latest["index"].unique())
    (META / "index_names.txt").write_text("\n".join(names) + "\n", encoding="utf-8")
    lower = {n.lower(): n for n in names}
    result = {}
    for item in config.ALL_INDICES:
        match = next((lower[a.lower()] for a in item["aliases"] if a.lower() in lower), None)
        result[item["key"]] = match
    return result


# --------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=dt.date.fromisoformat, default=None)
    ap.add_argument("--rebuild-ad", action="store_true",
                    help="recount advances/declines for all stored days")
    ap.add_argument("--compact", action="store_true",
                    help="clean stored stock files (non-trading days, universe)")
    args = ap.parse_args()

    today = dt.datetime.now(IST).date()
    client = NSEClient()
    status: dict = {"run_at_ist": dt.datetime.now(IST).isoformat(timespec="seconds")}
    problems: list[str] = []

    print("Constituents ...")
    status["constituents"] = collect_constituents(client)
    print("F&O list ...")
    try:
        status["fno"] = collect_fno(client)
    except Exception as exc:  # noqa: BLE001 - optional data, never fatal
        status["fno"] = {"ok": False}
        problems.append(f"F&O list: {type(exc).__name__}: {exc}"[:200])

    print("Corporate actions ...")
    try:
        status["corporate_actions"] = update_corporate_actions(client, today)
    except Exception as exc:  # noqa: BLE001 - not fatal; retried next run
        status["corporate_actions"] = {"ok": False}
        problems.append(f"Corporate actions: {type(exc).__name__}: {exc}"[:200])

    global UNIVERSE
    UNIVERSE = build_universe()
    status["universe_size"] = len(UNIVERSE)
    if not UNIVERSE:
        problems.append("Stock universe incomplete - keeping all stocks this run")

    for label, folder, url, parser, key in [
        ("indices", IDX_DIR, config.INDEX_CLOSE_URL, parse_index_file, ["date", "index"]),
        ("stocks", STK_DIR, config.BHAVCOPY_URL, parse_bhavcopy, ["date", "symbol"]),
    ]:
        last = last_stored_date(folder)
        start = args.start or (last + dt.timedelta(days=1) if last else config.BACKFILL_START)
        print(f"{label}: fetching {start} .. {today}")
        try:
            status[label] = collect_daily(client, folder, url, parser, key, start, today)
        except BlockedError as exc:
            problems.append(f"{label}: {exc}")
            status[label] = {"error": str(exc)}
        status[label]["latest_stored"] = str(last_stored_date(folder))

    status["advance_decline"] = save_ad_rows()
    if args.rebuild_ad:
        print("Rebuilding advance/decline history ...")
        status["advance_decline"] = rebuild_ad(client)

    print("Market cap ...")
    try:
        status["mcap"] = collect_mcap(client)
    except Exception as exc:  # noqa: BLE001 - keep yesterday's snapshot
        status["mcap"] = {"ok": False}
        problems.append(f"Market cap: {type(exc).__name__}: {exc}"[:200])

    if args.compact:
        status["compact"] = compact_stocks()
        print("compact:", status["compact"])

    status["price_jump_check"] = check_price_jumps()
    status["index_name_match"] = index_name_check()
    missing_names = [k for k, v in status["index_name_match"].items() if v is None]
    missing_cons = [k for k, v in status["constituents"].items() if not v["ok"]]
    for label in ("indices", "stocks"):
        for b in status[label].get("unreadable_files", [])[:5]:
            problems.append(f"{label} unreadable {b}")
    if missing_names:
        problems.append("Index not found in NSE file: " + ", ".join(missing_names))
    if missing_cons:
        problems.append("Constituent list not found: " + ", ".join(missing_cons))
    status["problems"] = problems
    status["requests_made"] = client.requests_made

    META.mkdir(parents=True, exist_ok=True)
    (META / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")

    summary = (
        f"Indices up to {status['indices'].get('latest_stored')} "
        f"(+{status['indices'].get('days_added', 0)} days); "
        f"stocks up to {status['stocks'].get('latest_stored')} "
        f"(+{status['stocks'].get('days_added', 0)} days); "
        f"constituent lists {len(status['constituents']) - len(missing_cons)}"
        f"/{len(status['constituents'])}; problems: {len(problems)}"
        f"; split/bonus events {status['corporate_actions'].get('events')}"
        f"; big drops explained {status['price_jump_check']['explained_by_split_bonus']}"
        f"/{status['price_jump_check']['big_drops']}"
    )
    print(summary)
    for p in problems:
        print("PROBLEM:", p)
    if os.environ.get("GITHUB_ACTIONS"):
        msg = summary + ("\n" + "\n".join(problems) if problems else "")
        print("::notice title=Data update::" + msg.replace("%", "%25").replace("\n", "%0A"))
    # Fail the run only if no data could be fetched at all.
    return 1 if ("error" in status["indices"] and "error" in status["stocks"]) else 0


def run() -> int:
    try:
        return main()
    except Exception:  # noqa: BLE001 - surface the error in the GitHub UI
        import traceback
        tb = traceback.format_exc()
        print(tb)
        if os.environ.get("GITHUB_ACTIONS"):
            print("::error title=Collector crashed::" + tb[-3000:].replace("%", "%25").replace("\n", "%0A"))
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
