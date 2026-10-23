"""Probe: market-cap coverage, and BSE's scrip list as an industry source."""

from __future__ import annotations

import datetime as dt
import io
import json
import os
import zipfile

import pandas as pd

from collector.nse import NSEClient

client = NSEClient(pause=0.6)
lines = []

# Market cap snapshot from the NSE PR zip
day = dt.date.today() - dt.timedelta(days=1)
mcap = None
for _ in range(5):
    while day.weekday() >= 5:
        day -= dt.timedelta(days=1)
    url = f"https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/PR{day:%d%m%y}.zip"
    resp = client.session.get(url, timeout=30)
    if resp.status_code == 200 and resp.content[:2] == b"PK":
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        name = next(n for n in zf.namelist() if n.lower().startswith("mcap"))
        mcap = pd.read_csv(io.BytesIO(zf.read(name)), dtype=str)
        break
    day -= dt.timedelta(days=1)

tm = set(pd.read_csv("data/constituents/TOTALMKT.csv", dtype=str)["symbol"])
if mcap is not None:
    mcap.columns = [c.strip() for c in mcap.columns]
    mcap = mcap[mcap["Series"].str.strip().isin(["EQ", "BE"])]
    mcap["sym"] = mcap["Symbol"].str.strip()
    mcap["cr"] = pd.to_numeric(mcap["Market Cap(Rs.)"].str.strip(), errors="coerce") / 1e7
    above = mcap[mcap["cr"] >= 500]
    in_tm = mcap[mcap["sym"].isin(tm)]
    lines.append(f"Stocks (EQ/BE): {len(mcap)}; mcap >= 500 cr: {len(above)}; "
                 f"of these outside Total Market: {(~above['sym'].isin(tm)).sum()}")
    lines.append(f"Smallest Total Market stock: {in_tm['cr'].min():.0f} cr; "
                 f"10th pct {in_tm['cr'].quantile(0.1):.0f} cr")
    lines.append(f"Count by mcap band (cr): " + str(pd.cut(mcap['cr'], [0, 500, 1000, 2000, 5000, 1e9]).value_counts().sort_index().to_dict()))

# BSE scrip list with industry
for url in [
    "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w?Group=&Scripcode=&industry=&segment=Equity&status=Active",
]:
    try:
        resp = client.session.get(url, timeout=40, headers={
            "Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com"})
        txt = resp.text
        lines.append(f"BSE scrip list: HTTP {resp.status_code}, {len(txt)} bytes")
        data = json.loads(txt) if resp.status_code == 200 and txt.strip().startswith(("[", "{")) else []
        if isinstance(data, dict):
            data = data.get("Table", [])
        if data:
            lines.append(f"  rows={len(data)} keys={list(data[0])}")
            lines.append(f"  sample={ {k: data[0][k] for k in list(data[0])[:12]} }")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"BSE scrip list: FAIL {type(exc).__name__}: {exc}"[:200])

msg = "\n".join(lines)
print(msg)
if os.environ.get("GITHUB_ACTIONS"):
    print("::notice title=Market cap probe::" + msg.replace("%", "%25").replace("\n", "%0A"))
