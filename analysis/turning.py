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
                  sessions (with p50 at 25%+); adr10 above 1.2; a follow-through day in the last
                  10 sessions (Nifty 500 up 1.2%+ on higher turnover, 4+
                  sessions after its 20-day low).

Distribution (top)
  1 Extended      Nifty 500 within 3% of its 3-month high (EXT_LOOK; was
                  6-month until 8 Nov 2026) after a strong rally (p50 reached
                  65%+ or RSI 68+ in the last 20 sessions, or a 5%+ bounce off
                  the 60-day low, EXT_BOUNCE: tops inside a range count too).
  2 Distribution  after an extended reading (stage 1 in the last 30
                  sessions), near the high (within 3% of the 60-day high), either a
                  negative divergence (Nifty 500 at or above its highest
                  close of 3-40 sessions ago but 3 of 4 readings weaker than
                  on that day: gauge 10+ lower, p50 lower, fewer new highs,
                  RSI lower) or 7+ distribution days in 25 sessions (Nifty
                  500 down 0.2%+ on higher turnover than the day before;
                  5 is normal in this market, 7+ is the top fifth). The
                  count restarts when seller exhaustion confirms a bottom.
  3 Breakdown     within 25 sessions of stage 2, 3 of 4:
                  gauge below 0; p50 crossed below p200 in the last 10
                  sessions; Nifty 500 closed below its 50-day average;
                  adr10 below 0.8.

The cycle (8 Nov 2026): only one box is live at a time.
  Seller exhaustion --Confirmed--> Up continuation --up weakens--> Distribution
  --Breakdown--> Down continuation --Washout--> Seller exhaustion
  Up continuation   up conditions (3 of 4): index above its 20-day and 50-day
                    average, 50%+ of stocks above their 50-day average, gauge
                    above 0. Once the up move has been proven (3 of 4 on some
                    day), it ends when 2+ of the 4 fail for UP_WEAK_DAYS days
                    in a row. Before it is proven, only a failure can end it.
  Down continuation mirror conditions (index below both averages, under 50%
                    of stocks above their 50-day, gauge below 0); it ends only
                    at the next Washout, which starts Seller exhaustion again.
  Failed moves      a close below the low the bottom was made at (lowest close
                    of the 40 sessions up to Confirmed), or a new Washout,
                    sends Up back to Seller exhaustion ("Exhaustion failed";
                    the website's Trend continuation box then shows
                    "Exhaustion failed: downtrend continues" until a new
                    bottom is confirmed); a close above the high
                    the top was made at sends Down back to Distribution.
  Shortcuts         a Washout while Distribution is live (the market fell
                    without a Breakdown signal) moves to Seller exhaustion; an
                    Extended reading while Seller exhaustion is live (it rose
                    without a Confirmed signal) moves to Distribution.
A stage only counts while its tracker is live (Washout also counts on the day
it ends Down continuation).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import sectors as S

LOOK_FROM, LOOK_TO = 3, 40
DIST_DAYS = 7      # heavy-volume down days in 25 sessions (in this data the median is 5)
EXT_LOOK, EXT_LOOK_NAME = 63, "3-month"    # Extended: within 3% of the highest close of this many sessions
                                           # (6-month until 8 Nov 2026; 3-month also sees lower highs, e.g. Nifty 50 Aug 2026)
EXT_BOUNCE, EXT_BOUNCE_LOOK = 5, 60        # ...or a bounce of this % off the lowest close of this many sessions (0 = off; on since 8 Nov 2026)
AD_DIV = False      # (test) Stage 2 also when the market-wide A/D line falls while the index holds near its high
AD_DIV_LOOK = 20    # ...A/D line lower than this many sessions ago, and below its 50-day average; index at/above its level then
AD_UP_END = 0       # (test, 0 = off) Up continuation also ends, into Distribution, after this many days in a row of A/D divergence near the high
DIV_NEAR_HIGH = 3   # Distribution divergence counts while the index is within this % of the earlier high (was 1; 3 since 8 Nov 2026)
T1_ACTIVE = 30     # stage 2 (distribution) needs stage 1 (extended) in the last 30 sessions


