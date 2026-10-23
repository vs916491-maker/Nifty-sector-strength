"""Sector strength scoring and Relative Rotation Graph (RRG).

All calculations use end-of-day closes. For every benchmark (Nifty 500 by
default, Nifty 50 as an alternative) and every trading day it computes:

RS line          sector close / benchmark close
RS-Ratio (RRG)   weekly RS vs its 10-week average, x100, lightly smoothed.
                 >100: the sector is outperforming its recent relative trend.
RS-Momentum      week-on-week change of RS-Ratio, x100.
                 >100: relative strength is improving.
Quadrants        Leading (>100, >100), Weakening (>100, <100),
                 Lagging (<100, <100), Improving (<100, >100)

Composite score 0-100 (weights in WEIGHTS):
  rs_trend      RS vs its 50-day average (ranked), RS 50-day average rising,
                RS above its 150-day average
  rs_momentum   10-day change of RS (ranked), 10-day change of the
                "RS vs 50-day average" gap (ranked) - catches turns early
  excess_return 1-month and 3-month return minus the benchmark's (ranked)
  trend         price above 50/150/200-day averages, 50 > 200, 50 rising
  breadth       % of the sector's stocks above their own 50-day average

"Ranked" parts are percentile ranks among the sectors in the same tab
(sectoral or thematic), so scores compare sectors with each other.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

WEIGHTS = {"rs_trend": 0.30, "rs_momentum": 0.20, "excess_return": 0.20,
           "trend": 0.20, "breadth": 0.10}
RRG_WINDOW = 10      # weeks
RRG_SMOOTH = 3       # weeks (EMA span)
TAIL_WEEKS = 8


def sma(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return df.rolling(n, min_periods=n).mean()


def rsi(df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    delta = df.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + gain / loss)


def pct_rank(df: pd.DataFrame) -> pd.DataFrame:
    """Cross-sectional percentile rank per day, 0-100."""
    return df.rank(axis=1, pct=True) * 100


def flag(cond: pd.DataFrame, valid: pd.DataFrame) -> pd.DataFrame:
    """Boolean -> 0/100, NaN where the input is not available yet."""
    return cond.astype(float).where(valid.notna()) * 100


def breadth(closes: pd.DataFrame, members: dict[str, list[str]], n: int = 50) -> pd.DataFrame:
    """% of each sector's (current) constituents trading above their n-DMA."""
    avg = sma(closes, n)
    above = (closes > avg).astype(float).where(avg.notna())
    out = {}
    for key, symbols in members.items():
        cols = [s for s in symbols if s in above.columns]
        out[key] = above[cols].mean(axis=1) * 100 if cols else np.nan
    return pd.DataFrame(out, index=closes.index)


def weekly_last(df: pd.DataFrame) -> pd.DataFrame:
    """Last trading day of each week (Mon-Fri), keeping the real date.
    The current, unfinished week is included as of its latest day."""
    weeks = df.index.to_period("W-FRI")
    return df.groupby(weeks).tail(1)


def rrg(sector: pd.DataFrame, bench: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame]:
    wk = weekly_last(sector.join(bench.rename("__bench")))
    rs = wk[sector.columns].div(wk["__bench"], axis=0)
    ratio = 100 * rs / rs.rolling(RRG_WINDOW, min_periods=RRG_WINDOW).mean()
    ratio = ratio.ewm(span=RRG_SMOOTH, adjust=False).mean()
    momentum = 100 * ratio / ratio.shift(1)
    return ratio, momentum


def quadrant(ratio: float, momentum: float) -> str | None:
    if np.isnan(ratio) or np.isnan(momentum):
        return None
    if ratio >= 100:
        return "Leading" if momentum >= 100 else "Weakening"
    return "Improving" if momentum >= 100 else "Lagging"


