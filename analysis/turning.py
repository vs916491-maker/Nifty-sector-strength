"""Turning-point trackers: seller exhaustion (bottoms) and distribution (tops).

Each tracker has three stages. Stage 1 is the setup, stage 2 the early
signal, stage 3 the confirmation. A stage counts as "met" on a day when its
conditions are true; stages 2 and 3 only count after the stage before them.

Readings used (all daily, end of day)
  gauge     the market internals gauge (-100..+100, see regime.py)
  p50/p200  % of Nifty 500 stocks above their 50- / 200-day averages
  hi/lo     Total Market stocks at a 52-week high / low
  rsi       RSI(14) of Nifty 500 Equal Weight
  adr10     advances / declines over 10 sessions, all NSE stocks
  turnover  Nifty 500 traded value

Seller exhaustion (bottom)
  1 Washout       3 of 4: p50 under 20%; new lows 55+ (5-day max); RSI under
                  30 (5-day low); adr10 under 0.65. Active for 20 sessions.
  2 Exhaustion    after a washout (last 30 sessions), Nifty 500 retests or
                  undercuts its lowest close of 3-40 sessions ago, but at
                  least 3 of 4 readings are better than on that earlier low
                  day: gauge 10+ points higher, p50 higher, fewer new lows,
                  RSI higher (positive divergence). Active for 10 sessions.
  3 Confirmed     within 20 sessions of stage 2, 2 of 4:
                  gauge above 0; p50 crossed above p200 in the last 10
                  sessions; adr10 above 1.2; a follow-through day in the last
                  10 sessions (Nifty 500 up 1.2%+ on higher turnover, 4+
                  sessions after its 20-day low).

Distribution (top)
  1 Extended      Nifty 500 within 3% of its 6-month high after a strong
                  rally (p50 reached 65%+ or RSI 68+ in the last 20 sessions).
  2 Distribution  near the high (within 3% of the 60-day high), either a
                  negative divergence (Nifty 500 at or above its highest
                  close of 3-40 sessions ago but 3 of 4 readings weaker than
                  on that day: gauge 10+ lower, p50 lower, fewer new highs,
                  RSI lower) or 7+ distribution days in 25 sessions (Nifty
                  500 down 0.2%+ on higher turnover than the day before;
                  5 is normal in this market, 7+ is the top fifth).
  3 Breakdown     within 25 sessions of stage 2, 3 of 4:
                  gauge below 0; p50 crossed below p200 in the last 10
                  sessions; Nifty 500 closed below its 50-day average;
                  adr10 below 0.8.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import sectors as S

LOOK_FROM, LOOK_TO = 3, 40
DIST_DAYS = 7      # heavy-volume down days in 25 sessions (in this data the median is 5)


def _recent(cond: pd.Series, n: int) -> pd.Series:
    return cond.fillna(False).astype(float).rolling(n, min_periods=1).max().astype(bool)


def _prior_extreme(price: pd.Series, lowest: bool) -> tuple[pd.Series, pd.Series]:
    """Value and date index of the lowest/highest close 3-40 sessions ago."""
    vals, locs = [], []
    arr = price.to_numpy()
    for i in range(len(arr)):
        lo, hi = i - LOOK_TO, i - LOOK_FROM
        if lo < 0:
            vals.append(np.nan); locs.append(-1)
            continue
        win = arr[lo:hi + 1]
        if np.all(np.isnan(win)):
            vals.append(np.nan); locs.append(-1)
            continue
        j = int(np.nanargmin(win) if lowest else np.nanargmax(win))
        vals.append(win[j]); locs.append(lo + j)
    return pd.Series(vals, index=price.index), pd.Series(locs, index=price.index)


def _at(series: pd.Series, locs: pd.Series) -> pd.Series:
    arr = series.to_numpy()
    return pd.Series([arr[j] if j >= 0 else np.nan for j in locs], index=series.index)


def build(rg: pd.DataFrame, close: pd.DataFrame, cons: dict, ad: pd.DataFrame | None,
          turnover: pd.Series | None) -> pd.DataFrame:
    n500 = rg["n500"]
    idx = n500.index
    gauge, p50, p200, rsi = rg["internals"], rg["pct_above_50"], rg["pct_above_200"], rg["ew_rsi"]

    tm = [s for s in cons.get("TOTALMKT", pd.DataFrame(columns=["symbol"]))["symbol"] if s in close.columns]
    t = close[tm]
    hi52, lo52 = t.rolling(250, min_periods=200).max(), t.rolling(250, min_periods=200).min()
    new_hi = ((t >= hi52) & hi52.notna()).sum(axis=1).reindex(idx)
    new_lo = ((t <= lo52) & lo52.notna()).sum(axis=1).reindex(idx)
    if ad is not None:
        adr10 = (ad["advances"].rolling(10).sum() / ad["declines"].rolling(10).sum().replace(0, np.nan)).reindex(idx)
    else:
        adr10 = pd.Series(np.nan, index=idx)
    tov = turnover.reindex(idx) if turnover is not None else pd.Series(np.nan, index=idx)
    chg = n500.pct_change() * 100
    sma50 = n500.rolling(50).mean()

    df = pd.DataFrame(index=idx)
    df["new_highs"], df["new_lows"], df["adr10"] = new_hi, new_lo, adr10

    # ---------------------------------------------------------- bottom
    b1_parts = pd.DataFrame({
        "p50 under 20%": p50 < 20,
        "new lows 55+": new_lo.rolling(5).max() >= 55,
        "RSI under 30": rsi.rolling(5).min() < 30,
        "adr10 under 0.65": adr10 < 0.65,
    })
    b1_today = b1_parts.sum(axis=1) >= 3
    b1 = _recent(b1_today, 20)

    plow, ploc = _prior_extreme(n500, lowest=True)
    retest = n500 <= plow * 1.01
    b2_parts = pd.DataFrame({
        "gauge higher": gauge >= _at(gauge, ploc) + 10,
        "p50 higher": p50 > _at(p50, ploc),
        "fewer new lows": new_lo < _at(new_lo, ploc),
        "RSI higher": rsi > _at(rsi, ploc),
    })
    b2_today = _recent(b1_today, 30) & retest & (b2_parts.sum(axis=1) >= 3)
    b2 = _recent(b2_today, 10)

    low20 = n500.rolling(20).min()
    days_from_low = pd.Series([np.nan] * len(idx), index=idx)
    arr = n500.to_numpy()
    for i in range(19, len(arr)):
        w = arr[i - 19:i + 1]
        days_from_low.iloc[i] = 19 - int(np.nanargmin(w))
    ftd = (chg >= 1.2) & (tov > tov.shift(1)) & (days_from_low >= 4)
    cross_up = (p50 > p200) & _recent((p50 < p200).shift(1), 10)
    b3_parts = pd.DataFrame({
        "gauge above 0": gauge > 0,
        "p50 crossed above p200": cross_up,
        "adr10 above 1.2": adr10 > 1.2,
        "follow-through day": _recent(ftd, 10),
    })
    b3_today = _recent(b2_today, 20) & (b3_parts.sum(axis=1) >= 2)

    # ---------------------------------------------------------- top
    near6m = n500 >= n500.rolling(126, min_periods=60).max() * 0.97
    t1_parts = pd.DataFrame({
        "within 3% of 6-month high": near6m,
        "p50 reached 65%+": p50.rolling(20).max() >= 65,
        "RSI reached 68+": rsi.rolling(20).max() >= 68,
    })
    t1_today = near6m & (t1_parts[["p50 reached 65%+", "RSI reached 68+"]].any(axis=1))

    phigh, phloc = _prior_extreme(n500, lowest=False)
    near60 = n500 >= n500.rolling(60).max() * 0.97
    retest_hi = n500 >= phigh * 0.99
    div_parts = pd.DataFrame({
        "gauge lower": gauge <= _at(gauge, phloc) - 10,
        "p50 lower": p50 < _at(p50, phloc),
        "fewer new highs": new_hi < _at(new_hi, phloc),
        "RSI lower": rsi < _at(rsi, phloc),
    })
    neg_div = retest_hi & (div_parts.sum(axis=1) >= 3)
    dist_day = (chg <= -0.2) & (tov > tov.shift(1))
    dist_count = dist_day.astype(float).rolling(25).sum()
    t2_today = near60 & (neg_div | (dist_count >= DIST_DAYS))
    cross_dn = (p50 < p200) & _recent((p50 > p200).shift(1), 10)
    t3_parts = pd.DataFrame({
        "gauge below 0": gauge < 0,
        "p50 crossed below p200": cross_dn,
        "Nifty 500 below its 50-day average": n500 < sma50,
        "adr10 below 0.8": adr10 < 0.8,
    })
    t3_today = _recent(t2_today, 25) & (t3_parts.sum(axis=1) >= 3)

    df["b1"], df["b2"], df["b3"] = b1_today, b2_today, b3_today
    df["t1"], df["t2"], df["t3"] = t1_today, t2_today, t3_today
    df["dist_days_25"] = dist_count
    df["ftd"] = ftd
    df["prior_low_date"] = [idx[j] if j >= 0 else pd.NaT for j in ploc]
    df["prior_high_date"] = [idx[j] if j >= 0 else pd.NaT for j in phloc]
    df.attrs["parts"] = {"b1": b1_parts, "b2": b2_parts, "b3": b3_parts,
                         "t1": t1_parts, "t2": div_parts, "t3": t3_parts}
    return df


STAGES = {
    "bottom": [("b1", "Washout", "Selling has become extreme: the setup, not yet a buy."),
               ("b2", "Exhaustion", "Price retests or undercuts the low but breadth holds up better: sellers are running out."),
               ("b3", "Confirmed", "Breadth turns up and the rally gets follow-through.")],
    "top": [("t1", "Extended", "Index near its high after a strong rally: the setup."),
            ("t2", "Distribution", "Price holds near the high while breadth weakens, or heavy-volume down days pile up."),
            ("t3", "Breakdown", "Breadth turns negative and the index loses its 50-day average.")],
}


def latest(df: pd.DataFrame, rg: pd.DataFrame) -> dict:
    out = {}
    last = df.index[-1]
    for side, stages in STAGES.items():
        items = []
        for key, name, help_ in stages:
            on = df[key].fillna(False)
            days = df.index[on]
            parts = df.attrs["parts"][key].loc[last]
            items.append({
                "key": key, "name": name, "help": help_, "met_today": bool(on.iloc[-1]),
                "last_met": days[-1].date().isoformat() if len(days) else None,
                "sessions_ago": int(len(df) - 1 - df.index.get_loc(days[-1])) if len(days) else None,
                "parts": [{"label": k, "ok": bool(v) if pd.notna(v) else False} for k, v in parts.items()],
            })
        out[side] = items
    r = rg.iloc[-1]
    pl, ph = df["prior_low_date"].iloc[-1], df["prior_high_date"].iloc[-1]
    out["readings"] = {
        "gauge": float(r["internals"]) if pd.notna(r["internals"]) else None,
        "p50": float(r["pct_above_50"]), "p200": float(r["pct_above_200"]),
        "rsi": float(r["ew_rsi"]) if pd.notna(r["ew_rsi"]) else None,
        "new_highs": int(df["new_highs"].iloc[-1]), "new_lows": int(df["new_lows"].iloc[-1]),
        "adr10": float(df["adr10"].iloc[-1]) if pd.notna(df["adr10"].iloc[-1]) else None,
        "dist_days_25": int(df["dist_days_25"].iloc[-1]) if pd.notna(df["dist_days_25"].iloc[-1]) else None,
        "prior_low": pl.date().isoformat() if pd.notna(pl) else None,
        "prior_high": ph.date().isoformat() if pd.notna(ph) else None,
    }
    if pd.notna(pl):
        out["readings"]["at_prior_low"] = {
            "n500": float(rg.at[pl, "n500"]), "gauge": float(rg.at[pl, "internals"]) if pd.notna(rg.at[pl, "internals"]) else None,
            "p50": float(rg.at[pl, "pct_above_50"]), "new_lows": int(df.at[pl, "new_lows"]),
            "rsi": float(rg.at[pl, "ew_rsi"]) if pd.notna(rg.at[pl, "ew_rsi"]) else None}
    out["readings"]["n500"] = float(r["n500"])
    return out


def events(df: pd.DataFrame, b: pd.Series, gap: int = 10) -> list[dict]:
    """First day of each stage spell, with what Nifty 500 did next."""
    f = {"1M": (b.shift(-21) / b - 1) * 100, "3M": (b.shift(-63) / b - 1) * 100}
    names = {k: (side, n) for side, st in STAGES.items() for k, n, _ in st}
    out = []
    for key, (side, name) in names.items():
        on = df[key].fillna(False).astype(bool)
        last_on = None
        for i, (d, v) in enumerate(on.items()):
            if v:
                if last_on is None or i - last_on > gap:
                    out.append({"date": d.date().isoformat(), "side": side, "stage": int(key[1]), "name": name,
                                "n500": float(b[d]), **{k: (float(s[d]) if pd.notna(s.get(d)) else None) for k, s in f.items()}})
                last_on = i
    return sorted(out, key=lambda e: (e["date"], e["stage"]), reverse=True)