UP_WEAK_DAYS = 3   # Up continuation ends after this many days in a row with 2+ of 4 up conditions failing
RECLAIM_DAYS = 0   # (test, 0 = off) Down continuation also ends, into Up, after this many days in a row with 3+ of 4 up conditions
BD_CONFIRM = 0     # (test) Breakdown needs: 0 = the day's reading; 1 = two days in a row; 2 = a close below the lowest close since Distribution went live
PHASES = ["bottom", "up", "top", "down"]


def _phases(b1, b3, t1, t3, up_n, close: pd.Series, start: str = "bottom", addiv=None) -> pd.DataFrame:
    """Walk the cycle day by day. Returns, per day: phase at the close, phase
    before the day, the session the phase began, pivots, the weak-day count and
    whether the up move has been proven, plus the event text on change days."""
    n = len(close)
    arr = close.to_numpy()
    b1, b3, t1, t3 = (np.asarray(pd.Series(x).fillna(False), bool) for x in (b1, b3, t1, t3))
    up_n = np.asarray(up_n, float)
    addiv = np.zeros(n, bool) if addiv is None else np.asarray(pd.Series(addiv).fillna(False), bool)
    adrun = 0
    ph, since, pl, phh, weak, proven, strong = start, 0, np.nan, np.nan, 0, False, 0
    rows = []
    for i in range(n):
        strong = strong + 1 if up_n[i] >= 3 else 0
        adrun = adrun + 1 if addiv[i] else 0
        prev, ev = ph, None
        if ph == "bottom":
            if t1[i] and not b3[i]:
                ph, ev = "top", "Extended without a confirmed bottom"
            elif b3[i]:
                ph, ev = "up", "Bottom confirmed"
                pl, weak, proven = float(np.nanmin(arr[max(0, i - LOOK_TO):i + 1])), 0, up_n[i] >= 3
        elif ph == "up":
            if arr[i] < pl or b1[i]:
                ph, ev = "bottom", "Exhaustion failed: new low" if arr[i] < pl else "Exhaustion failed: new washout"
            else:
                proven = proven or up_n[i] >= 3
                weak = weak + 1 if (proven and up_n[i] <= 2) else 0
                if weak >= UP_WEAK_DAYS:
                    ph, ev = "top", "Up trend weakened"
                elif AD_UP_END and adrun >= AD_UP_END:
                    ph, ev = "top", "A/D divergence: breadth fading near the high"
        elif ph == "top":
            if b1[i] and not t3[i]:
                ph, ev = "bottom", "Washout without a confirmed top"
            elif t3[i] and (BD_CONFIRM == 0 or (BD_CONFIRM == 1 and i > 0 and t3[i - 1])
                            or (BD_CONFIRM == 2 and i > since and arr[i] < np.nanmin(arr[since:i]))):
                ph, ev = "down", "Top confirmed"
                phh = float(np.nanmax(arr[max(0, i - LOOK_TO):i + 1]))
        elif ph == "down":
            if arr[i] > phh:
                ph, ev = "top", "Top failed"
            elif b1[i]:
                ph, ev = "bottom", "Washout"
            elif RECLAIM_DAYS and strong >= RECLAIM_DAYS:
                ph, ev = "up", "Trend reclaimed without a washout"
                pl, weak, proven = float(np.nanmin(arr[max(0, i - LOOK_TO):i + 1])), 0, True
        if ph != prev:
            since = i
        rows.append((ph, prev, since, pl if ph == "up" else np.nan, phh if ph == "down" else np.nan,
                     weak if ph == "up" else 0, proven if ph == "up" else False, ev))
    return pd.DataFrame(rows, index=close.index,
                        columns=["phase", "phase_prev", "phase_since", "pivot_low", "pivot_high", "weak_days", "proven", "phase_event"])


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
          turnover: pd.Series | None, hl_key: str = "TOTALMKT", ad_market: pd.DataFrame | None = None) -> pd.DataFrame:
    n500 = rg["n500"]
    idx = n500.index
    gauge, p50, p200, rsi = rg["internals"], rg["pct_above_50"], rg["pct_above_200"], rg["ew_rsi"]

    tm = [s for s in cons.get(hl_key, pd.DataFrame(columns=["symbol"]))["symbol"] if s in close.columns]
    # 55 new lows out of ~750 Total Market stocks; scaled for a smaller universe (4 of 50)
    lows_thr = max(3, int(round(55 * len(tm) / 750)))
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
        f"new lows {lows_thr}+": new_lo.rolling(5).max() >= lows_thr,
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
    # a crossing deep in washout territory (both lines near 15%) is noise, so p50 must be 25%+
    cross_up = (p50 > p200) & (p50 >= 25) & _recent((p50 < p200).shift(1), 10)
    b3_parts = pd.DataFrame({
        "gauge above 0": gauge > 0,
        "p50 crossed above p200": cross_up,
        "adr10 above 1.2": adr10 > 1.2,
        "follow-through day": _recent(ftd, 10),
    })
    b3_today = _recent(b2_today, 20) & (b3_parts.sum(axis=1) >= 2)
    sma20 = n500.rolling(20).mean()
    up_parts = pd.DataFrame({
        "above 20-day average": n500 > sma20,
        "above 50-day average": n500 > sma50,
        "50%+ of stocks above their 50-day average": p50 >= 50,
        "internals gauge above 0": gauge > 0,
    })
    dn_parts = pd.DataFrame({
        "below 20-day average": n500 < sma20,
        "below 50-day average": n500 < sma50,
        "under 50% of stocks above their 50-day average": p50 < 50,
        "internals gauge below 0": gauge < 0,
    })

    # ---------------------------------------------------------- top
    near_hi = n500 >= n500.rolling(EXT_LOOK, min_periods=min(60, EXT_LOOK)).max() * 0.97
    bounce = (n500 / n500.rolling(EXT_BOUNCE_LOOK).min() - 1) * 100 >= EXT_BOUNCE if EXT_BOUNCE else pd.Series(False, index=idx)
    t1_parts = pd.DataFrame({
        f"within 3% of {EXT_LOOK_NAME} high": near_hi,
        "p50 reached 65%+": p50.rolling(20).max() >= 65,
        "RSI reached 68+": rsi.rolling(20).max() >= 68,
    })
    if EXT_BOUNCE:
        t1_parts[f"bounced {EXT_BOUNCE}%+ from its {EXT_BOUNCE_LOOK}-day low"] = bounce
    t1_today = near_hi & (t1_parts.iloc[:, 1:].any(axis=1))

    phigh, phloc = _prior_extreme(n500, lowest=False)
    near60 = n500 >= n500.rolling(60).max() * 0.97
    retest_hi = n500 >= phigh * (1 - DIV_NEAR_HIGH / 100)
    div_parts = pd.DataFrame({
        "gauge lower": gauge <= _at(gauge, phloc) - 10,
        "p50 lower": p50 < _at(p50, phloc),
        "fewer new highs": new_hi < _at(new_hi, phloc),
        "RSI lower": rsi < _at(rsi, phloc),
    })
    neg_div = retest_hi & (div_parts.sum(axis=1) >= 3)
    dist_day = (chg <= -0.2) & (tov > tov.shift(1))
    # count restarts on the first day of each seller-exhaustion confirmation: heavy
    # down days before a confirmed bottom are capitulation, not distribution at a top
    b3_start = b3_today & ~_recent(b3_today.shift(1), 10)
    cs = np.concatenate([[0.0], dist_day.fillna(False).astype(float).cumsum().to_numpy()])
    starts = np.flatnonzero(b3_start.to_numpy())
    cnt = np.full(len(idx), np.nan)
    for i in range(24, len(idx)):
        k = np.searchsorted(starts, i, side="right")
        frm = max(i - 24, starts[k - 1] if k else 0)
        cnt[i] = cs[i + 1] - cs[frm]
    dist_count = pd.Series(cnt, index=idx)
    # A/D divergence: the broad market (all NSE stocks) stops participating while the index holds up
    adm = ad_market if ad_market is not None else ad
    if adm is not None:
        adl = (adm["advances"] - adm["declines"]).cumsum().reindex(idx).ffill()
        ad_div = (adl < adl.rolling(50).mean()) & (adl < adl.shift(AD_DIV_LOOK)) & (n500 >= n500.shift(AD_DIV_LOOK))
    else:
        ad_div = pd.Series(False, index=idx)
    ad_div_raw = (ad_div.fillna(False) & near60).astype(bool)
    ad_div = ad_div.fillna(False) & AD_DIV
    t2_today = _recent(t1_today, T1_ACTIVE) & near60 & (neg_div | (dist_count >= DIST_DAYS) | ad_div)
    if AD_DIV:
        div_parts["market A/D line falling while the index holds up"] = ad_div
    cross_dn = (p50 < p200) & _recent((p50 > p200).shift(1), 10)
    t3_parts = pd.DataFrame({
        "gauge below 0": gauge < 0,
        "p50 crossed below p200": cross_dn,
        "Nifty 500 below its 50-day average": n500 < sma50,
        "adr10 below 0.8": adr10 < 0.8,
    })
    t3_today = _recent(t2_today, 25) & (t3_parts.sum(axis=1) >= 3)

    # the readings need ~200 sessions of history (200-day averages, 52-week highs/lows); before the
    # regime light is valid no signal may move the cycle, so it starts cleanly in Seller exhaustion
    ok = rg["light"].notna() if "light" in rg else pd.Series(True, index=idx)
    cyc = _phases(*(x & ok for x in (b1_today, b3_today, t1_today, t3_today)), up_parts.sum(axis=1), n500,
                  addiv=ad_div_raw & ok)
    df = df.join(cyc)
    live_b = (cyc["phase_prev"] == "bottom") | (cyc["phase"] == "bottom")
    live_t = (cyc["phase_prev"] == "top") | (cyc["phase"] == "top")
    df["b1"], df["b2"] = b1_today & live_b, b2_today & live_b
    df["b3"] = (cyc["phase_prev"] == "bottom") & (cyc["phase"] == "up")
    df["t1"], df["t2"] = t1_today & live_t, t2_today & live_t
    df["t3"] = (cyc["phase_prev"] == "top") & (cyc["phase"] == "down")
    df["up_n"], df["dn_n"] = up_parts.sum(axis=1), dn_parts.sum(axis=1)
    df["sma20"], df["sma50"] = sma20, sma50
    df["dist_days_25"] = dist_count
    df["ftd"] = ftd
    df["prior_low_date"] = [idx[j] if j >= 0 else pd.NaT for j in ploc]
    df["prior_high_date"] = [idx[j] if j >= 0 else pd.NaT for j in phloc]
    df.attrs["parts"] = {"b1": b1_parts, "b2": b2_parts, "b3": b3_parts,
                         "t1": t1_parts, "t2": div_parts, "t3": t3_parts, "up": up_parts, "down": dn_parts}
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
            on = df[key].fillna(False).astype(bool)
            days = df.index[on]
            parts = df.attrs["parts"][key].loc[last]
            items.append({
                "key": key, "name": name, "help": help_, "met_today": bool(on.iloc[-1]),
                "last_met": days[-1].date().isoformat() if len(days) else None,
                "sessions_ago": int(len(df) - 1 - df.index.get_loc(days[-1])) if len(days) else None,
                "parts": [{"label": k, "ok": bool(v) if pd.notna(v) else False} for k, v in parts.items()],
            })
        out[side] = items
    out["cycle"] = cycle(df, rg["n500"])
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


