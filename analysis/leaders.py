"""Next leaders and sector rotation during a market correction.

Leadership often changes hands in a correction: the old leaders lag the next
rally, and the stocks and sectors that fell least and recover first lead it.
This module measures that, using the market's current decline:

Decline     peak = Nifty 500's highest close in the last 126 sessions (about
            6 months); low = its lowest close since that peak. Treated as a
            correction when the low is 7% or more below the peak.

Next-leader score 0-100 (percentile ranks across eligible stocks)
  Held up        35%  stock's return from the market's peak to its low,
                      minus Nifty 500's (fell least = best)
  Off the low    25%  return since the market's low minus Nifty 500's; only
                      counted once the low is 5+ sessions old (before that
                      its weight goes to the others)
  RS line        20%  relative-strength line vs its own 52-week high; a new
                      high while the price is still 5%+ below its high
                      ("RS leads price") is the classic early sign
  Accumulation   20%  up-day vs down-day volume and delivery % on up days vs
                      down days, since the peak (at least 20 sessions)
  Stocks more than 30% below their 52-week high are left out.

Sector rotation (sectoral and thematic indices, vs Nifty 500)
  Same held-up / off-the-low / RS-line ranks within each tab, plus a status:
  Emerging       top third on the next-leader ranks and RS momentum rising
                 or outperforming since the low
  Steady leader  top 5 by sector score at the market's peak and still in
                 the top third
  Fading leader  top 5 at the peak, now in the bottom half and not
                 outperforming since the low
  Old leader, bouncing
                 top 5 at the peak, fell more than the market, but
                 outperforming since the low
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import sectors as S

PEAK_WINDOW = 126
MIN_DECLINE = 7.0
MIN_LOW_AGE = 5
MAX_FROM_HIGH = 30.0
WEIGHTS = {"held_up": 0.35, "off_low": 0.25, "rs_line": 0.20, "accumulation": 0.20}
SECTOR_WEIGHTS = {"held_up": 0.45, "off_low": 0.30, "rs_line": 0.25}


def decline(bench: pd.Series, i: int | None = None) -> dict:
    """The market's current decline as of position i (default: latest)."""
    i = len(bench) - 1 if i is None else i
    win = bench.iloc[max(0, i - PEAK_WINDOW + 1): i + 1]
    peak = win.idxmax()
    low = bench.loc[peak: bench.index[i]].idxmin()
    now = bench.index[i]
    fall = (bench[low] / bench[peak] - 1) * 100
    bounce = (bench[now] / bench[low] - 1) * 100
    age = int(bench.index.get_loc(now) - bench.index.get_loc(low))
    return {"peak": peak, "low": low, "now": now, "fall": fall, "bounce": bounce, "low_age": age,
            "from_peak": (bench[now] / bench[peak] - 1) * 100,
            "in_correction": fall <= -MIN_DECLINE,
            "off_low_valid": age >= MIN_LOW_AGE}


def _rank(s: pd.Series) -> pd.Series:
    return s.rank(pct=True) * 100


def _blend(parts: dict[str, pd.Series], weights: dict[str, float]) -> pd.Series:
    num = sum(parts[k].fillna(0) * w for k, w in weights.items() if k in parts)
    den = sum(parts[k].notna() * w for k, w in weights.items() if k in parts)
    return num / den.replace(0, np.nan)


