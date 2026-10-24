"""Overall market breadth from daily closes.

Advance / decline   every NSE EQ/BE stock that traded, close vs previous
                    close (data/meta/advance_decline.csv, from the bhavcopy)
A/D line            running total of (advances - declines), with its 50-day average
A/D ratio (10-day)  advances / declines summed over the last 10 sessions
% above 50/200-DMA  share of Nifty 500 stocks above their own averages
                    (split/bonus-adjusted closes)
52-week highs/lows  Total Market stocks closing at a 52-week high / low
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import sectors as S

AD_PATH = Path(__file__).resolve().parent.parent / "data" / "meta" / "advance_decline.csv"


def build(idx: pd.DataFrame, close: pd.DataFrame, cons: dict[str, pd.DataFrame],
          days: int = 260) -> dict:
    out: dict = {}
    n500 = [s for s in cons.get("NIFTY500", pd.DataFrame(columns=["symbol"]))["symbol"]
            if s in close.columns]
    px = close[n500]
    pct50 = (px > S.sma(px, 50)).astype(float).where(S.sma(px, 50).notna()).mean(axis=1) * 100
    pct200 = (px > S.sma(px, 200)).astype(float).where(S.sma(px, 200).notna()).mean(axis=1) * 100

    tm = [s for s in cons.get("TOTALMKT", pd.DataFrame(columns=["symbol"]))["symbol"]
          if s in close.columns]
    tpx = close[tm]
    hi = tpx.rolling(250, min_periods=200).max()
    lo = tpx.rolling(250, min_periods=200).min()
    new_hi = ((tpx >= hi) & hi.notna()).sum(axis=1)
    new_lo = ((tpx <= lo) & lo.notna()).sum(axis=1)

    frame = pd.DataFrame({"nifty500": idx["NIFTY500"], "pct_above_50": pct50,
                          "pct_above_200": pct200, "new_highs": new_hi, "new_lows": new_lo})

    if AD_PATH.exists():
        ad = pd.read_csv(AD_PATH, parse_dates=["date"]).set_index("date").sort_index()
        ad["net"] = ad["advances"] - ad["declines"]
        ad["ad_line"] = ad["net"].cumsum()
        ad["ad_mean50"] = ad["ad_line"].rolling(50).mean()
        ad["ad_ratio_10"] = (ad["advances"].rolling(10).sum()
                             / ad["declines"].rolling(10).sum().replace(0, pd.NA))
        frame = frame.join(ad[["advances", "declines", "unchanged", "net",
                               "ad_line", "ad_mean50", "ad_ratio_10"]], how="left")

    frame = frame.iloc[-days:]
    if "ad_line" in frame:
        # rebase so the visible window starts at 0
        base = frame["ad_line"].dropna().iloc[0]
        frame["ad_line"] = frame["ad_line"] - base
        frame["ad_mean50"] = frame["ad_mean50"] - base

    out["dates"] = [d.date().isoformat() for d in frame.index]
    out["series"] = {c: frame[c].astype(float).tolist() for c in frame.columns}
    last = frame.iloc[-1]
    prev20 = frame.iloc[-21] if len(frame) > 21 else frame.iloc[0]
    out["latest"] = {
        "date": out["dates"][-1],
        **{c: (float(last[c]) if pd.notna(last[c]) else None) for c in frame.columns},
        "pct_above_50_20d_ago": float(prev20["pct_above_50"]),
        "pct_above_200_20d_ago": float(prev20["pct_above_200"]),
    }
    out["universe"] = {"pct_above": "Nifty 500", "highs_lows": "Nifty Total Market",
                       "advance_decline": "All NSE EQ/BE stocks"}
    return out
