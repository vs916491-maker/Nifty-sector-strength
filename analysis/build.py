"""Compute sector strength and write the JSON files the website reads.

Run:  python -m analysis.build

Writes:
  site/data/sectors.json         latest scores, ranks, RRG tails per benchmark
  site/data/sector_history.json  ~1 year of RS lines, scores and prices
  site/data/stocks.json          stock scores, sector members, focus-sector picks
  site/data/breadth.json         market breadth: A/D line, % above DMAs, highs/lows
  site/data/regime.json          market regime light and its history
  site/data/validation.json      Phase 6: how the model's choices did afterwards
"""

from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from collector import config

from . import breadth as breadth_mod, data, regime as regime_mod, sectors, setups as setups_mod, stocks as stock_mod, validate

OUT = Path(__file__).resolve().parent.parent / "site" / "data"
BENCHMARKS = ["NIFTY500", "NIFTY50"]       # first = default on the website
HISTORY_DAYS = 260


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
    rg = regime_mod.series(idx, stocks["close"], cons)
    ind = setups_mod.indicators(stocks, idx["NIFTY500"])
    sets = setups_mod.detect(ind)
    last = ind["close"].index[-1]
    eligible = {s for s, v in stock_out["stocks"].items() if v.get("eligible")}
    for sym, v in stock_out["stocks"].items():
        if sym in ind["close"].columns and bool(ind["rs_at_high"].at[last, sym]):
            v["flags"].append("RS at high")
    stock_out["setups"] = setups_mod.today(ind, sets, stock_out["stocks"], eligible)
    stock_out["leaders"] = setups_mod.leaders(ind, eligible)
    stock_out["setup_rules"] = {"trend": setups_mod.TREND, "breakout": setups_mod.BREAKOUT,
                                "tight": setups_mod.TIGHT, "pullback": setups_mod.PULLBACK,
                                "stop": setups_mod.STOP, "exit": setups_mod.EXIT,
                                "a_grade_rs": setups_mod.A_GRADE_RS}
    trades = setups_mod.simulate(ind, sets, rg["light"])
    val = validate.build(idx, stocks, cons, groups, res_by_bench["NIFTY500"], ind, trades, rg)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "sectors.json").write_text(json.dumps(clean(out), separators=(",", ":")),
                                      encoding="utf-8")
    (OUT / "sector_history.json").write_text(json.dumps(clean(hist), separators=(",", ":")),
                                             encoding="utf-8")
    mkt = breadth_mod.build(idx, stocks["close"], cons)
    (OUT / "breadth.json").write_text(json.dumps(clean(mkt), separators=(",", ":")),
                                      encoding="utf-8")
    (OUT / "regime.json").write_text(json.dumps(clean(regime_mod.latest(rg)), separators=(",", ":")),
                                     encoding="utf-8")
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