def cycle(df: pd.DataFrame, n500: pd.Series) -> dict:
    """Where the market is in the cycle, the live continuation box and recent phase changes."""
    last = df.index[-1]
    ph = df["phase"].iloc[-1]
    si = int(df["phase_since"].iloc[-1])
    d = lambda i: df.index[i].date().isoformat()
    ch = df[df["phase_event"].notna()]
    out = {"phase": ph, "since": d(si), "sessions_since": int(len(df) - 1 - si),
           "event": df["phase_event"].iloc[si] if si > 0 or pd.notna(df["phase_event"].iloc[si]) else None,
           "weak_days": int(df["weak_days"].iloc[-1]), "weak_needed": UP_WEAK_DAYS, "proven": bool(df["proven"].iloc[-1]),
           "pivot_low": float(df["pivot_low"].iloc[-1]) if pd.notna(df["pivot_low"].iloc[-1]) else None,
           "pivot_high": float(df["pivot_high"].iloc[-1]) if pd.notna(df["pivot_high"].iloc[-1]) else None,
           "failed": None,
           "n500_since": float(n500.iloc[si]), "n500_now": float(n500.iloc[-1]),
           "change_pct": float((n500.iloc[-1] / n500.iloc[si] - 1) * 100),
           "history": [{"date": t.date().isoformat(), "event": e, "phase": p, "n500": float(n500[t])}
                       for t, e, p in zip(ch.index[-8:], ch["phase_event"].iloc[-8:], ch["phase"].iloc[-8:])][::-1]}
    # back in Seller exhaustion because the confirmed bottom failed: keep what failed for the website
    if ph == "bottom" and si > 0 and str(out["event"] or "").startswith("Exhaustion failed"):
        ci = int(df["phase_since"].iloc[si - 1])
        out["failed"] = {"confirmed": d(ci), "n500_confirmed": float(n500.iloc[ci]),
                         "pivot_low": float(df["pivot_low"].iloc[si - 1]), "n500_failed": float(n500.iloc[si])}
    out["chart"] = chart(df, n500)
    out["chop"] = chop(df, n500)
    for side, col in (("up", "up_n"), ("down", "dn_n")):
        parts = df.attrs["parts"][side].loc[last]
        refs = [(df.at[last, "sma20"], "index"), (df.at[last, "sma50"], "index"), (50.0, "p50"), (0.0, "gauge")]
        out[side] = {"count": int(df[col].iloc[-1]),
                     "parts": [{"label": k, "ok": bool(v) if pd.notna(v) else False,
                                "ref": float(r) if pd.notna(r) else None, "kind": kind}
                               for (k, v), (r, kind) in zip(parts.items(), refs)]}
    return out


