"""Positional entry setups (holding weeks to months), from daily data.

Every setup needs a stock in a long-term uptrend ("trend filter"):
  close above its 200-day average, 50-day above 200-day, 200-day rising
  (vs a month ago), within 25% of its 52-week high, RS rating 70+.

Breakout        today's close clears the highest high of the previous 40
                sessions (the pivot) on volume at least 1.5x its 50-day
                average, closing in the upper half of the day's range. The
                base under the pivot is no deeper than 30%, and the close is
                no more than 5% above the pivot (not chasing).
Tight base      price coiling near the highs: 10-session range within 8% of
                the close, 10-day volume at most 80% of the 50-day average,
                within 15% of the 52-week high. Buy only if the price trades
                above the pivot (10-session high); the setup expires after 10
                sessions without a trigger.
Pullback        a recent leader (52-week high within the last 60 sessions)
                pulled back 8-25% to its rising 50-day average on light
                volume, held above it, and closed up on the day.

Stop            lowest low of the setup's recent sessions (10 for breakout
                and tight base, 5 for pullback, and the 50-day average for a
                pullback), less 0.5%, but never more than 8% below entry.
Exit            stop hit; or a close below the 50-day average; or 120
                sessions (about 6 months). Profits are not capped, so
                winners can run for months.

Grade           A = RS rating 90+ or the RS line at a 52-week high; B = the
                rest. In the Phase 6 test A-grade setups were profitable and
                B-grade setups lost money, so the site lists A first.
RS at high      the stock's relative-strength line vs Nifty 500 made a new
                52-week high in the last 5 sessions. When this happens while
                the market is falling, the stock is often a future leader.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import sectors as S

TREND = {"near_high_pct": 25, "min_rs_rating": 70}
BREAKOUT = {"lookback": 40, "vol_mult": 1.5, "max_depth": 30, "max_above_pivot": 5}
TIGHT = {"days": 10, "max_range": 8, "vol_ratio": 0.8, "near_high_pct": 15, "trigger_days": 10}
PULLBACK = {"high_within": 60, "min_off": 8, "max_off": 25, "touch": 1.02}
STOP = {"buffer": 0.995, "max_risk": 8}
EXIT = {"max_days": 120}
SETUP_NAMES = {"breakout": "Breakout", "tight": "Tight base", "pullback": "Pullback"}


A_GRADE_RS = 90


def grade(rs: float, rs_high: bool) -> str:
    return "A" if (rs == rs and rs >= A_GRADE_RS) or rs_high else "B"


def rs_rating(close: pd.DataFrame) -> pd.DataFrame:
    """Daily IBD-style RS rating 1-99 across the universe."""
    parts, weights = [], []
    for n, w in ((63, 0.4), (126, 0.2), (189, 0.2), (250, 0.2)):
        r = close.pct_change(n, fill_method=None)
        parts.append(r.fillna(0) * w)
        weights.append(r.notna() * w)
    perf = sum(parts) / sum(weights).replace(0, np.nan)
    return perf.rank(axis=1, pct=True) * 98 + 1


def indicators(st: dict[str, pd.DataFrame], bench: pd.Series) -> dict[str, pd.DataFrame]:
    o, h, l, c, v = st["open"], st["high"], st["low"], st["close"], st["volume"]
    s50, s200 = S.sma(c, 50), S.sma(c, 200)
    hi52 = h.rolling(250, min_periods=120).max()
    rs = c.div(bench.reindex(c.index), axis=0)
    ind = {
        "open": o, "high": h, "low": l, "close": c, "volume": v,
        "s50": s50, "s200": s200, "hi52": hi52,
        "vol50": v.rolling(50, min_periods=40).mean(),
        "rs_rating": rs_rating(c),
        "from_high": (c / hi52 - 1) * 100,
        "rs_at_high": (rs >= rs.rolling(250, min_periods=120).max() * 0.999).rolling(5, min_periods=1).max().astype(bool),
    }
    ind["trend_ok"] = ((c > s200) & (s50 > s200) & (s200 > s200.shift(21))
                       & (ind["from_high"] >= -TREND["near_high_pct"])
                       & (ind["rs_rating"] >= TREND["min_rs_rating"]))
    return ind


def _stop(entry: pd.DataFrame, raw: pd.DataFrame) -> pd.DataFrame:
    floor = entry * (1 - STOP["max_risk"] / 100)
    return np.maximum(raw * STOP["buffer"], floor)


def detect(ind: dict[str, pd.DataFrame]) -> dict[str, dict[str, pd.DataFrame]]:
    """Boolean setup tables plus pivot/stop levels (dates x symbols)."""
    h, l, c, v = ind["high"], ind["low"], ind["close"], ind["volume"]
    tr = ind["trend_ok"]
    out = {}

    # breakout
    B = BREAKOUT
    pivot = h.shift(1).rolling(B["lookback"]).max()
    base_low = l.shift(1).rolling(B["lookback"]).min()
    depth = (1 - base_low / pivot) * 100
    rng = (h - l).replace(0, np.nan)
    upper_half = ((c - l) / rng) >= 0.5
    brk = (tr & (c > pivot) & (v >= B["vol_mult"] * ind["vol50"]) & upper_half
           & (depth <= B["max_depth"]) & (c <= pivot * (1 + B["max_above_pivot"] / 100)))
    out["breakout"] = {"on": brk.fillna(False), "pivot": pivot,
                       "stop": _stop(c, l.rolling(10).min())}

    # tight base (trigger = trade above the 10-session high)
    T = TIGHT
    hiN, loN = h.rolling(T["days"]).max(), l.rolling(T["days"]).min()
    tight = (tr & ((hiN - loN) / c * 100 <= T["max_range"])
             & (v.rolling(T["days"]).mean() <= T["vol_ratio"] * ind["vol50"])
             & (ind["from_high"] >= -T["near_high_pct"]) & ~brk.fillna(False))
    out["tight"] = {"on": tight.fillna(False), "pivot": hiN, "stop": _stop(hiN, loN)}

    # pullback to a rising 50-day average
    P = PULLBACK
    s50 = ind["s50"]
    recent_high = (h >= ind["hi52"] * 0.999).rolling(P["high_within"], min_periods=1).max().astype(bool)
    off = -ind["from_high"]
    pb = (tr & (s50 > s50.shift(10)) & recent_high & (off >= P["min_off"]) & (off <= P["max_off"])
          & (l.rolling(3).min() <= s50 * P["touch"]) & (c > s50) & (c > c.shift(1))
          & (v.rolling(5).mean() < ind["vol50"]))
    out["pullback"] = {"on": pb.fillna(False), "pivot": c,
                       "stop": _stop(c, np.minimum(l.rolling(5).min(), s50))}
    return out


def simulate(ind: dict[str, pd.DataFrame], sets: dict, regime_light: pd.Series | None = None) -> pd.DataFrame:
    """Walk every historical setup forward with the entry and exit rules.

    Breakout and pullback buy at the next session's open. Tight base buys
    when the price first trades above the pivot within 10 sessions, at the
    higher of that day's open and the pivot. A stock is not re-entered while
    a trade in it is open.
    """
    o, h, l, c, s50 = (ind[k].to_numpy() for k in ("open", "high", "low", "close", "s50"))
    dates, syms = ind["close"].index, ind["close"].columns
    n = len(dates)
    events = []
    for kind, d in sets.items():
        on = d["on"].to_numpy()
        piv, stp = d["pivot"].to_numpy(), d["stop"].to_numpy()
        ii, jj = np.nonzero(on)
        for i, j in zip(ii, jj):
            events.append((i, j, kind, piv[i, j], stp[i, j]))
    events.sort()
    busy_until = {}
    trades = []
    for i, j, kind, piv, stp in events:
        if busy_until.get(j, -1) >= i:
            continue
        # entry
        if kind == "tight":
            e = None
            for k in range(i + 1, min(n, i + 1 + TIGHT["trigger_days"])):
                if np.isfinite(h[k, j]) and h[k, j] > piv:
                    e, entry = k, max(o[k, j], piv)
                    break
            if e is None:
                continue
        else:
            e = i + 1
            if e >= n or not np.isfinite(o[e, j]):
                continue
            entry = o[e, j]
        stop = max(stp, entry * (1 - STOP["max_risk"] / 100))
        if not (np.isfinite(stop) and stop < entry):
            continue
        risk = entry - stop
        # walk forward
        x, exit_px, why = None, None, None
        for k in range(e, min(n, e + EXIT["max_days"] + 1)):
            if not np.isfinite(c[k, j]):
                continue
            if l[k, j] <= stop:
                x, why = k, "Stop"
                exit_px = min(o[k, j], stop) if k > e else stop
                break
            if k > e and np.isfinite(s50[k, j]) and c[k, j] < s50[k, j]:
                x, exit_px, why = k, c[k, j], "Closed below 50-day"
                break
            if k - e >= EXIT["max_days"]:
                x, exit_px, why = k, c[k, j], "Time (120 sessions)"
                break
        status = "Closed"
        if x is None:
            x = n - 1
            while x > e and not np.isfinite(c[x, j]):
                x -= 1
            exit_px, why, status = c[x, j], "Still open", "Open"
        busy_until[j] = x
        trades.append({
            "symbol": syms[j], "setup": kind, "signal_date": dates[i], "entry_date": dates[e],
            "exit_date": dates[x], "entry": entry, "stop": stop, "exit": exit_px,
            "return_pct": (exit_px / entry - 1) * 100, "r": (exit_px - entry) / risk,
            "risk_pct": risk / entry * 100, "days": x - e, "exit_reason": why, "status": status,
            "light": regime_light.get(dates[i]) if regime_light is not None else None,
        })
    return pd.DataFrame(trades)


def today(ind: dict, sets: dict, stocks_df: dict, eligible: set[str]) -> list[dict]:
    """Setups on the latest session for eligible stocks."""
    last = ind["close"].index[-1]
    out = []
    for kind, d in sets.items():
        on = d["on"].loc[last]
        for sym in on.index[on.to_numpy()]:
            if sym not in eligible:
                continue
            c = float(ind["close"].at[last, sym])
            piv = float(d["pivot"].at[last, sym])
            stop = float(d["stop"].at[last, sym])
            entry_ref = piv if kind == "tight" else c
            stop = max(stop, entry_ref * (1 - STOP["max_risk"] / 100))
            rs, rsh = float(ind["rs_rating"].at[last, sym]), bool(ind["rs_at_high"].at[last, sym])
            out.append({
                "symbol": sym, "setup": kind, "close": c, "grade": grade(rs, rsh),
                "rs_rating": rs, "rs_at_high": rsh,
                "trigger": piv if kind == "tight" else None,
                "entry_ref": entry_ref, "stop": stop,
                "risk_pct": (entry_ref - stop) / entry_ref * 100,
                "vol_ratio": float(ind["volume"].at[last, sym] / ind["vol50"].at[last, sym])
                if ind["vol50"].at[last, sym] else None,
                "s50": float(ind["s50"].at[last, sym]),
                "from_high": float(ind["from_high"].at[last, sym]),
            })
    order = {"breakout": 0, "pullback": 1, "tight": 2}
    out.sort(key=lambda x: (x["grade"], order[x["setup"]], -(stocks_df.get(x["symbol"], {}).get("score") or 0)))
    return out


def leaders(ind: dict, eligible: set[str], near_high: float = 15) -> list[str]:
    """Stocks whose RS line is at a 52-week high while price is near its own
    high and in a long-term uptrend: the watchlist for a weak market."""
    last = ind["close"].index[-1]
    ok = (ind["rs_at_high"].loc[last] & (ind["from_high"].loc[last] >= -near_high)
          & (ind["close"].loc[last] > ind["s200"].loc[last]))
    syms = [s for s in ok.index[ok.fillna(False).to_numpy()] if s in eligible]
    return sorted(syms, key=lambda s: -ind["rs_rating"].at[last, s])


def summarise(trades: pd.DataFrame) -> dict:
    def block(t: pd.DataFrame) -> dict:
        closed = t[t["status"] == "Closed"]
        if closed.empty:
            return {"trades": int(len(t)), "closed": 0}
        win = closed["r"] > 0
        gains, losses = closed.loc[win, "return_pct"], closed.loc[~win, "return_pct"]
        return {
            "trades": int(len(t)), "closed": int(len(closed)), "open": int((t["status"] == "Open").sum()),
            "win_rate": float(win.mean() * 100),
            "avg_return": float(closed["return_pct"].mean()),
            "median_return": float(closed["return_pct"].median()),
            "avg_r": float(closed["r"].mean()),
            "avg_win": float(gains.mean()) if len(gains) else None,
            "avg_loss": float(losses.mean()) if len(losses) else None,
            "profit_factor": float(gains.sum() / -losses.sum()) if len(losses) and losses.sum() < 0 else None,
            "avg_days": float(closed["days"].mean()),
            "avg_days_win": float(closed.loc[win, "days"].mean()) if win.any() else None,
        }
    if trades.empty:
        return {"all": {"trades": 0, "closed": 0}, "by_setup": {}, "by_light": {}}
    return {
        "all": block(trades),
        "by_setup": {SETUP_NAMES[k]: block(g) for k, g in trades.groupby("setup")},
        "by_light": {k: block(g) for k, g in trades.groupby("light") if k},
        "by_setup_light": {f"{SETUP_NAMES[a]}|{b}": block(g) for (a, b), g in trades.groupby(["setup", "light"]) if b},
        "first_signal": trades["signal_date"].min().date().isoformat(),
        "last_signal": trades["signal_date"].max().date().isoformat(),
    }
