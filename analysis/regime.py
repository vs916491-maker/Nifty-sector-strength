"""Market regime light for positional buying (weeks to months).

Six yes/no checks on the broad market, one point each:
  1. Nifty 500 above its 200-day average
  2. Nifty 500 above its 50-day average
  3. Nifty 500's 50-day average rising (vs 10 sessions ago)
  4. At least half of Nifty 500 stocks above their 50-day average
  5. At least half of Nifty 500 stocks above their 200-day average
  6. More 52-week highs than lows (Total Market stocks, 10-day average)

Light   Green 5-6 points, Amber 3-4, Red 0-2.

Two breadth events are flagged separately because they mark turns:
  Washout        under 20% of Nifty 500 stocks above their 50-day average
  Breadth thrust share above the 50-day average goes from under 20% to over
                 50% within 15 sessions; it stays flagged for 20 sessions.
"""

from __future__ import annotations

import pandas as pd

from . import sectors as S

GREEN, AMBER = 5, 3
WASHOUT = 20
THRUST_FROM, THRUST_TO, THRUST_DAYS, THRUST_KEEP = 20, 50, 15, 20

CHECKS = [
    ("above_200", "Nifty 500 above its 200-day average"),
    ("above_50", "Nifty 500 above its 50-day average"),
    ("ma50_rising", "Nifty 500's 50-day average rising"),
    ("breadth_50", "Half or more of Nifty 500 stocks above their 50-day average"),
    ("breadth_200", "Half or more of Nifty 500 stocks above their 200-day average"),
    ("highs_vs_lows", "More 52-week highs than lows (10-day average)"),
]

GUIDANCE = {
    "Green": "Broad uptrend. Normal position size on A-grade setups.",
    "Amber": "Mixed market. A-grade setups only, at reduced size; expect more false breakouts.",
    "Red": "Weak market. Keep new positions small and A-grade only, and build a watchlist of stocks holding near their highs.",
}


def series(idx: pd.DataFrame, close: pd.DataFrame, cons: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Daily regime table: one column per check, points, light, washout, thrust."""
    n500 = idx["NIFTY500"]
    s50, s200 = S.sma(n500.to_frame(), 50).iloc[:, 0], S.sma(n500.to_frame(), 200).iloc[:, 0]

    members = [s for s in cons.get("NIFTY500", pd.DataFrame(columns=["symbol"]))["symbol"] if s in close.columns]
    px = close[members]
    a50, a200 = S.sma(px, 50), S.sma(px, 200)
    pct50 = (px > a50).astype(float).where(a50.notna()).mean(axis=1) * 100
    pct200 = (px > a200).astype(float).where(a200.notna()).mean(axis=1) * 100

    tm = [s for s in cons.get("TOTALMKT", pd.DataFrame(columns=["symbol"]))["symbol"] if s in close.columns]
    t = close[tm]
    hi, lo = t.rolling(250, min_periods=200).max(), t.rolling(250, min_periods=200).min()
    net_hl = (((t >= hi) & hi.notna()).sum(axis=1) - ((t <= lo) & lo.notna()).sum(axis=1)).rolling(10).mean()

    df = pd.DataFrame(index=close.index)
    df["above_200"] = n500 > s200
    df["above_50"] = n500 > s50
    df["ma50_rising"] = s50 > s50.shift(10)
    df["breadth_50"] = pct50 >= 50
    df["breadth_200"] = pct200 >= 50
    df["highs_vs_lows"] = net_hl > 0
    ok = s200.notna() & pct200.notna() & net_hl.notna()
    df["points"] = df[[k for k, _ in CHECKS]].sum(axis=1).where(ok)
    df["light"] = df["points"].map(lambda p: None if pd.isna(p) else "Green" if p >= GREEN else "Amber" if p >= AMBER else "Red")
    df["pct_above_50"] = pct50
    df["pct_above_200"] = pct200
    df["net_highs_lows_10d"] = net_hl
    df["washout"] = pct50 < WASHOUT
    thrust_day = (pct50 > THRUST_TO) & (pct50.rolling(THRUST_DAYS).min() < THRUST_FROM)
    df["thrust_day"] = thrust_day
    df["thrust_active"] = thrust_day.rolling(THRUST_KEEP, min_periods=1).max().astype(bool)
    return df


def latest(df: pd.DataFrame, days: int = 260) -> dict:
    last = df.iloc[-1]
    thrusts = df.index[df["thrust_day"]]
    washouts = df["washout"]
    # start of the current washout spell, if any
    since = None
    if bool(last["washout"]):
        run = washouts[::-1]
        stop = run[~run].index
        since = (run.index[run.index.get_loc(stop[0]) - 1] if len(stop) else run.index[-1]).date().isoformat()
    lights = df["light"].dropna()
    changed = lights.ne(lights.shift()).cumsum()
    light_since = lights[changed == changed.iloc[-1]].index[0].date().isoformat() if len(lights) else None
    tail = df.iloc[-days:]
    return {
        "date": df.index[-1].date().isoformat(),
        "light": last["light"],
        "light_since": light_since,
        "points": int(last["points"]) if pd.notna(last["points"]) else None,
        "max_points": len(CHECKS),
        "checks": [{"key": k, "label": label, "ok": bool(last[k])} for k, label in CHECKS],
        "guidance": GUIDANCE.get(last["light"]),
        "pct_above_50": float(last["pct_above_50"]),
        "pct_above_200": float(last["pct_above_200"]),
        "net_highs_lows_10d": float(last["net_highs_lows_10d"]) if pd.notna(last["net_highs_lows_10d"]) else None,
        "washout": bool(last["washout"]),
        "washout_since": since,
        "thrust_active": bool(last["thrust_active"]),
        "last_thrust": thrusts[-1].date().isoformat() if len(thrusts) else None,
        "history": {"dates": [d.date().isoformat() for d in tail.index],
                    "light": tail["light"].tolist(), "points": tail["points"].tolist()},
        "rules": {"green": GREEN, "amber": AMBER, "washout": WASHOUT,
                  "thrust": f"under {THRUST_FROM}% to over {THRUST_TO}% within {THRUST_DAYS} sessions"},
    }