# Choppy market warning (Vivek's rules, 8 Nov 2026). Context only: changes no signal or light. Uses the 50-day EMA.
#   Choppy     = 1 OR 2 holds (his change 8 Nov 2026, was AND), unless an exception below applies:
#     1. today within ±CHOP_BAND% of the 50 EMA, and in the last CHOP_LOOK sessions price never held beyond
#        CHOP_BAND% for CHOP_HOLD+ days in a row (could not push away and hold)
#     2. the 50 EMA lost momentum over CHOP_LOOK sessions: moved < CHOP_EMA_FLAT%, or its direction
#        (vs CHOP_SLOPE_DAYS ago) flipped CHOP_EMA_FLIPS+ times (zig-zag)
#   No warning (exceptions):
#     3. quick push: price crossed the 50 EMA and got > CHOP_BAND% away within CHOP_PUSH_DAYS sessions. Off while
#        it holds there; if it falls back inside the band it stays off as long as the 50 EMA has turned the push's
#        way (his correction); ends if price crosses back over the EMA
#     4. congestion: the last CONG_DAYS closes within ±CONG_BAND% of the 50 EMA -> "Congestion · watch for break"
#        (not Choppy); a close outside the congestion's range is a break and stays warning-free while it holds
#        (ends on a close back inside the range or on the other side of the 50 EMA)
#   5. EMA trending (his rule, 8 Nov 2026: the ±3% test only applies while the 50 EMA is flat or getting flat):
#        the 50 EMA moved CHOP_TREND%+ in CHOP_TREND_DAYS sessions, or is picking up a trend (that move grew
#        CHOP_PICKUP_DAYS days in a row with price more than CHOP_PICKUP_DEV% on that side) -> no warning
CHOP_BAND = 3.0
CHOP_HOLD = 3
CHOP_LOOK = 30
CHOP_EMA_FLAT = 2.0
CHOP_EMA_FLIPS = 2
CHOP_SLOPE_DAYS = 5
CHOP_PUSH_DAYS = 4
CONG_BAND = 1.0
CONG_DAYS = 10
CHOP_TREND = 0.5
CHOP_TREND_DAYS = 10
CHOP_PICKUP_DAYS = 3
CHOP_PICKUP_DEV = 1.0


