"""Upcoming quarterly results, from NSE's corporate event calendar.

NSE lists every board meeting a company has announced, with its purpose.
Meetings whose purpose mentions financial results are kept in
data/meta/results_calendar.csv (symbol, date, purpose); past dates are kept
for 30 days so the site can also flag "results just out".
"""

from __future__ import annotations

import datetime as dt
import json
import re

import pandas as pd

from .nse import NSEClient

API = "https://www.nseindia.com/api/event-calendar?index=equities&from_date={start}&to_date={end}"
RESULTS_RE = re.compile(r"financial result|quarterly result|audited result|results", re.IGNORECASE)
KEEP_PAST_DAYS = 30
AHEAD_DAYS = 60


def fetch(client: NSEClient, start: dt.date, end: dt.date) -> pd.DataFrame:
    url = API.format(start=start.strftime("%d-%m-%Y"), end=end.strftime("%d-%m-%Y"))
    text = client.get_text(url)
    data = json.loads(text) if text else []
    if isinstance(data, dict):
        data = data.get("data", [])
    rows = []
    for item in data:
        purpose = " ".join(str(item.get(k) or "") for k in ("purpose", "bm_desc")).strip()
        if not RESULTS_RE.search(purpose):
            continue
        d = pd.to_datetime(item.get("date"), format="%d-%b-%Y", errors="coerce")
        if pd.isna(d):
            d = pd.to_datetime(item.get("date"), dayfirst=True, errors="coerce")
        sym = str(item.get("symbol") or "").strip()
        if sym and pd.notna(d):
            rows.append({"symbol": sym, "date": d.date().isoformat(),
                         "purpose": str(item.get("purpose") or "").strip()[:80]})
    return pd.DataFrame(rows, columns=["symbol", "date", "purpose"])


def update(client: NSEClient, path, today: dt.date) -> dict:
    new = fetch(client, today - dt.timedelta(days=KEEP_PAST_DAYS), today + dt.timedelta(days=AHEAD_DAYS))
    old = pd.read_csv(path, dtype=str) if path.exists() else pd.DataFrame(columns=["symbol", "date", "purpose"])
    if len(new):
        # the fresh list replaces stored future dates (meetings get rescheduled)
        old = old[old["date"] < today.isoformat()]
    df = pd.concat([old, new], ignore_index=True).drop_duplicates(["symbol", "date"], keep="last")
    df = df[df["date"] >= (today - dt.timedelta(days=KEEP_PAST_DAYS)).isoformat()].sort_values(["date", "symbol"])
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    upcoming = df[df["date"] >= today.isoformat()]
    return {"ok": True, "fetched": len(new), "upcoming": len(upcoming),
            "next_7_days": int((upcoming["date"] <= (today + dt.timedelta(days=7)).isoformat()).sum())}
