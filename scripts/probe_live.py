"""Probe: do NSE/BSE live F&O feeds work from GitHub Actions (market hours)?

Checks option chains (NSE indices, BSE SENSEX), index and stock futures,
index quotes and Yahoo hourly candles. Reports via a workflow annotation.
"""

from __future__ import annotations

import json
import os
import time

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
lines: list[str] = []


def summarize(name: str, resp, extract=None) -> None:
    try:
        status = resp.status_code
        size = len(resp.content)
        note = ""
        if status == 200 and extract:
            try:
                note = extract(resp.json())
            except Exception as exc:  # noqa: BLE001
                note = f"parse error {type(exc).__name__}: {resp.text[:80]!r}"
        elif status != 200:
            note = resp.text[:80].replace("\n", " ")
        lines.append(f"{name}: HTTP {status}, {size} B {note}")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"{name}: FAIL {exc}"[:200])


def nse_session(impersonate: bool):
    if impersonate:
        from curl_cffi import requests as creq
        s = creq.Session(impersonate="chrome")
    else:
        s = requests.Session()
        s.headers.update({"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"})
    s.headers.update({"Referer": "https://www.nseindia.com/option-chain"})
    for url in ("https://www.nseindia.com/", "https://www.nseindia.com/option-chain"):
        try:
            s.get(url, timeout=20)
        except Exception:  # noqa: BLE001
            pass
    return s


def oc_extract(d):
    rec = d.get("records", d)
    exps = rec.get("expiryDates", [])
    data = rec.get("data", []) or d.get("filtered", {}).get("data", [])
    return f"expiries={exps[:2]} rows={len(data)} underlying={rec.get('underlyingValue')}"


def fut_extract(d):
    data = d.get("data", d if isinstance(d, list) else [])
    if data and isinstance(data, list):
        r = data[0]
        keys = [k for k in r if "oi" in k.lower() or "openInterest" in k][:4]
        return f"rows={len(data)} first={r.get('underlying') or r.get('symbol')} oi_keys={keys}"
    return f"keys={list(d)[:6]}"


for mode in (False, True):
    tag = "curl_cffi" if mode else "requests"
    try:
        s = nse_session(mode)
    except Exception as exc:  # noqa: BLE001
        lines.append(f"[{tag}] session FAIL {exc}"[:200])
        continue
    base = "https://www.nseindia.com/api"
    summarize(f"[{tag}] OC indices NIFTY (old)", s.get(f"{base}/option-chain-indices?symbol=NIFTY", timeout=25), oc_extract)
    time.sleep(1)
    r = s.get(f"{base}/option-chain-contract-info?symbol=NIFTY", timeout=25)
    exp = None
    try:
        exp = r.json().get("expiryDates", [None])[0]
    except Exception:  # noqa: BLE001
        pass
    summarize(f"[{tag}] OC contract-info NIFTY", r, lambda d: f"expiries={d.get('expiryDates', [])[:3]}")
    if exp:
        time.sleep(1)
        summarize(f"[{tag}] OC v3 NIFTY {exp}",
                  s.get(f"{base}/option-chain-v3?type=Indices&symbol=NIFTY&expiry={exp}", timeout=25), oc_extract)
    for key in ("nse50_fut", "nifty_bank_fut", "finnifty_fut", "niftymidcap_fut", "stock_fut"):
        time.sleep(1)
        summarize(f"[{tag}] futures {key}", s.get(f"{base}/liveEquity-derivatives?index={key}", timeout=25), fut_extract)
    time.sleep(1)
    summarize(f"[{tag}] allIndices", s.get(f"{base}/allIndices", timeout=25),
              lambda d: f"rows={len(d.get('data', []))}")

# BSE SENSEX option chain
try:
    from curl_cffi import requests as creq
    b = creq.Session(impersonate="chrome")
    b.headers.update({"Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com"})
    b.get("https://www.bseindia.com/", timeout=20)
    r = b.get("https://api.bseindia.com/BseIndiaAPI/api/ddlExpiry_IV/w?ProductType=IO&scrip_cd=1", timeout=25)
    summarize("[bse] SENSEX expiries", r, lambda d: str(d)[:120])
    try:
        tbl = r.json().get("Table1") or r.json().get("Table") or []
        exp = (tbl[0].get("ExpiryDate") if tbl else None)
    except Exception:  # noqa: BLE001
        exp = None
    if exp:
        summarize(f"[bse] SENSEX chain {exp}", b.get(
            f"https://api.bseindia.com/BseIndiaAPI/api/DerivOptionChain_IV/w?Expiry={exp}&scrip_cd=1&strprice=0",
            timeout=25), lambda d: f"rows={len(d.get('Table', []))}")
except Exception as exc:  # noqa: BLE001
    lines.append(f"[bse] FAIL {exc}"[:200])

# Yahoo hourly candles
summarize("[yahoo] RELIANCE.NS 60m", requests.get(
    "https://query1.finance.yahoo.com/v8/finance/chart/RELIANCE.NS?range=1mo&interval=60m",
    headers={"User-Agent": UA}, timeout=25),
    lambda d: f"candles={len(d['chart']['result'][0]['timestamp'])} last={time.strftime('%H:%M', time.gmtime(d['chart']['result'][0]['timestamp'][-1] + 19800))} IST")

msg = "\n".join(lines)
print(msg)
if os.environ.get("GITHUB_ACTIONS"):
    print("::notice title=Live feed probe::" + msg.replace("%", "%25").replace("\n", "%0A"))