def score_group(px: pd.DataFrame, bench: pd.Series, brd: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Daily component scores and composite score for one group of sectors."""
    rs = px.div(bench, axis=0)
    rs50, rs150 = sma(rs, 50), sma(rs, 150)
    rs_gap = rs / rs50 - 1
    rs_trend = (pct_rank(rs_gap) * 0.5
                + flag(rs50 > rs50.shift(10), rs50.shift(10)) * 0.25
                + flag(rs > rs150, rs150) * 0.25)
    rs_mom = (pct_rank(rs.pct_change(10)) * 0.5
              + pct_rank(rs_gap - rs_gap.shift(10)) * 0.5)
    excess = (pct_rank(rs.pct_change(21)) * 0.5 + pct_rank(rs.pct_change(63)) * 0.5)
    s50, s150, s200 = sma(px, 50), sma(px, 150), sma(px, 200)
    trend = (flag(px > s50, s50) + flag(px > s150, s150) + flag(px > s200, s200)
             + flag(s50 > s200, s200) + flag(s50 > s50.shift(10), s50.shift(10))) / 5
    comps = {"rs_trend": rs_trend, "rs_momentum": rs_mom, "excess_return": excess,
             "trend": trend, "breadth": brd[px.columns]}
    total = sum(comps[k].fillna(50) * w for k, w in WEIGHTS.items())
    # no score until the slowest input (150-day RS average) exists
    total = total.where(rs150.notna())
    comps["score"] = total
    return comps


def analyse(idx: pd.DataFrame, groups: dict[str, list[str]], bench_key: str,
            brd: pd.DataFrame) -> dict:
    """Everything the website needs for one benchmark."""
    bench = idx[bench_key]
    keys = [k for g in groups.values() for k in g]
    px = idx[keys]
    last = px.index[-1]
    ratio, momentum = rrg(px, bench)

    comps: dict[str, pd.DataFrame] = {}
    for g_keys in groups.values():
        part = score_group(px[g_keys], bench, brd)
        for name, frame in part.items():
            comps[name] = frame if name not in comps else comps[name].join(frame)

    score = comps["score"]
    rank = pd.DataFrame(index=score.index, columns=score.columns, dtype=float)
    for g_keys in groups.values():
        rank[g_keys] = score[g_keys].rank(axis=1, ascending=False, method="min")

    rs = px.div(bench, axis=0)
    ret = lambda df, n: (df.iloc[-1] / df.iloc[-1 - n] - 1) * 100  # noqa: E731
    s50, s150, s200 = sma(px, 50), sma(px, 150), sma(px, 200)
    rsi14 = rsi(px)
    hi52 = px.rolling(250, min_periods=200).max()
    week_ago = score.index[-6] if len(score) > 6 else score.index[0]

    rows = {}
    for k in keys:
        rows[k] = {
            "score": score.at[last, k],
            "rank": rank.at[last, k],
            "rank_1w_ago": rank.at[week_ago, k],
            "score_1w_ago": score.at[week_ago, k],
            "quadrant": quadrant(ratio[k].iloc[-1], momentum[k].iloc[-1]),
            "rs_ratio": ratio[k].iloc[-1],
            "rs_momentum": momentum[k].iloc[-1],
            "excess_1w": ret(rs[k], 5), "excess_1m": ret(rs[k], 21),
            "excess_3m": ret(rs[k], 63), "excess_6m": ret(rs[k], 126),
            "return_1w": ret(px[k], 5), "return_1m": ret(px[k], 21),
            "return_3m": ret(px[k], 63), "return_6m": ret(px[k], 126),
            "close": px[k].iloc[-1],
            "above_50": bool(px[k].iloc[-1] > s50[k].iloc[-1]),
            "above_150": bool(px[k].iloc[-1] > s150[k].iloc[-1]),
            "above_200": bool(px[k].iloc[-1] > s200[k].iloc[-1]),
            "pct_from_52w_high": (px[k].iloc[-1] / hi52[k].iloc[-1] - 1) * 100,
            "rsi14": rsi14[k].iloc[-1],
            "breadth_50": brd[k].iloc[-1],
            "components": {c: comps[c].at[last, k] for c in WEIGHTS},
        }
    tails = {k: [{"date": d.date().isoformat(), "x": ratio.at[d, k], "y": momentum.at[d, k]}
                 for d in ratio.index[-TAIL_WEEKS:]] for k in keys}
    return {"rows": rows, "tails": tails, "score": score, "rank": rank, "rs": rs}