def chop_series(close: pd.Series) -> pd.DataFrame:
    """Daily choppy-market state: 'chop', 'congestion', 'push', 'break' or None, plus the numbers behind it."""
    ema = close.ewm(span=50, adjust=False).mean()
    c, e = close.to_numpy(float), ema.to_numpy(float)
    dv = (c / e - 1) * 100
    sl = np.sign(e - np.roll(e, CHOP_SLOPE_DAYS)); sl[:CHOP_SLOPE_DAYS] = 0
    tr = (e / np.roll(e, CHOP_TREND_DAYS) - 1) * 100; tr[:CHOP_TREND_DAYS] = 0
    n = len(c)
    rows = []
    side_prev, cross = 0, -999
    push = None            # direction of a quick push being held
    zone, brk = None, None  # congestion range (lo, hi, start) and the direction of a break being held
    cong_start = None
    for i in range(n):
        side = 1 if dv[i] > 0 else -1
        if side != side_prev:
            cross = i
        side_prev = side
        r = {"state": None, "dev": dv[i], "ema": e[i]}
        if i < 60:
            rows.append(r); continue
        # 3. quick push after a cross
        if abs(dv[i]) > CHOP_BAND and i - cross <= CHOP_PUSH_DAYS:
            push = side
        if push is not None and (side != push or (abs(dv[i]) <= CHOP_BAND and sl[i] != push)):
            push = None
        # 4. congestion and its break
        if np.all(np.abs(dv[i - CONG_DAYS + 1:i + 1]) <= CONG_BAND):
            cong_start = cong_start if cong_start is not None else i - CONG_DAYS + 1
            seg = c[cong_start:i + 1]
            zone, brk = (float(seg.min()), float(seg.max()), cong_start), None
            r.update(state="congestion", zone_lo=zone[0], zone_hi=zone[1], cong_days=i - cong_start + 1)
            rows.append(r); continue
        cong_start = None
        if zone is not None and brk is None:
            brk = 1 if c[i] > zone[1] else -1 if c[i] < zone[0] else None
            if brk is None:
                zone = None
        elif brk is not None and (side != brk or not (c[i] > zone[1] if brk > 0 else c[i] < zone[0])):
            zone, brk = None, None
        # 1 and 2
        w = dv[i - CHOP_LOOK + 1:i + 1]
        held = 0
        for k in range(len(w)):
            run = 0
            while k + run < len(w) and abs(w[k + run]) > CHOP_BAND and np.sign(w[k + run]) == np.sign(w[k]):
                run += 1
            held = max(held, run)
        ema_move = (e[i] / e[i - CHOP_LOOK] - 1) * 100
        s = [x for x in sl[i - CHOP_LOOK + 1:i + 1] if x != 0]
        flips = int(sum(1 for a, b in zip(s, s[1:]) if a != b))
        steep = abs(tr[i]) >= CHOP_TREND
        k = CHOP_PICKUP_DAYS
        pickup = (all(abs(tr[i - j]) > abs(tr[i - j - 1]) and np.sign(tr[i - j]) == np.sign(tr[i]) for j in range(k))
                  and np.sign(tr[i]) == side and abs(dv[i]) > CHOP_PICKUP_DEV)
        r.update(held=held, ema_move=ema_move, flips=flips, ema_10=tr[i])
        rule1 = abs(dv[i]) <= CHOP_BAND and held < CHOP_HOLD
        rule2 = abs(ema_move) < CHOP_EMA_FLAT or flips >= CHOP_EMA_FLIPS
        if push is not None:
            r["state"] = "push"
        elif brk is not None:
            r.update(state="break", zone_lo=zone[0], zone_hi=zone[1], brk=brk)
        elif steep or pickup:
            r["state"] = "trend"
        elif rule1 or rule2:
            r.update(state="chop", rule1=bool(rule1), rule2=bool(rule2))
        rows.append(r)
    return pd.DataFrame(rows, index=close.index)


