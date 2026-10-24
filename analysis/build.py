"""Compute sector strength and write the JSON files the website reads.

Run:  python -m analysis.build

Writes:
  site/data/sectors.json         latest scores, ranks, RRG tails per benchmark
  site/data/sector_history.json  ~1 year of RS lines, scores and prices
  site/data/stocks.json          stock scores, sector members, focus-sector picks
  site/data/breadth.json         market breadth: A/D line, % above DMAs, highs/lows
  site/data/regime.json          market regime light and its history
  site/data/validation.json      Phase 6: how the model's choices did afterwards
  site/data/leaders.json         next leaders and sector rotation in a correction
"""

from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from collector import config

from . import turning, breadth as breadth_mod, data, leaders as leaders_mod, regime as regime_mod, sectors, setups as setups_mod, stocks as stock_mod, validate

OUT = Path(__file__).resolve().parent.parent / "site" / "data"
BENCHMARKS = ["NIFTY500", "NIFTY50"]       # first = default on the website
HISTORY_DAYS = 260
RESULTS_AHEAD_FLAG = 7      # flag results due within this many calendar days
RESULTS_RECENT = 5          # and results announced in the last 5 days
RESULTS_AHEAD_LIST = 45     # results dates kept for My Trades


def clean(obj):
    """Make values JSON-safe: round floats, NaN -> None, numpy -> python."""
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if hasattr(obj, "item"):          # numpy scalar
        obj = obj.item()
    if isinstance(obj, float):
        return None if math.isnan(obj) or math.isinf(obj) else round(obj, 2)
    return obj


def series_dict(df: pd.DataFrame) -> dict[str, list]:
    return {c: df[c].tolist() for c in df.columns}


