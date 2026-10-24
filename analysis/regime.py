"""Market regime light for positional buying (weeks to months).

Six yes/no checks on the broad market, one point each:
  1. Nifty 500 above its 200-day average
  2. Nifty 500 above its 50-day average
  3. Nifty 500's 50-day average rising (vs 10 sessions ago)
  4. At least half of Nifty 500 stocks above their 50-day average
  5. At least half of Nifty 500 stocks above their 200-day average
  6. More 52-week highs than lows (Total Market stocks, 10-day average)

Light   from the 5-session average of the points, with a buffer so it does
        not flip back and forth: it turns Green at 5+, leaves Green below 4;
        turns Red below 2.5, leaves Red at 3.5+; Amber in between. (Without
        the buffer the light changed 33 times in 15 months; with it, 12.)
        The cost is a few sessions of delay at real turns, which the
        internals gauge below is meant to cover.

Market internals gauge, -100 to +100 (average of five parts, each -1..+1)
  A/D line       advance-decline line vs its 50-day average, scaled by how
                 far it usually strays
  Breadth trend  10-session change in the share of Nifty 500 stocks above
                 their 50-day average
  RSI trend      RSI(14) of Nifty 500 Equal Weight vs its 20-day average
  Highs - lows   52-week highs minus lows (10-day average)
  Equal weight   Nifty 500 Equal Weight vs Nifty 500 over 20 sessions (the
                 average stock vs the big ones)

Early warnings (the pattern of a market stalling while internals weaken)
  Topping warning   Nifty 500 within 3% of its 60-day high on 12+ of the
                    last 15 sessions, while the A/D line is below its 50-day
                    average, RSI's 20-day average is lower than 10 sessions
                    ago and breadth is falling
  Bottoming signal  the mirror image near the 60-day low (within 4% on 9+
                    of 15 sessions, A/D line above its average, RSI and
                    breadth rising), or - while Nifty 500 is 7%+ below its
                    6-month high - the gauge climbing above 0 within 30
                    sessions of being at -50 or lower

Two breadth events are flagged separately because they mark turns:
  Washout        under 20% of Nifty 500 stocks above their 50-day average
  Breadth thrust share above the 50-day average goes from under 20% to over
                 50% within 15 sessions; it stays flagged for 20 sessions.
"""

from __future__ import annotations

import pandas as pd

import numpy as np

from . import sectors as S

GREEN, AMBER = 5, 3
LEAVE_GREEN, ENTER_RED, LEAVE_RED, SMOOTH = 4, 2.5, 3.5, 5
WASHOUT = 20
THRUST_FROM, THRUST_TO, THRUST_DAYS, THRUST_KEEP = 20, 50, 15, 20

CHECKS = [
    ("above_200", "{name} above its 200-day average"),
    ("above_50", "{name} above its 50-day average"),
    ("ma50_rising", "{name}'s 50-day average rising"),
    ("breadth_50", "Half or more of {name} stocks above their 50-day average"),
    ("breadth_200", "Half or more of {name} stocks above their 200-day average"),
    ("highs_vs_lows", "More 52-week highs than lows (10-day average)"),
]
# The same rules run for Nifty 50: breadth from its 50 stocks, highs/lows and
# advances/declines from those 50 stocks, RSI from Nifty 50 Equal Weight.
BENCHES = {
    "NIFTY500": {"name": "Nifty 500", "breadth": "NIFTY500", "highs_lows": "TOTALMKT",
                 "equal_weight": "Nifty500 Equal Weight", "turnover": "Nifty 500"},
    "NIFTY50": {"name": "Nifty 50", "breadth": "NIFTY50", "highs_lows": "NIFTY50",
                "equal_weight": "NIFTY50 Equal Weight", "turnover": "Nifty 50"},
}

GUIDANCE = {
    "Green": "Broad uptrend. Normal position size on A-grade setups.",
    "Amber": "Mixed market. A-grade setups only, at reduced size; expect more false breakouts.",
    "Red": "Weak market. Keep new positions small and A-grade only, and build a watchlist of stocks holding near their highs.",
}


