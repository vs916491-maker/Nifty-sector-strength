"""Phase 6: did the model's choices actually do well afterwards?

Everything is tested on the stored history (Oct 2024 onwards), using only
data available on each test date.

Sectors     every 5th session from the first date a score exists: each
            index's return over the next 1 and 3 months minus Nifty 500's,
            grouped by its rank that day (top 3 / middle / bottom 3) and by
            its RRG quadrant.
Stocks      first session of each month: every stock is scored from data up
            to that day; next 1- and 3-month return minus Nifty 500's,
            grouped by score band, and for the picks (up to 5 per focus
            sector, score 60+) against all other stocks.
Setups      every positional setup since scores began, walked forward with the
            entry, stop and exit rules (see setups.py).
Regime      Nifty 500's next 1- and 3-month return by the regime light.

Known limits (shown on the website): about 17 months of test dates, which
cover one up-leg, a correction and a recovery, but no long bear market;
the stock universe is today's Nifty Total Market list, so stocks that fell
out of it are missing (survivorship bias, which flatters every group
equally); the market-cap filter is not applied historically.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import sectors as S, setups as SU, stocks as SM

HORIZONS = {"1M": 21, "3M": 63}


def _agg(x: pd.Series) -> dict:
    return {"avg": float(x.mean()), "median": float(x.median()),
            "hit": float((x > 0).mean() * 100), "n": int(len(x))}


def daily_quadrants(ratio: pd.DataFrame, momentum: pd.DataFrame, index: pd.Index) -> pd.DataFrame:
    q = pd.DataFrame({k: [S.quadrant(a, b) for a, b in zip(ratio[k], momentum[k])] for k in ratio.columns},
                     index=ratio.index)
    return q.reindex(index, method="ffill")


def sector_test(idx: pd.DataFrame, groups: dict, res: dict, quads: pd.DataFrame) -> dict:
    rank, score = res["rank"], res["score"]
    dates = score.dropna(how="all").index[::5]
    out = {}
    for g, keys in groups.items():
        out[g] = {}
        for label, n in HORIZONS.items():
            fwd = (idx.shift(-n) / idx - 1) * 100
            ex = fwd[keys].sub(fwd["NIFTY500"], axis=0)
            rows = []
            for d in dates:
                r = rank.loc[d, keys]
                cnt = r.notna().sum()
                for k in keys:
                    if pd.isna(r[k]) or pd.isna(ex.at[d, k]):
                        continue
                    b = "Top 3" if r[k] <= 3 else "Bottom 3" if r[k] > cnt - 3 else "Middle"
                    rows.append((b, quads.at[d, k], ex.at[d, k]))
            df = pd.DataFrame(rows, columns=["bucket", "quadrant", "ex"])
            out[g][label] = {
                "by_rank": {b: _agg(df.loc[df.bucket == b, "ex"]) for b in ("Top 3", "Middle", "Bottom 3")},
                "by_quadrant": {q: _agg(df.loc[df.quadrant == q, "ex"])
                                for q in ("Leading", "Improving", "Weakening", "Lagging")},
            }
    return out


def stock_test(st: dict, idx: pd.DataFrame, cons: dict, keys: list[str], res: dict,
               quads: pd.DataFrame) -> dict:
    mem = SM.membership(cons, keys)
    universe = sorted(set(cons.get("TOTALMKT", pd.DataFrame(columns=["symbol"]))["symbol"])
                      | {s for m in mem.values() for s in m})
    close, dates = st["close"], st["close"].index
    start = res["score"].dropna(how="all").index[0]
    reb = [d for i, d in enumerate(dates) if d >= start and i and d.month != dates[i - 1].month]
    rows = []
    for d in reb:
        i = dates.get_loc(d)
        df = SM.score_stocks({k: v.iloc[:i + 1] for k, v in st.items()}, universe)
        df = df[(df.traded_value_cr >= SM.FILTERS["min_traded_value_cr"])
                & (df.history_days >= SM.FILTERS["min_history_days"]) & df.score.notna()]
        focus = [k for k in keys if res["rank"].at[d, k] <= 5 or quads.at[d, k] in ("Leading", "Improving")]
        picks = set()
        for k in focus:
            ranked = sorted((s for s in mem[k] if s in df.index), key=lambda s: -df.at[s, "score"])
            picks |= set([s for s in ranked if df.at[s, "score"] >= SM.FILTERS["min_pick_score"]][:SM.PICKS_PER_SECTOR])
        for label, n in HORIZONS.items():
            if i + n >= len(dates):
                continue
            fwd = (close.iloc[i + n] / close.iloc[i] - 1) * 100
            bench = (idx["NIFTY500"].iloc[i + n] / idx["NIFTY500"].iloc[i] - 1) * 100
            for sym, sc in df.score.items():
                if pd.notna(fwd.get(sym)):
                    rows.append((d, label, sym, sc, sym in picks, fwd[sym] - bench))
    R = pd.DataFrame(rows, columns=["date", "h", "symbol", "score", "pick", "ex"])
    bands = [("80+", 80, 101), ("60–80", 60, 80), ("40–60", 40, 60), ("Below 40", 0, 40)]
    out = {"rebalances": len(reb), "first": reb[0].date().isoformat() if reb else None,
           "last": reb[-1].date().isoformat() if reb else None, "by_score": {}, "picks": {}, "monthly": {}}
    for label in HORIZONS:
        x = R[R.h == label]
        out["by_score"][label] = {b: _agg(x.loc[(x.score >= lo) & (x.score < hi), "ex"]) for b, lo, hi in bands}
        out["picks"][label] = {"Picks": _agg(x.loc[x.pick, "ex"]), "All other stocks": _agg(x.loc[~x.pick, "ex"])}
        pm, am = x[x.pick].groupby("date").ex.mean(), x.groupby("date").ex.mean()
        out["monthly"][label] = [{"date": d.date().isoformat(), "picks": float(pm.get(d, np.nan)), "all": float(am[d])}
                                 for d in am.index]
    return out


def setup_test(trades: pd.DataFrame, ind: dict, regime_df: pd.DataFrame) -> dict:
    if trades.empty:
        return {"summary": SU.summarise(trades)}
    t = trades.copy()
    t["grade"] = [SU.grade(ind["rs_rating"].at[d, s], bool(ind["rs_at_high"].at[d, s]))
                  for d, s in zip(t.signal_date, t.symbol)]
    closed = t[t.status == "Closed"]
    by_grade = {g: SU.summarise(x)["all"] for g, x in t.groupby("grade")}
    by_grade_light = {f"{g}|{l}": SU.summarise(x)["all"] for (g, l), x in t.groupby(["grade", "light"]) if l}
    by_quarter = []
    for q, x in t.groupby(t.signal_date.dt.to_period("Q")):
        s = SU.summarise(x)["all"]
        a = SU.summarise(x[x.grade == "A"])["all"]
        by_quarter.append({"quarter": f"{q.year} Q{q.quarter}", "all": s, "A": a})
    recent = closed.sort_values("exit_date").tail(40).iloc[::-1]
    cols = ["symbol", "setup", "grade", "signal_date", "entry_date", "exit_date", "entry", "stop", "exit",
            "return_pct", "r", "days", "exit_reason", "light"]
    rec = recent[cols].copy()
    for c in ("signal_date", "entry_date", "exit_date"):
        rec[c] = rec[c].dt.date.astype(str)
    rec["setup"] = rec["setup"].map(SU.SETUP_NAMES)
    return {"summary": SU.summarise(t), "by_grade": by_grade, "by_grade_light": by_grade_light,
            "by_quarter": by_quarter, "recent": rec.to_dict("records")}


def regime_test(idx: pd.DataFrame, regime_df: pd.DataFrame) -> dict:
    out = {}
    b = idx["NIFTY500"]
    for label, n in HORIZONS.items():
        fwd = ((b.shift(-n) / b - 1) * 100).reindex(regime_df.index)
        df = pd.DataFrame({"light": regime_df["light"], "f": fwd}).dropna()
        out[label] = {l: _agg(df.loc[df.light == l, "f"]) for l in ("Green", "Amber", "Red")}
    out["days"] = {l: int((regime_df["light"] == l).sum()) for l in ("Green", "Amber", "Red")}
    return out


def build(idx, st, cons, groups, res, ind, trades, regime_df) -> dict:
    keys = [k for g in groups.values() for k in g]
    ratio, momentum = S.rrg(idx[keys], idx["NIFTY500"])
    quads = daily_quadrants(ratio, momentum, idx.index)
    first = res["score"].dropna(how="all").index[0]
    return {
        "as_of": idx.index[-1].date().isoformat(),
        "period": {"data_from": idx.index[0].date().isoformat(), "tests_from": first.date().isoformat()},
        "sectors": sector_test(idx, groups, res, quads),
        "stocks": stock_test(st, idx, cons, keys, res, quads),
        "setups": setup_test(trades, ind, regime_df),
        "regime": regime_test(idx, regime_df),
        "leadership": leadership_test(idx, st, cons, groups, res),
    }


# ---------------------------------------------------------------- leadership change
EPISODE_FALL, EPISODE_BOUNCE, FWD = 8.0, 6.0, 63


def leadership_test(idx: pd.DataFrame, st: dict, cons: dict, groups: dict, res: dict) -> dict:
    """At each past correction, once Nifty 500 is 6%+ off a low that was 8%+
    below its 6-month peak: did the next-leader stocks and sectors beat the
    old leaders over the following 3 months?"""
    from . import leaders as LD
    b = idx["NIFTY500"]
    keys = [k for g in groups.values() for k in g]
    ratio, momentum = S.rrg(idx[keys], b)
    mem = SM.membership(cons, keys)
    universe = sorted(set(cons.get("TOTALMKT", pd.DataFrame(columns=["symbol"]))["symbol"])
                      | {s for m in mem.values() for s in m})
    universe = [s for s in universe if s in st["close"].columns]
    first_score = res["score"].dropna(how="all").index[0]
    used_lows, episodes = set(), []
    for i in range(130, len(b)):
        d = LD.decline(b, i)
        if d["fall"] <= -EPISODE_FALL and d["bounce"] >= EPISODE_BOUNCE and d["low"] not in used_lows:
            used_lows.add(d["low"])
            episodes.append((i, d))
    out = []
    for i, d in episodes:
        sub = {k: v.iloc[:i + 1] for k, v in st.items()}
        tv = (sub["close"] * sub["volume"]).tail(20).mean() / 1e7
        hist = sub["close"].notna().sum()
        elig = [s for s in universe if tv.get(s, 0) >= SM.FILTERS["min_traded_value_cr"] and hist.get(s, 0) >= SM.FILTERS["min_history_days"]]
        nl = LD.stock_scores(st, b, d, elig)
        pk = st["close"].index.get_loc(d["peak"])
        old = SM.score_stocks({k: v.iloc[:pk + 1] for k, v in st.items()}, elig).score
        j = min(i + FWD, len(b) - 1)
        fwd = (st["close"].iloc[j] / st["close"].iloc[i] - 1) * 100 - (b.iloc[j] / b.iloc[i] - 1) * 100
        df = pd.DataFrame({"nl": nl.score, "old": old, "held": nl.held_up_pct, "off": nl.since_low_pct, "fwd": fwd}).dropna(subset=["fwd"])
        q = lambda col: df[col] >= df[col].quantile(0.8)   # noqa: E731
        groups_out = {
            "Next leaders (top 20% next-leader score)": df.loc[q("nl"), "fwd"],
            "Old leaders (top 20% score at the peak)": df.loc[q("old"), "fwd"],
            "Fell least (top 20%)": df.loc[q("held"), "fwd"],
            "Best off the low (top 20%)": df.loc[q("off"), "fwd"],
            "Old leaders not in the top half now": df.loc[q("old") & (df.nl < df.nl.median()), "fwd"],
            "All stocks": df["fwd"],
        }
        sec = LD.sector_scores(idx.iloc[:i + 1], groups, d, res["rank"], momentum, ratio) if d["peak"] >= first_score else {}
        sfwd = (idx[keys].iloc[j] / idx[keys].iloc[i] - 1) * 100 - (b.iloc[j] / b.iloc[i] - 1) * 100
        sector_rows = [{"key": k, "status": v["status"], "nl_rank": v["nl_rank"], "rank_at_peak": v["rank_at_peak"],
                        "fwd": sfwd[k]} for k, v in sec.items()]
        by_status = {}
        for st_name in ("Emerging", "Steady leader", "Fading leader"):
            vals = [r["fwd"] for r in sector_rows if r["status"] == st_name and pd.notna(r["fwd"])]
            if vals:
                by_status[st_name] = {"avg": float(np.mean(vals)), "n": len(vals)}
        out.append({
            **LD.describe(d), "eval_date": b.index[i].date().isoformat(), "fwd_days": int(j - i),
            "complete": bool(j - i >= FWD),
            "groups": {k: _agg(v) for k, v in groups_out.items() if len(v)},
            "corr_next": float(df.nl.corr(df.fwd, method="spearman")),
            "corr_old": float(df.old.corr(df.fwd, method="spearman")) if df.old.notna().sum() > 20 else None,
            "sectors_by_status": by_status,
            "sector_corr_next": float(pd.Series({r["key"]: r["nl_rank"] for r in sector_rows}).corr(
                pd.Series({r["key"]: r["fwd"] for r in sector_rows}), method="spearman") * -1) if sector_rows else None,
            "sector_corr_old": float(pd.Series({r["key"]: r["rank_at_peak"] for r in sector_rows}).corr(
                pd.Series({r["key"]: r["fwd"] for r in sector_rows}), method="spearman") * -1) if sector_rows else None,
            "top_next": df.sort_values("nl", ascending=False).head(10).index.tolist(),
        })
    return {"rules": {"fall": EPISODE_FALL, "bounce": EPISODE_BOUNCE, "forward": FWD}, "episodes": out}