def stock_scores(st: dict[str, pd.DataFrame], bench: pd.Series, d: dict, symbols: list[str]) -> pd.DataFrame:
    """Next-leader score for the given symbols, as of d['now']."""
    cols = [s for s in symbols if s in st["close"].columns]
    c = st["close"].loc[: d["now"], cols]
    h = st["high"].loc[: d["now"], cols]
    v = st["volume"].loc[: d["now"], cols]
    dp = st["deliv_pct"].loc[: d["now"], cols]
    b = bench.loc[: d["now"]]
    peak, low, now = d["peak"], d["low"], d["now"]

    held = (c.loc[low] / c.loc[peak] - 1) * 100 - (b[low] / b[peak] - 1) * 100
    off = (c.loc[now] / c.loc[low] - 1) * 100 - (b[now] / b[low] - 1) * 100

    rs = c.div(b, axis=0)
    rs_hi = rs.rolling(250, min_periods=120).max().iloc[-1]
    rs_vs_high = (rs.iloc[-1] / rs_hi - 1) * 100                     # 0 = at its high
    hi52 = h.rolling(250, min_periods=120).max().iloc[-1]
    from_high = (c.iloc[-1] / hi52 - 1) * 100
    rs_leads = (rs_vs_high >= -0.5) & (from_high <= -5)

    # accumulation since the peak (at least the last 20 sessions)
    start = min(c.index.get_loc(peak), len(c) - 20)
    cc, vv, dd = c.iloc[start:], v.iloc[start:], dp.iloc[start:]
    chg = cc.diff()
    up_vol, dn_vol = vv.where(chg > 0).sum(), vv.where(chg < 0).sum()
    updown = up_vol / dn_vol.replace(0, np.nan)
    deliv_gap = dd.where(chg > 0).mean() - dd.where(chg < 0).mean()

    parts = {
        "held_up": _rank(held) if d["fall"] < 0 else pd.Series(np.nan, index=cols),
        "off_low": _rank(off) if d["off_low_valid"] else pd.Series(np.nan, index=cols),
        "rs_line": (100 + rs_vs_high * 100 / 15).clip(0, 100),        # 100 at its high, 0 at 15% below
        "accumulation": _rank(updown) * 0.6 + _rank(deliv_gap).fillna(50) * 0.4,
    }
    score = _blend(parts, WEIGHTS)
    df = pd.DataFrame({"score": score, "held_up_pct": held, "since_low_pct": off,
                       "rs_vs_high": rs_vs_high, "rs_leads_price": rs_leads, "from_high": from_high,
                       "updown_volume": updown, "deliv_gap": deliv_gap})
    for k, p in parts.items():
        df[f"c_{k}"] = p
    df.loc[from_high < -MAX_FROM_HIGH, "score"] = np.nan
    return df


def sector_scores(idx: pd.DataFrame, groups: dict[str, list[str]], d: dict,
                  rank: pd.DataFrame, momentum: pd.DataFrame, ratio: pd.DataFrame) -> dict[str, dict]:
    b = idx["NIFTY500"]
    peak, low, now = d["peak"], d["low"], d["now"]
    out = {}
    wk = ratio.index[ratio.index <= now]
    for g, keys in groups.items():
        px = idx.loc[:now, keys]
        held = (px.loc[low] / px.loc[peak] - 1) * 100 - (b[low] / b[peak] - 1) * 100
        off = (px.loc[now] / px.loc[low] - 1) * 100 - (b[now] / b[low] - 1) * 100
        rs = px.div(b.loc[:now], axis=0)
        rs_vs_high = (rs.iloc[-1] / rs.rolling(250, min_periods=120).max().iloc[-1] - 1) * 100
        parts = {"held_up": _rank(held) if d["fall"] < 0 else pd.Series(np.nan, index=keys),
                 "off_low": _rank(off) if d["off_low_valid"] else pd.Series(np.nan, index=keys),
                 "rs_line": (100 + rs_vs_high * 100 / 15).clip(0, 100)}
        score = _blend(parts, SECTOR_WEIGHTS)
        nl_rank = score.rank(ascending=False, method="min")
        n = len(keys)
        for k in keys:
            mom = momentum.at[wk[-1], k] if len(wk) else np.nan
            mom_prev = momentum.at[wk[-2], k] if len(wk) > 1 else np.nan
            was_top = bool(rank.at[peak, k] <= 5) if pd.notna(rank.at[peak, k]) else False
            top_third = nl_rank[k] <= np.ceil(n / 3)
            off_up = bool(d["off_low_valid"] and off[k] > 0)
            if was_top and top_third:
                status = "Steady leader"
            elif was_top and nl_rank[k] > n / 2 and not off_up:
                status = "Fading leader"
            elif was_top and off_up:
                status = "Old leader, bouncing"
            elif not was_top and top_third and (mom >= 100 or (pd.notna(mom_prev) and mom > mom_prev) or off_up):
                status = "Emerging"
            else:
                status = None
            out[k] = {"score": score[k], "nl_rank": nl_rank[k], "held_up_pct": held[k],
                      "since_low_pct": off[k], "rs_vs_high": rs_vs_high[k],
                      "rank_at_peak": rank.at[peak, k], "rank_now": rank.at[now, k],
                      "quadrant": S.quadrant(ratio.at[wk[-1], k], mom) if len(wk) else None,
                      "rs_momentum": mom, "status": status}
    return out


def describe(d: dict) -> dict:
    return {"peak": d["peak"].date().isoformat(), "low": d["low"].date().isoformat(),
            "fall": d["fall"], "bounce": d["bounce"], "from_peak": d["from_peak"], "low_age": d["low_age"],
            "in_correction": bool(d["in_correction"]), "off_low_valid": bool(d["off_low_valid"])}