def _buffered_light(avg: pd.Series) -> pd.Series:
    out, cur = [], None
    for v in avg:
        if pd.isna(v):
            out.append(None)
            continue
        if cur is None:
            cur = "Green" if v >= GREEN else "Amber" if v >= ENTER_RED else "Red"
        elif cur == "Green" and v < LEAVE_GREEN:
            cur = "Amber" if v >= ENTER_RED else "Red"
        elif cur == "Amber":
            cur = "Green" if v >= GREEN else "Red" if v < ENTER_RED else "Amber"
        elif cur == "Red" and v >= LEAVE_RED:
            cur = "Green" if v >= GREEN else "Amber"
        out.append(cur)
    return pd.Series(out, index=avg.index)


def internals(n500: pd.Series, ew: pd.Series, ad_line: pd.Series, pct50: pd.Series, net_hl: pd.Series,
              hl_universe: int = 750) -> pd.DataFrame:
    ew = ew.reindex(n500.index)
    ad = ad_line.reindex(n500.index)
    gap = ad - ad.rolling(50).mean()
    rsi = S.rsi(ew.to_frame()).iloc[:, 0]
    rsi_avg = rsi.rolling(20).mean()
    ratio = ew / n500
    parts = pd.DataFrame({
        "ad_line": (gap / gap.rolling(250, min_periods=100).std() / 2).clip(-1, 1),
        "breadth_trend": ((pct50 - pct50.shift(10)) / 20).clip(-1, 1),
        "rsi_trend": ((rsi - rsi_avg) / 10).clip(-1, 1),
        "highs_lows": np.tanh(net_hl / (20 * hl_universe / 750)),
        "equal_weight": ((ratio / ratio.shift(20) - 1) * 100 / 2).clip(-1, 1),
    })
    out = parts.add_prefix("i_")
    out["internals"] = (parts.mean(axis=1, skipna=False) * 100).rolling(3).mean()
    out["ew_rsi"], out["ew_rsi_avg"] = rsi, rsi_avg
    out["ad_line"], out["ad_mean50"] = ad, ad.rolling(50).mean()

    hi60, lo60 = n500.rolling(60).max(), n500.rolling(60).min()
    ad_below = ad < ad.rolling(50).mean()
    falling = (rsi_avg < rsi_avg.shift(10)) & (pct50 < pct50.shift(10))
    rising = (rsi_avg > rsi_avg.shift(10)) & (pct50 > pct50.shift(10))
    near_hi = (n500 >= hi60 * 0.97).rolling(15).sum() >= 12
    near_lo = (n500 <= lo60 * 1.04).rolling(15).sum() >= 9
    in_correction = n500 <= n500.rolling(120).max() * 0.93
    turn_up = (out["internals"] > 0) & (out["internals"].rolling(30).min() <= -50) & in_correction
    out["topping"] = (near_hi & ad_below & falling).fillna(False)
    out["bottoming"] = ((near_lo & ~ad_below & rising) | turn_up).fillna(False)
    return out


def series(idx: pd.DataFrame, close: pd.DataFrame, cons: dict[str, pd.DataFrame],
           ew: pd.Series | None = None, ad_line: pd.Series | None = None, bench: str = "NIFTY500") -> pd.DataFrame:
    """Daily regime table: one column per check, points, light, washout, thrust,
    internals gauge and early warnings, for Nifty 500 (default) or Nifty 50."""
    cfg = BENCHES[bench]
    n500 = idx[bench]
    s50, s200 = S.sma(n500.to_frame(), 50).iloc[:, 0], S.sma(n500.to_frame(), 200).iloc[:, 0]

    members = [s for s in cons.get(cfg["breadth"], pd.DataFrame(columns=["symbol"]))["symbol"] if s in close.columns]
    px = close[members]
    a50, a200 = S.sma(px, 50), S.sma(px, 200)
    pct50 = (px > a50).astype(float).where(a50.notna()).mean(axis=1) * 100
    pct200 = (px > a200).astype(float).where(a200.notna()).mean(axis=1) * 100

    tm = [s for s in cons.get(cfg["highs_lows"], pd.DataFrame(columns=["symbol"]))["symbol"] if s in close.columns]
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
    df["n500"] = n500
    df["points_avg"] = df["points"].rolling(SMOOTH).mean()
    df["light"] = _buffered_light(df["points_avg"])
    df["pct_above_50"] = pct50
    df["pct_above_200"] = pct200
    df["net_highs_lows_10d"] = net_hl
    df["washout"] = pct50 < WASHOUT
    thrust_day = (pct50 > THRUST_TO) & (pct50.rolling(THRUST_DAYS).min() < THRUST_FROM)
    df["thrust_day"] = thrust_day
    df["thrust_active"] = thrust_day.rolling(THRUST_KEEP, min_periods=1).max().astype(bool)
    if ew is not None and ad_line is not None and len(ew) and len(ad_line):
        df = df.join(internals(n500, ew, ad_line, pct50, net_hl, max(len(tm), 1)))
    df.attrs.update({"bench": bench, "name": cfg["name"], "hl_universe": len(tm)})
    return df


