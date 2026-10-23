"""Split and bonus events from NSE, used to adjust stock prices.

NSE's bhavcopy prices are raw: on a 1:5 split the price simply drops ~80%.
Without adjustment, moving averages, returns and 52-week highs would show a
fake crash. This module downloads NSE's corporate-action list and turns each
split / bonus into a price factor:

    split Rs 10 -> Rs 2      factor = 2 / 10        = 0.2
    bonus 1:1 (1 new per 1)  factor = 1 / (1 + 1)   = 0.5
    bonus 4:1 + split 2 -> 1 factor = 0.2 * 0.5     = 0.1

Prices before the ex-date are multiplied by the factor (done later, at
analysis time; the stored raw prices are never changed).
"""

from __future__ import annotations

import datetime as dt
import json
import re

import pandas as pd

from .nse import NSEClient

API = ("https://www.nseindia.com/api/corporates-corporateActions"
       "?index=equities&from_date={start}&to_date={end}")

NUM = r"(\d+(?:\.\d+)?)"
# "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share"
SPLIT_RE = re.compile(
    rf"split.*?(?:rs|re|inr)\.?\s*{NUM}.*?\bto\b\s*(?:rs|re|inr)\.?\s*{NUM}",
    re.IGNORECASE)
# "Bonus 1:1" / "Bonus 4:1" (new shares : held shares)
BONUS_RE = re.compile(rf"bonus\s*-?\s*{NUM}\s*:\s*{NUM}", re.IGNORECASE)


def factor_from_subject(subject: str) -> float | None:
    """Price factor for a split and/or bonus subject line, else None."""
    factor, found = 1.0, False
    m = SPLIT_RE.search(subject)
    if m:
        old, new = float(m.group(1)), float(m.group(2))
        if old > 0 and 0 < new < old:
            factor *= new / old
            found = True
    m = BONUS_RE.search(subject)
    if m:
        new_sh, held = float(m.group(1)), float(m.group(2))
        if new_sh > 0 and held > 0:
            factor *= held / (new_sh + held)
            found = True
    return factor if found else None


def fetch(client: NSEClient, start: dt.date, end: dt.date) -> pd.DataFrame:
    """All split / bonus actions with ex-date in [start, end]."""
    rows = []
    chunk = dt.timedelta(days=90)
    lo = start
    while lo <= end:
        hi = min(lo + chunk, end)
        url = API.format(start=lo.strftime("%d-%m-%Y"), end=hi.strftime("%d-%m-%Y"))
        text = client.get_text(url)
        data = json.loads(text) if text else []
        if isinstance(data, dict):  # some versions wrap the list
            data = data.get("data", [])
        for item in data:
            subject = str(item.get("subject", ""))
            if not re.search(r"split|bonus", subject, re.IGNORECASE):
                continue
            ex = pd.to_datetime(item.get("exDate"), format="%d-%b-%Y", errors="coerce")
            rows.append({
                "symbol": str(item.get("symbol", "")).strip(),
                "series": str(item.get("series", "")).strip(),
                "ex_date": ex.date().isoformat() if pd.notna(ex) else None,
                "subject": subject.strip(),
                "factor": factor_from_subject(subject),
            })
        lo = hi + dt.timedelta(days=1)
    df = pd.DataFrame(rows, columns=["symbol", "series", "ex_date", "subject", "factor"])
    return df.dropna(subset=["ex_date"])
