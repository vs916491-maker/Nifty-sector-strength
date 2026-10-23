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
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from . import config
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


# ----------------------------------------------------------------- parsers
def parse_index_file(text: str, day: dt.date) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(text))
    df.columns = [c.strip() for c in df.columns]
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


def parse_bhavcopy(text: str, day: dt.date) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(text), dtype=str)
    df.columns = [c.strip() for c in df.columns]
    df["SERIES"] = df["SERIES"].str.strip()
    df = df[df["SERIES"].isin(config.STOCK_SERIES)]
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
                by_month.setdefault(day.strftime("%Y-%m"), []).append(parser(text, day))
                found.append(day.isoformat())
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
