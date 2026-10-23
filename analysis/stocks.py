"""Stock drill-down: who leads inside the leading sectors.

Universe: Nifty Total Market (largest ~750 NSE stocks, all above Rs 500 cr)
plus every constituent of the tracked indices.

Sector membership
  * Official index constituents (every sector and theme).
  * For sectoral indices whose NSE industry is unambiguous, also every other
    Total Market stock in that industry (e.g. all IT companies, not just the
    10 in Nifty IT). Bank / Private Bank / PSU Bank / Pharma share a broader
    NSE industry (Financial Services / Healthcare), so they stay official-only.

Stock score 0-100
  RS rating     35%  IBD-style: weighted 3/6/9/12-month return, percentile
                     rank across the whole universe (1-99)
  Trend         25%  above 50/150/200-day averages, 50 > 200, 200 rising
  Near high     15%  100 at the 52-week high, 0 at 25% or more below it
  Recent RS     15%  1-month return, percentile rank across the universe
  Accumulation  10%  up-day vs down-day volume (50 days) and rising
                     delivery % (20-day vs 60-day average)

Picks are the top stocks (up to 5) by score inside each focus sector that
pass the filters: market cap >= Rs 500 cr, 20-day average traded value
>= Rs 5 cr, at least 6 months of history, and score >= 60. A weak sector can
therefore have fewer than 5 picks.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import sectors as S

INDUSTRY_PEERS = {
    "AUTO": "Automobile and Auto Components",
    "FINSERV": "Financial Services",
    "FMCG": "Fast Moving Consumer Goods",
    "HEALTHCARE": "Healthcare",
    "IT": "Information Technology",
    "MEDIA": "Media Entertainment & Publication",
    "METAL": "Metals & Mining",
    "REALTY": "Realty",
    "CONSDUR": "Consumer Durables",
    "OILGAS": "Oil Gas & Consumable Fuels",
    "CHEMICALS": "Chemicals",
}
WEIGHTS = {"rs_rating": 0.35, "trend": 0.25, "near_high": 0.15,
           "recent_rs": 0.15, "accumulation": 0.10}
FILTERS = {"min_mcap_cr": 500, "min_traded_value_cr": 5, "min_history_days": 126,
           "min_pick_score": 60}
PICKS_PER_SECTOR = 5


def membership(cons: dict[str, pd.DataFrame], sector_keys: list[str]) -> dict[str, dict[str, str]]:
    """sector key -> {symbol: 'index' | 'industry'}."""
    tm = cons.get("TOTALMKT", pd.DataFrame(columns=["symbol", "industry"]))
    out: dict[str, dict[str, str]] = {}
    for key in sector_keys:
        members = {s: "index" for s in cons.get(key, pd.DataFrame(columns=["symbol"]))["symbol"]}
        industry = INDUSTRY_PEERS.get(key)
        if industry:
            for s in tm.loc[tm["industry"] == industry, "symbol"]:
                members.setdefault(s, "industry")
        out[key] = members
    return out


def _ret(df: pd.DataFrame, n: int) -> pd.Series:
    if len(df) <= n:
        return pd.Series(np.nan, index=df.columns)
    return (df.iloc[-1] / df.iloc[-1 - n] - 1) * 100


def score_stocks(st: dict[str, pd.DataFrame], universe: list[str]) -> pd.DataFrame:
    """Latest metrics and score for every stock in the universe."""
    cols = [s for s in universe if s in st["close"].columns]
    close, high = st["close"][cols], st["high"][cols]
    vol, deliv = st["volume"][cols], st["deliv_pct"][cols]
    hist_days = close.notna().sum()

    r1, r3, r6, r9, r12 = (_ret(close, n) for n in (21, 63, 126, 189, 250))
    # IBD-style weighting; missing longer periods fall back to what exists
    parts = pd.concat([r3 * 0.4, r6 * 0.2, r9 * 0.2, r12 * 0.2], axis=1)
    w = pd.concat([r3.notna() * 0.4, r6.notna() * 0.2, r9.notna() * 0.2,
                   r12.notna() * 0.2], axis=1).sum(axis=1)
    perf = parts.sum(axis=1, min_count=1) / w.replace(0, np.nan)
    rs_rating = (perf.rank(pct=True) * 98 + 1).round()
    recent_rs = r1.rank(pct=True) * 100

    s50, s150, s200 = (S.sma(close, n).iloc[-1] for n in (50, 150, 200))
    s200_prev = S.sma(close, 200).iloc[-22] if len(close) > 222 else pd.Series(np.nan, index=cols)
    last = close.iloc[-1]
    checks = pd.DataFrame({
        "above_50": last > s50, "above_150": last > s150, "above_200": last > s200,
        "50_above_200": s50 > s200, "200_rising": s200 > s200_prev,
    })
    trend = checks.astype(float).where(pd.concat([s50, s150, s200, s200, s200_prev], axis=1)
                                       .set_axis(checks.columns, axis=1).notna()).mean(axis=1) * 100

    hi52 = high.rolling(250, min_periods=60).max().iloc[-1]
    from_high = (last / hi52 - 1) * 100
    near_high = (100 + from_high * 4).clip(0, 100)

    chg = close.diff()
    up_vol = vol.where(chg > 0).tail(50).sum()
    dn_vol = vol.where(chg < 0).tail(50).sum()
    updown = up_vol / dn_vol.replace(0, np.nan)
    deliv20, deliv60 = deliv.tail(20).mean(), deliv.tail(60).mean()
    accumulation = (((updown - 0.7) / 0.8).clip(0, 1) * 100 * 0.6
                    + (deliv20 - deliv60).rank(pct=True) * 100 * 0.4)

    rsi14 = S.rsi(close).iloc[-1]
    ext50 = (last / s50 - 1) * 100
    traded_cr = (close * vol).tail(20).mean() / 1e7

    comps = pd.DataFrame({"rs_rating": rs_rating, "trend": trend, "near_high": near_high,
                          "recent_rs": recent_rs, "accumulation": accumulation})
    score = sum(comps[k].fillna(50) * w_ for k, w_ in WEIGHTS.items())
    score = score.where(rs_rating.notna())

    df = pd.DataFrame({
        "close": last, "score": score, "rs_rating": rs_rating,
        "return_1m": r1, "return_3m": r3, "return_6m": r6, "return_12m": r12,
        "pct_from_52w_high": from_high, "rsi14": rsi14, "pct_above_50dma": ext50,
        "updown_volume": updown, "deliv_pct_20d": deliv20, "traded_value_cr": traded_cr,
        "history_days": hist_days, "trend": trend,
    })
    df = df.join(comps.drop(columns=["rs_rating", "trend"]).add_prefix("c_"))
    df = df.join(checks)
    return df


def build(st: dict[str, pd.DataFrame], idx: pd.DataFrame, cons: dict[str, pd.DataFrame],
          fno: set[str], mcap: pd.DataFrame, sector_keys: list[str],
          focus_by_bench: dict[str, dict[str, list[dict]]]) -> dict:
    members = membership(cons, sector_keys)
    universe = sorted(set(cons.get("TOTALMKT", pd.DataFrame(columns=["symbol"]))["symbol"])
                      | {s for m in members.values() for s in m})
    df = score_stocks(st, universe)

    info = pd.concat([c[["symbol", "company", "industry"]] for c in cons.values()])
    info = info.drop_duplicates("symbol").set_index("symbol")
    df = df.join(info, how="left")
    df["fno"] = df.index.isin(fno)
    df["mcap_cr"] = mcap.set_index("symbol")["mcap_cr"].reindex(df.index) if len(mcap) else np.nan

    ok = ((df["mcap_cr"].fillna(np.inf) >= FILTERS["min_mcap_cr"])
          & (df["traded_value_cr"] >= FILTERS["min_traded_value_cr"])
          & (df["history_days"] >= FILTERS["min_history_days"])
          & df["score"].notna())
    df["eligible"] = ok
    flags = []
    for sym, r in df.iterrows():
        f = []
        if r["fno"]:
            f.append("F&O")
        if (r["pct_above_50dma"] or 0) > 25 or (r["rsi14"] or 0) > 78:
            f.append("Extended")
        if r["history_days"] < 250:
            f.append("New listing")
        if not r["eligible"]:
            f.append("Filtered out")
        flags.append(f)
    df["flags"] = flags

    # excess return vs each sector index it belongs to
    vs_sector: dict[str, dict[str, dict]] = {}
    for key, mem in members.items():
        if key not in idx.columns:
            continue
        sec = idx[key]
        sec1 = (sec.iloc[-1] / sec.iloc[-22] - 1) * 100
        sec3 = (sec.iloc[-1] / sec.iloc[-64] - 1) * 100
        vs_sector[key] = {s: {"excess_1m": df.at[s, "return_1m"] - sec1,
                              "excess_3m": df.at[s, "return_3m"] - sec3,
                              "via": via}
                          for s, via in mem.items() if s in df.index}

    ranked = {key: sorted((s for s in mem if s in df.index and pd.notna(df.at[s, "score"])),
                          key=lambda s: -df.at[s, "score"])
              for key, mem in members.items()}

    focus: dict[str, dict[str, list[dict]]] = {}
    for bench, tabs in focus_by_bench.items():
        focus[bench] = {}
        for tab, items in tabs.items():
            out = []
            for item in items:
                picks = [s for s in ranked.get(item["key"], [])
                         if df.at[s, "eligible"] and df.at[s, "score"] >= FILTERS["min_pick_score"]]
                out.append({**item, "picks": picks[:PICKS_PER_SECTOR]})
            focus[bench][tab] = out

    stocks = {}
    for sym, r in df.iterrows():
        stocks[sym] = {k: (r[k] if not isinstance(r[k], (np.bool_,)) else bool(r[k]))
                       for k in df.columns if k != "flags"}
        stocks[sym]["flags"] = r["flags"]
        stocks[sym]["sectors"] = [k for k, m in members.items() if sym in m]

    return {"weights": WEIGHTS, "filters": FILTERS, "picks_per_sector": PICKS_PER_SECTOR,
            "industry_peers": INDUSTRY_PEERS, "stocks": stocks, "members": ranked,
            "vs_sector": vs_sector, "focus": focus}


def focus_sectors(rows: dict[str, dict], groups: dict[str, list[str]], top_n: int = 5) -> dict[str, list[dict]]:
    """Leading or Improving quadrant, plus the top-N by score, per tab."""
    out = {}
    for tab, keys in groups.items():
        items = []
        for k in sorted(keys, key=lambda k: rows[k]["rank"] if rows[k]["rank"] == rows[k]["rank"] else 99):
            r = rows[k]
            reasons = []
            if r["quadrant"] in ("Leading", "Improving"):
                reasons.append(r["quadrant"])
            if r["rank"] == r["rank"] and r["rank"] <= top_n:
                reasons.append(f"Top {top_n}")
            if reasons:
                items.append({"key": k, "reason": " + ".join(reasons)})
        out[tab] = items
    return out
