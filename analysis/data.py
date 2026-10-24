"""Load the stored NSE data into wide tables (dates x names)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from collector import config

DATA = Path(__file__).resolve().parent.parent / "data"


def _read_months(folder: Path, cols: list[str]) -> pd.DataFrame:
    files = sorted(folder.glob("*.csv"))
    return pd.concat((pd.read_csv(f, usecols=cols) for f in files), ignore_index=True)


def index_closes() -> pd.DataFrame:
    """Daily closes of every tracked index, columns = config keys."""
    raw = _read_months(DATA / "indices", ["date", "index", "close"])
    lower = {n.lower(): n for n in raw["index"].unique()}
    rename = {}
    for item in config.ALL_INDICES:
        for alias in item["aliases"]:
            if alias.lower() in lower:
                rename[lower[alias.lower()]] = item["key"]
                break
    raw = raw[raw["index"].isin(rename)]
    wide = raw.pivot(index="date", columns="index", values="close").rename(columns=rename)
    wide.index = pd.to_datetime(wide.index)
    return wide.sort_index()


def index_valuations() -> pd.DataFrame:
    """Latest P/E, P/B, dividend yield per tracked index (keyed by config key)."""
    files = sorted((DATA / "indices").glob("*.csv"))
    latest = pd.read_csv(files[-1])
    latest = latest[latest["date"] == latest["date"].max()]
    lower = {n.lower(): n for n in latest["index"]}
    rows = {}
    for item in config.ALL_INDICES:
        for alias in item["aliases"]:
            if alias.lower() in lower:
                r = latest[latest["index"] == lower[alias.lower()]].iloc[0]
                rows[item["key"]] = {"pe": r["pe"], "pb": r["pb"], "div_yield": r["div_yield"]}
                break
    return pd.DataFrame.from_dict(rows, orient="index")


def adjustment_table() -> pd.DataFrame:
    """symbol, ex_date, factor: splits/bonuses (NSE) + manual (demergers).
    Several events on one day multiply."""
    frames = []
    for name in ("corporate_actions.csv", "manual_adjustments.csv"):
        path = DATA / "meta" / name
        if path.exists():
            frames.append(pd.read_csv(path, usecols=["symbol", "ex_date", "factor"]))
    if not frames:
        return pd.DataFrame(columns=["symbol", "ex_date", "factor"])
    ca = pd.concat(frames).dropna(subset=["factor"])
    ca = ca.groupby(["symbol", "ex_date"], as_index=False)["factor"].prod()
    ca["ex_date"] = pd.to_datetime(ca["ex_date"])
    return ca


def stock_tables() -> dict[str, pd.DataFrame]:
    """Wide tables of stock data, prices adjusted for splits/bonuses/demergers.

    Returns open, high, low, close, volume, deliv_pct (dates x symbols). Volume is
    adjusted inversely so volume x price stays comparable.
    """
    raw = _read_months(DATA / "stocks",
                       ["date", "symbol", "open", "high", "low", "close", "volume", "deliv_pct"])
    raw["date"] = pd.to_datetime(raw["date"])
    out = {c: raw.pivot(index="date", columns="symbol", values=c).sort_index()
           for c in ("open", "high", "low", "close", "volume", "deliv_pct")}
    # cumulative factor per symbol: product of factors of all LATER ex-dates
    adj = pd.DataFrame(1.0, index=out["close"].index, columns=out["close"].columns)
    for r in adjustment_table().itertuples():
        if r.symbol in adj.columns:
            adj.loc[adj.index < r.ex_date, r.symbol] *= r.factor
    for c in ("open", "high", "low", "close"):
        out[c] = out[c] * adj
    out["volume"] = out["volume"] / adj
    return out


def constituents() -> dict[str, pd.DataFrame]:
    """key -> DataFrame(symbol, company, industry)."""
    out = {}
    for item in config.ALL_INDICES:
        path = DATA / "constituents" / f"{item['key']}.csv"
        if path.exists():
            out[item["key"]] = pd.read_csv(path, dtype=str)
    return out


def fno_symbols() -> set[str]:
    path = DATA / "meta" / "fno_symbols.csv"
    return set(pd.read_csv(path, dtype=str)["symbol"]) if path.exists() else set()


def mcap() -> pd.DataFrame:
    """Latest market cap snapshot: symbol, mcap_cr (empty if not collected yet)."""
    path = DATA / "meta" / "mcap.csv"
    if not path.exists():
        return pd.DataFrame(columns=["symbol", "mcap_cr"])
    return pd.read_csv(path, usecols=["symbol", "mcap_cr"])


def results_calendar() -> pd.DataFrame:
    """Board meetings for financial results: symbol, date (ISO), purpose."""
    path = DATA / "meta" / "results_calendar.csv"
    if not path.exists():
        return pd.DataFrame(columns=["symbol", "date", "purpose"])
    return pd.read_csv(path, dtype=str).dropna(subset=["symbol", "date"])


def index_close_by_name(name: str, column: str = "close") -> pd.Series:
    """Daily close (or another column, e.g. turnover_cr) of any NSE index by its
    name in the NSE file (e.g. 'Nifty500 Equal Weight')."""
    raw = _read_months(DATA / "indices", ["date", "index", column])
    s = raw[raw["index"].str.lower() == name.lower()].set_index("date")[column]
    s.index = pd.to_datetime(s.index)
    return s[~s.index.duplicated(keep="last")].sort_index()