INTERNAL_PARTS = [
    ("i_ad_line", "A/D line vs its 50-day average"),
    ("i_breadth_trend", "Share of stocks above their 50-day average, 10-day change"),
    ("i_rsi_trend", "RSI of {name} Equal Weight vs its 20-day average"),
    ("i_highs_lows", "52-week highs minus lows"),
    ("i_equal_weight", "Average stock (equal weight) vs {name}"),
]


def warning_events(df: pd.DataFrame, col: str, gap: int = 15) -> list[pd.Timestamp]:
    """First day of each warning spell; spells closer than `gap` sessions merge."""
    on = df[col].fillna(False).astype(bool)
    out, last_on = [], None
    for i, (d, v) in enumerate(on.items()):
        if v:
            if last_on is None or i - last_on > gap:
                out.append(d)
            last_on = i
    return out


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
    name = df.attrs.get("name", "Nifty 500")
    return {
        "bench": df.attrs.get("bench", "NIFTY500"), "name": name,
        "date": df.index[-1].date().isoformat(),
        "light": last["light"],
        "light_since": light_since,
        "points": int(last["points"]) if pd.notna(last["points"]) else None,
        "max_points": len(CHECKS),
        "checks": [{"key": k, "label": label.format(name=name), "ok": bool(last[k])} for k, label in CHECKS],
        "guidance": GUIDANCE.get(last["light"]),
        "pct_above_50": float(last["pct_above_50"]),
        "pct_above_200": float(last["pct_above_200"]),
        "net_highs_lows_10d": float(last["net_highs_lows_10d"]) if pd.notna(last["net_highs_lows_10d"]) else None,
        "washout": bool(last["washout"]),
        "washout_since": since,
        "thrust_active": bool(last["thrust_active"]),
        "last_thrust": thrusts[-1].date().isoformat() if len(thrusts) else None,
        "history": {"dates": [d.date().isoformat() for d in tail.index],
                    "light": tail["light"].tolist(), "points": tail["points"].tolist(),
                    "internals": tail["internals"].tolist() if "internals" in tail else None,
                    "n500": tail["n500"].tolist()},
        "internals": None if "internals" not in df else {
            "value": float(last["internals"]) if pd.notna(last["internals"]) else None,
            "value_10d_ago": float(df["internals"].iloc[-11]) if len(df) > 11 and pd.notna(df["internals"].iloc[-11]) else None,
            "parts": [{"key": k, "label": label.format(name=name), "value": float(last[k] * 100) if pd.notna(last[k]) else None}
                      for k, label in INTERNAL_PARTS],
            "topping": bool(last["topping"]), "bottoming": bool(last["bottoming"]),
            "last_topping": (lambda e: e[-1].date().isoformat() if e else None)(warning_events(df, "topping")),
            "last_bottoming": (lambda e: e[-1].date().isoformat() if e else None)(warning_events(df, "bottoming")),
        },
        "rules": {"green": GREEN, "amber": AMBER, "washout": WASHOUT,
                  "thrust": f"under {THRUST_FROM}% to over {THRUST_TO}% within {THRUST_DAYS} sessions"},
    }
