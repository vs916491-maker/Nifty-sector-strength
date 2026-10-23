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


s = nse_session(False)
base = "https://www.nseindia.com/api"
def keys_extract(d):
    data = d.get("data", d) if isinstance(d, dict) else d
    if isinstance(data, dict):
        return "dict keys=" + str(list(data)[:8])
    if isinstance(data, list) and data:
        return f"rows={len(data)} keys={list(data[0])[:14]}"
    return str(d)[:120]
def deriv_extract(d):
    body = d if isinstance(d, dict) else {}
    data = body.get("data") or body.get("stocks") or body
    if isinstance(data, list) and data:
        futs = [x for x in data if "FUT" in str(x.get("instrumentType", x)).upper()]
        r = futs[0] if futs else data[0]
        return f"rows={len(data)} futs={len(futs)} sample_keys={list(r)[:25]}"
    return "keys=" + str(list(body)[:10]) + " " + str(body)[:200]
for sym in ("HDFCBANK", "APOLLOHOSP", "IREDA"):
    time.sleep(1.5)
    summarize(f"NextApi {sym}", s.get(f"{base}/NextApi/apiClient/GetQuoteApi",
              params={"functionName": "getSymbolDerivativesData", "symbol": sym}, timeout=25), deriv_extract)
time.sleep(1.5)
r = s.get(f"{base}/NextApi/apiClient/GetQuoteApi", params={"functionName": "getSymbolDerivativesData", "symbol": "HDFCBANK"}, timeout=25)
try:
    d = r.json(); data = d.get("data") or d
    futs = [x for x in data if "FUT" in str(x.get("instrumentType", "")).upper()][:1]
    lines.append("HDFCBANK fut row: " + json.dumps(futs[0])[:700] if futs else "no fut row: " + json.dumps(data[:1])[:500])
except Exception as exc:  # noqa: BLE001
    lines.append(f"detail parse fail {exc}: {r.text[:200]!r}")

msg = "\n".join(lines)
print(msg)
if os.environ.get("GITHUB_ACTIONS"):
    print("::notice title=Live feed probe::" + msg.replace("%", "%25").replace("\n", "%0A"))
