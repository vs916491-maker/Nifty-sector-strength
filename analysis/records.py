"""Prediction Records: the turning-point cycle's full history, for the website tab of that name.

For each benchmark (Nifty 500, Nifty 50), from the first day the readings are valid:
  chart    closes, 50-day average, the cycle phase of each day, phase-change and stage markers,
           and the real tops and bottoms (turns of SWING_PCT or more on closing prices)
  swings   each real top/bottom, the first matching signal within MATCH_SESSIONS (Bottom
           confirmed for a bottom, Breakdown for a top), how late it came and how far price had
           moved, plus the early warning (washout before a bottom, up move weakening near a top)
  signals  every phase change with the index 1 and 3 months later and a result:
           bottom signal: False bottom if the index fell 5%+ below it within 3 months, else Good;
           breakdown: Whipsaw if the top failed within 15 sessions, else Good/Wrong by the
           3-month (or 1-month) return; up move weakened: Good warning if the next month fell
  phases   each spell of each phase (start, end, sessions, index change start-to-end, and its
           highest and lowest close vs the start) and their averages
  score    bottoms/tops caught, false bottoms, wrong breakdowns

Built from the same turning.build() / regime output the Overview uses, so it follows the live rules.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .turning import chop_series

SWING_PCT = 6.0       # a real top/bottom = a turn of this % or more on closing prices
MATCH_SESSIONS = 45   # a signal within this many sessions after the turn counts as catching it
WHIPSAW_SESSIONS = 15
CHOP_MERGE_GAP = 5    # choppy spells this close together are drawn as one zone
CHOP_MIN_SESSIONS = 3 # shorter spells are not drawn
BAD_VERDICTS = ("False bottom", "Whipsaw", "Wrong", "Early")
BOTTOM_EVENTS = ("Bottom confirmed",)
PHASE_NAMES = {"bottom": "Seller exhaustion", "up": "Up continuation", "top": "Distribution", "down": "Down continuation"}


def _zigzag(arr: np.ndarray, th: float) -> tuple[list[tuple[str, int]], tuple[str, int]]:
    """Swing highs (H) and lows (L): an extreme is confirmed once price turns th from it."""
    piv, mode, e = [], None, 0
    for i in range(1, len(arr)):
        if mode is None:
            if arr[i] >= arr[e] * (1 + th):
                mode = "up"; piv.append(("L", e)); e = i
            elif arr[i] <= arr[e] * (1 - th):
                mode = "down"; piv.append(("H", e)); e = i
        elif mode == "up":
            if arr[i] > arr[e]:
                e = i
            elif arr[i] <= arr[e] * (1 - th):
                piv.append(("H", e)); mode = "down"; e = i
        else:
            if arr[i] < arr[e]:
                e = i
            elif arr[i] >= arr[e] * (1 + th):
                piv.append(("L", e)); mode = "up"; e = i
    return piv, ("H" if mode == "up" else "L", e)


def build(rg: pd.DataFrame, tp: pd.DataFrame) -> dict:
    n = rg["n500"]
    arr = n.to_numpy()
    dates = n.index
    valid = rg["light_checks" if "light_checks" in rg else "light"].first_valid_index()
    if valid is None:
        return {}
    v = dates.get_loc(valid)
    d = lambda i: dates[i].date().isoformat()
    r1 = lambda x: round(float(x), 1) if pd.notna(x) else None
    fwd = lambda i, k: round(float((arr[i + k] / arr[i] - 1) * 100), 2) if i + k < len(arr) else None

    evs = [(dates.get_loc(t), e) for t, e in tp["phase_event"].dropna().items() if t >= valid]
    signals = []
    for j, (i, e) in enumerate(evs):
        s = {"date": d(i), "event": e, "phase": tp["phase"].iloc[i], "price": r1(arr[i]), "f21": fwd(i, 21), "f63": fwd(i, 63)}
        nxt = evs[j + 1] if j + 1 < len(evs) else None
        if e in BOTTOM_EVENTS:
            ahead = arr[i + 1:i + 64]
            s["dd63"] = round(float((ahead.min() / arr[i] - 1) * 100), 2) if len(ahead) else None
            s["verdict"] = "Too recent" if s["f21"] is None else ("False bottom" if s["dd63"] is not None and s["dd63"] <= -5 else "Good")
        elif e == "Top confirmed":
            r = s["f63"] if s["f63"] is not None else s["f21"]
            whip = nxt is not None and nxt[1] == "Top failed" and nxt[0] - i <= WHIPSAW_SESSIONS
            s["verdict"] = "Whipsaw" if whip else ("Too recent" if r is None else ("Good" if r < 0 else "Wrong"))
        elif e == "Up trend weakened":
            s["verdict"] = "Too recent" if s["f21"] is None else ("Good warning" if s["f21"] < 0 else "Early")
        signals.append(s)

    # real tops and bottoms, matched to the first signal after them
    off = max(0, v - 60)
    piv, last = _zigzag(arr[off:], SWING_PCT / 100)
    piv = [(k, i + off) for k, i in piv if i + off >= v - 20]
    swings = []
    for k, i in piv:
        want = BOTTOM_EVENTS if k == "L" else ("Top confirmed",)
        hit = [(j, e) for j, e in evs if e in want and 0 <= j - i <= MATCH_SESSIONS]
        warn_ev = ("Washout", "Washout without a confirmed top") if k == "L" else ("Up trend weakened", "Extended without a confirmed bottom")
        warn = [(j, e) for j, e in evs if e in warn_ev and -30 <= j - i <= MATCH_SESSIONS]
        j = hit[0][0] if hit else None
        swings.append({"kind": "Bottom" if k == "L" else "Top", "date": d(i), "price": r1(arr[i]),
                       "signal": d(j) if j is not None else None, "signal_price": r1(arr[j]) if j is not None else None,
                       "lag": int(j - i) if j is not None else None,
                       "gap": round(float((arr[j] / arr[i] - 1) * 100), 2) if j is not None else None,
                       "warn": d(warn[0][0]) if warn else None, "warn_event": warn[0][1] if warn else None,
                       "warn_lag": int(warn[0][0] - i) if warn else None})

    # phase spells
    ph = tp["phase"].to_numpy()
    spells, start = [], v
    for i in range(v + 1, len(ph) + 1):
        if i == len(ph) or ph[i] != ph[start]:
            seg = arr[start:i]
            spells.append({"phase": ph[start], "start": d(start), "end": d(i - 1), "sessions": int(i - start),
                           "change_pct": round(float((arr[i - 1] / arr[start] - 1) * 100), 2),
                           "high_pct": round(float((seg.max() / arr[start] - 1) * 100), 2),
                           "low_pct": round(float((seg.min() / arr[start] - 1) * 100), 2), "open": i == len(ph)})
            start = i
    phase_avg = {}
    for p in ("bottom", "up", "top", "down"):
        done = [s for s in spells if s["phase"] == p and not s["open"]]
        phase_avg[p] = {"name": PHASE_NAMES[p], "count": len(done),
                        "avg_sessions": round(float(np.mean([s["sessions"] for s in done])), 1) if done else None,
                        "avg_change": round(float(np.mean([s["change_pct"] for s in done])), 2) if done else None,
                        "up_share": round(100 * float(np.mean([s["change_pct"] > 0 for s in done])), 0) if done else None,
                        "avg_high": round(float(np.mean([s["high_pct"] for s in done])), 2) if done else None,
                        "avg_low": round(float(np.mean([s["low_pct"] for s in done])), 2) if done else None}

    # chart series from the first valid day
    marks = [{"date": s["date"], "event": s["event"], "price": s["price"]} for s in signals]
    start = v
    for i in range(v + 1, len(ph) + 1):
        if i == len(ph) or ph[i] != ph[start]:
            if ph[start] in ("bottom", "top"):
                col = "b2" if ph[start] == "bottom" else "t2"
                hit = np.flatnonzero(tp[col].to_numpy()[start:i])
                if len(hit):
                    j = start + int(hit[0])
                    marks.append({"date": d(j), "event": "Exhaustion" if col == "b2" else "Distribution", "price": r1(arr[j])})
            start = i
    chart = {"dates": [d(i) for i in range(v, len(arr))], "close": [r1(x) for x in arr[v:]],
             "sma20": [r1(x) for x in tp["sma20"].iloc[v:]], "sma50": [r1(x) for x in tp["sma50"].iloc[v:]],
             "phase": tp["phase"].iloc[v:].tolist(), "marks": sorted(marks, key=lambda m: m["date"]),
             "swings": [{"kind": s["kind"], "date": s["date"], "price": s["price"]} for s in swings if s["date"] >= d(v)],
             "anchor": None, "fail": None}

    bots = [s for s in swings if s["kind"] == "Bottom" and s["date"] >= d(v)]
    tops = [s for s in swings if s["kind"] == "Top" and s["date"] >= d(v)]
    cb, ct = [s for s in bots if s["signal"]], [s for s in tops if s["signal"]]
    bd = [s for s in signals if s["event"] == "Top confirmed"]
    bs = [s for s in signals if s["event"] in BOTTOM_EVENTS]
    mean = lambda xs: round(float(np.mean(xs)), 1) if xs else None
    score = {"from": d(v), "to": d(len(arr) - 1), "sessions": int(len(arr) - v),
             "bottoms": len(bots), "bottoms_caught": len(cb), "bottom_lag": mean([s["lag"] for s in cb]), "bottom_gap": mean([s["gap"] for s in cb]),
             "tops": len(tops), "tops_caught": len(ct), "top_lag": mean([s["lag"] for s in ct]), "top_gap": mean([s["gap"] for s in ct]),
             "bottom_signals": len(bs), "false_bottoms": sum(s.get("verdict") == "False bottom" for s in bs),
             "breakdowns": len(bd), "bad_breakdowns": sum(s.get("verdict") in ("Whipsaw", "Wrong") for s in bd)}
    return {"score": score, "chart": chart, "chop": _chop(n, v, signals, d, r1), "swings": swings, "signals": signals[::-1],
            "spells": spells[::-1], "phase_avg": phase_avg,
            "last_extreme": {"kind": last[0], "date": d(last[1] + off), "price": r1(arr[last[1] + off])},
            "rules": {"swing_pct": SWING_PCT, "match_sessions": MATCH_SESSIONS, "whipsaw_sessions": WHIPSAW_SESSIONS}}


def _chop(n: pd.Series, v: int, signals: list, d, r1) -> dict:
    """Choppy / congestion zones (live chop rules, turning.chop_series) on price + 50 EMA, and whether each
    trend-change signal came inside a choppy zone."""
    cs = chop_series(n)
    st = cs["state"].to_numpy()
    arr = n.to_numpy()
    zones = []
    for kind in ("chop", "congestion"):
        idx = [i for i in range(v, len(st)) if st[i] == kind]
        spans = []
        for i in idx:
            gap = CHOP_MERGE_GAP if kind == "chop" else 1
            if spans and i - spans[-1][1] <= gap:
                spans[-1][1] = i
            else:
                spans.append([i, i])
        for a, b in spans:
            if kind == "chop" and b - a + 1 < CHOP_MIN_SESSIONS:
                continue
            seg = arr[a:b + 1]
            zones.append({"kind": kind, "start": d(a), "end": d(b), "sessions": int(b - a + 1),
                          "lo": r1(seg.min()), "hi": r1(seg.max())})
    zones.sort(key=lambda z: z["start"])
    names = {"chop": "Choppy", "congestion": "Congestion", "trend": "EMA trending", "push": "Quick push",
             "break": "Broke out of congestion", None: "Not choppy"}
    sig = []
    for s in signals[::-1]:
        if not s.get("verdict"):
            continue
        z = next((z for z in zones if z["start"] <= s["date"] <= z["end"]), None)
        i = n.index.get_loc(pd.Timestamp(s["date"]))
        sig.append({"date": s["date"], "event": s["event"], "price": s["price"], "verdict": s["verdict"],
                    "bad": s["verdict"] in BAD_VERDICTS, "zone": z["kind"] if z else None,
                    "state": names.get(st[i], "Not choppy")})
    done = [s for s in sig if s["verdict"] != "Too recent"]
    cnt = lambda bad, inz: sum(1 for s in done if s["bad"] == bad and (s["zone"] == "chop") == inz)
    return {"dates": [d(i) for i in range(v, len(arr))], "close": [r1(x) for x in arr[v:]],
            "ema50": [r1(x) for x in cs["ema"].iloc[v:]], "zones": zones, "signals": sig,
            "summary": {"bad_in": cnt(True, True), "bad_out": cnt(True, False), "good_in": cnt(False, True), "good_out": cnt(False, False),
                        "chop_days": int(sum(1 for i in range(v, len(st)) if st[i] == "chop")), "days": int(len(st) - v)}}