def chop(df: pd.DataFrame, n500: pd.Series) -> dict:
    x = chop_series(n500.reindex(df.index).dropna()).iloc[-1]
    g = lambda k: (round(float(x[k]), 2) if pd.notna(x.get(k)) else None) if k in x else None
    out = {"state": x["state"], "on": x["state"] == "chop", "dev": g("dev"), "ema": g("ema"),
           "ema_move": g("ema_move"), "ema_10": g("ema_10"), "flips": int(x["flips"]) if pd.notna(x.get("flips")) else None,
           "look": CHOP_LOOK, "band": CHOP_BAND, "cong_band": CONG_BAND}
    if x["state"] in ("congestion", "break"):
        out.update(zone_lo=g("zone_lo"), zone_hi=g("zone_hi"))
    if x["state"] == "chop":
        out.update(price_band=bool(x["rule1"]), ema_flat=bool(x["rule2"]))
    if x["state"] == "congestion":
        out["cong_days"] = int(x["cong_days"])
    return out


CHART_DAYS = 110   # sessions shown in the website's cycle chart


def chart(df: pd.DataFrame, n500: pd.Series) -> dict:
    """Series for the website's cycle chart: closes, 20/50-day averages, the phase of each day,
    phase-change and stage markers, the turn the current move started from, and the failure line."""
    n = len(df)
    i0 = max(0, n - CHART_DAYS)
    idx = df.index
    d = lambda i: idx[i].date().isoformat()
    r1 = lambda v: round(float(v), 1) if pd.notna(v) else None
    marks = [{"date": d(idx.get_loc(t)), "event": e, "price": r1(n500[t])}
             for t, e in df["phase_event"].dropna().items() if idx.get_loc(t) >= i0]
    # first Exhaustion (stage 2 of a bottom) and first Distribution (stage 2 of a top) in each live spell
    ph = df["phase"].to_numpy()
    start = i0
    for i in range(i0 + 1, n + 1):
        if i == n or ph[i] != ph[start]:
            if ph[start] in ("bottom", "top"):
                col = "b2" if ph[start] == "bottom" else "t2"
                hit = np.flatnonzero(df[col].to_numpy()[start:i])
                if len(hit):
                    j = start + int(hit[0])
                    marks.append({"date": d(j), "event": "Exhaustion" if col == "b2" else "Distribution", "price": r1(n500.iloc[j])})
            start = i
    ph_now, si = df["phase"].iloc[-1], int(df["phase_since"].iloc[-1])
    anchor, fail = None, None
    if ph_now in ("up", "down"):
        lo = max(0, si - LOOK_TO)
        win = n500.iloc[lo:si + 1].to_numpy()
        j = lo + int(np.nanargmin(win) if ph_now == "up" else np.nanargmax(win))
        anchor = {"date": d(j), "price": r1(n500.iloc[j]), "kind": "bottom" if ph_now == "up" else "top",
                  "sessions": int(n - 1 - j), "change_pct": round(float((n500.iloc[-1] / n500.iloc[j] - 1) * 100), 2)}
        fail = r1(df["pivot_low"].iloc[-1] if ph_now == "up" else df["pivot_high"].iloc[-1])
    return {"dates": [d(i) for i in range(i0, n)],
            "close": [r1(v) for v in n500.iloc[i0:]],
            "sma20": [r1(v) for v in df["sma20"].iloc[i0:]],
            "sma50": [r1(v) for v in df["sma50"].iloc[i0:]],
            "phase": df["phase"].iloc[i0:].tolist(),
            "marks": sorted(marks, key=lambda m: m["date"]), "anchor": anchor, "fail": fail}


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