def main() -> int:
    idx = data.index_closes()
    stocks = data.stock_tables()
    cons = data.constituents()
    members = {k: list(v["symbol"]) for k, v in cons.items()}
    brd = sectors.breadth(stocks["close"], members)

    groups = {
        "Sectoral": [s["key"] for s in config.SECTORS if s["group"] == "Sectoral"],
        "Thematic": [s["key"] for s in config.SECTORS if s["group"] == "Thematic"],
    }
    names = {i["key"]: i["name"] for i in config.ALL_INDICES}
    as_of = idx.index[-1].date().isoformat()
    vals = data.index_valuations()

    out = {
        "as_of": as_of,
        "generated_at": dt.datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(timespec="minutes"),
        "weights": sectors.WEIGHTS,
        "groups": groups,
        "names": names,
        "constituent_counts": {k: len(v) for k, v in members.items()},
        "valuations": vals.to_dict(orient="index"),
        "benchmarks": {},
    }
    hist = {"as_of": as_of, "dates": [], "prices": {}, "benchmarks": {}}
    tail = idx.index[-HISTORY_DAYS:]
    hist["dates"] = [d.date().isoformat() for d in tail]
    keys = [k for g in groups.values() for k in g]
    px = idx[keys + BENCHMARKS]
    hist["prices"] = {
        "close": series_dict(px.loc[tail]),
        "sma50": series_dict(sectors.sma(px, 50).loc[tail]),
        "sma200": series_dict(sectors.sma(px, 200).loc[tail]),
    }
    hist["breadth50"] = series_dict(brd[keys].loc[tail])
    focus_by_bench = {}
    res_by_bench = {}

    for b in BENCHMARKS:
        res = sectors.analyse(idx, groups, b, brd)
        res_by_bench[b] = res
        bench = idx[b]
        out["benchmarks"][b] = {
            "name": names[b],
            "close": bench.iloc[-1],
            "return_1w": (bench.iloc[-1] / bench.iloc[-6] - 1) * 100,
            "return_1m": (bench.iloc[-1] / bench.iloc[-22] - 1) * 100,
            "return_3m": (bench.iloc[-1] / bench.iloc[-64] - 1) * 100,
            "rows": res["rows"],
            "tails": res["tails"],
        }
        rs = res["rs"].loc[tail]
        hist["benchmarks"][b] = {
            "rs": series_dict(rs / rs.iloc[0] * 100),   # rebased to 100
            "score": series_dict(res["score"].loc[tail]),
            "rank": series_dict(res["rank"].loc[tail]),
        }
        focus_by_bench[b] = stock_mod.focus_sectors(res["rows"], groups)

    stock_out = stock_mod.build(stocks, idx, cons, data.fno_symbols(), data.mcap(),
                                keys, focus_by_bench)
    stock_out["as_of"] = as_of

    # regime light, positional setups and the Phase 6 track record
    ad_raw = pd.read_csv(breadth_mod.AD_PATH, parse_dates=["date"]).set_index("date").sort_index() \
        if breadth_mod.AD_PATH.exists() else None
    ad_line = (ad_raw["advances"] - ad_raw["declines"]).cumsum() if ad_raw is not None else None
    rg = regime_mod.series(idx, stocks["close"], cons, data.index_close_by_name("Nifty500 Equal Weight"), ad_line)
    ind = setups_mod.indicators(stocks, idx["NIFTY500"])
    sets = setups_mod.detect(ind)
    last = ind["close"].index[-1]
    eligible = {s for s, v in stock_out["stocks"].items() if v.get("eligible")}
    for sym, v in stock_out["stocks"].items():
        if sym in ind["close"].columns and bool(ind["rs_at_high"].at[last, sym]):
            v["flags"].append("RS at high")
    # quarterly results: flag stocks with results due in the next 7 days or just out
    res_cal = data.results_calendar()
    as_of_d = dt.date.fromisoformat(as_of)
    near = {}
    for sym, grp in res_cal.groupby("symbol"):
        days = [(dt.date.fromisoformat(d) - as_of_d).days for d in grp["date"]]
        upcoming = [d for d in days if d >= 0]
        recent = [d for d in days if d < 0]
        pick = min(upcoming) if upcoming else (max(recent) if recent else None)
        if pick is not None and -RESULTS_RECENT <= pick <= RESULTS_AHEAD_LIST:
            near[sym] = {"date": (as_of_d + dt.timedelta(days=pick)).isoformat(), "days": pick}
    stock_out["results"] = near
    stock_out["results_rules"] = {"ahead_flag": RESULTS_AHEAD_FLAG, "recent": RESULTS_RECENT}
    for sym, v in stock_out["stocks"].items():
        r = near.get(sym)
        if not r:
            continue
        v["results_date"], v["results_days"] = r["date"], r["days"]
        if 0 <= r["days"] <= RESULTS_AHEAD_FLAG:
            v["flags"].append("Results today" if r["days"] == 0 else f"Results in {r['days']}d")
        elif r["days"] < 0:
            v["flags"].append(f"Results {-r['days']}d ago")
    stock_out["setups"] = setups_mod.today(ind, sets, stock_out["stocks"], eligible)
    stock_out["leaders"] = setups_mod.leaders(ind, eligible)
    stock_out["setup_rules"] = {"trend": setups_mod.TREND, "breakout": setups_mod.BREAKOUT,
                                "tight": setups_mod.TIGHT, "pullback": setups_mod.PULLBACK,
                                "stop": setups_mod.STOP, "exit": setups_mod.EXIT,
                                "a_grade_rs": setups_mod.A_GRADE_RS}
    trades = setups_mod.simulate(ind, sets, rg["light"])

    # next leaders and sector rotation during the current decline
    dec = leaders_mod.decline(idx["NIFTY500"])
    nl = leaders_mod.stock_scores(stocks, idx["NIFTY500"], dec, sorted(eligible))
    nl = nl.dropna(subset=["score"]).sort_values("score", ascending=False)
    keys_all = [k for g in groups.values() for k in g]
    ratio, momentum = sectors.rrg(idx[keys_all], idx["NIFTY500"])
    rot = leaders_mod.sector_scores(idx, groups, dec, res_by_bench["NIFTY500"]["rank"], momentum, ratio)
    leaders_out = {
        "as_of": as_of, "decline": leaders_mod.describe(dec),
        "weights": leaders_mod.WEIGHTS, "sector_weights": leaders_mod.SECTOR_WEIGHTS,
        "stocks": [{"symbol": s, **{k: (bool(v) if isinstance(v, (bool, np.bool_)) else v) for k, v in r.items()}}
                   for s, r in nl.head(40).iterrows()],
        "sectors": rot,
    }
    val = validate.build(idx, stocks, cons, groups, res_by_bench["NIFTY500"], ind, trades, rg)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "sectors.json").write_text(json.dumps(clean(out), separators=(",", ":")),
                                      encoding="utf-8")
    (OUT / "sector_history.json").write_text(json.dumps(clean(hist), separators=(",", ":")),
                                             encoding="utf-8")
    mkt = breadth_mod.build(idx, stocks["close"], cons)
    (OUT / "breadth.json").write_text(json.dumps(clean(mkt), separators=(",", ":")),
                                      encoding="utf-8")
    reg_out = regime_mod.latest(rg)
    tp = turning.build(rg, stocks["close"], cons, ad_raw, data.index_close_by_name("Nifty 500", "turnover_cr"))
    reg_out["turning"] = turning.latest(tp, rg)
    val["regime"]["turning_events"] = turning.events(tp, rg["n500"])
    (OUT / "regime.json").write_text(json.dumps(clean(reg_out), separators=(",", ":")),
                                     encoding="utf-8")
    (OUT / "leaders.json").write_text(json.dumps(clean(leaders_out), separators=(",", ":")), encoding="utf-8")
    (OUT / "validation.json").write_text(json.dumps(clean(val), separators=(",", ":")), encoding="utf-8")
    (OUT / "stocks.json").write_text(json.dumps(clean(stock_out), separators=(",", ":")),
                                     encoding="utf-8")
    top = sorted(out["benchmarks"][BENCHMARKS[0]]["rows"].items(),
                 key=lambda kv: kv[1]["rank"] if kv[0] in groups["Sectoral"] else 99)[:3]
    print(f"Sector scores as of {as_of}. Top sectoral: "
          + ", ".join(f"{names[k]} ({v['score']:.0f})" for k, v in top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
