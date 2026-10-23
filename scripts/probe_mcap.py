"""Probe: can we get market cap and industry for every NSE stock for free?

Checks (from GitHub Actions):
  1. NSE quote API per stock (industry classification + issued shares)
  2. NSE daily "PR" zip (may contain a market-cap file for all companies)
  3. NSE equity master list (EQUITY_L.csv)
Reports via a workflow annotation.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import os
import zipfile

from collector.nse import NSEClient

client = NSEClient(pause=0.6)
lines = []

# 1. Quote API
for sym in ["RELIANCE", "TATAELXSI", "KPITTECH"]:
    try:
        text = client.get_text(f"https://www.nseindia.com/api/quote-equity?symbol={sym}")
        d = json.loads(text) if text else {}
        ind = d.get("industryInfo", {})
        info = d.get("securityInfo", {})
        price = d.get("priceInfo", {})
        lines.append(f"quote {sym}: industryInfo={ind} issuedSize={info.get('issuedSize')} "
                     f"lastPrice={price.get('lastPrice')} keys={list(d)[:8]}")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"quote {sym}: FAIL {type(exc).__name__}: {exc}"[:200])

# 2. PR zip for the last few weekdays
day = dt.date.today() - dt.timedelta(days=1)
for _ in range(5):
    while day.weekday() >= 5:
        day -= dt.timedelta(days=1)
    url = f"https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/PR{day:%d%m%y}.zip"
    try:
        resp = client.session.get(url, timeout=30)
        if resp.status_code == 200 and resp.content[:2] == b"PK":
            zf = zipfile.ZipFile(io.BytesIO(resp.content))
            names = zf.namelist()
            lines.append(f"PR zip {day}: {names}")
            mc = [n for n in names if "mcap" in n.lower()]
            if mc:
                head = zf.read(mc[0]).decode("utf-8", "replace").splitlines()
                lines.append(f"  {mc[0]}: rows={len(head)} | {head[0][:200]} | {head[1][:200]}")
            break
        lines.append(f"PR zip {day}: HTTP {resp.status_code}")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"PR zip {day}: FAIL {exc}"[:200])
    day -= dt.timedelta(days=1)

# 3. Equity master list
try:
    text = client.get_text("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv")
    rows = text.splitlines() if text else []
    lines.append(f"EQUITY_L: rows={len(rows)} | {rows[0][:200] if rows else ''}")
except Exception as exc:  # noqa: BLE001
    lines.append(f"EQUITY_L: FAIL {exc}"[:200])

msg = "\n".join(lines)
print(msg)
if os.environ.get("GITHUB_ACTIONS"):
    print("::notice title=Market cap probe::" + msg.replace("%", "%25").replace("\n", "%0A"))
