"""Phase 1 - data feasibility probe.

Checks whether the free data sources the sector-strength tool needs can be
downloaded from GitHub Actions servers. It writes a Markdown report to the
GitHub job summary (if available) and a JSON file with the raw results.

Nothing here is used by the final tool; it only answers one question:
"Which free sources work from the cloud?"
"""

from __future__ import annotations

import datetime as dt
import io
import json
import os
import sys
import time
import zipfile
from zoneinfo import ZoneInfo

import requests

IST = ZoneInfo("Asia/Kolkata")
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}
TIMEOUT = 25


def recent_weekdays(n: int = 7) -> list[dt.date]:
    """Last n weekdays before today (IST); today's file may not exist yet."""
    day = dt.datetime.now(IST).date() - dt.timedelta(days=1)
    out: list[dt.date] = []
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day)
        day -= dt.timedelta(days=1)
    return out


def describe(resp: requests.Response) -> dict:
    """Summarise a response: status, size, rows, first line."""
    body = resp.content
    info = {"status": resp.status_code, "bytes": len(body)}
    ctype = resp.headers.get("Content-Type", "")
    info["content_type"] = ctype
    text = ""
    if body[:2] == b"PK":  # zip archive
        try:
            with zipfile.ZipFile(io.BytesIO(body)) as zf:
                name = zf.namelist()[0]
                text = zf.read(name).decode("utf-8", "replace")
                info["zip_member"] = name
        except zipfile.BadZipFile:
            text = ""
    else:
        text = body.decode("utf-8", "replace")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    info["rows"] = max(len(lines) - 1, 0)
    info["first_line"] = lines[0][:160] if lines else ""
    return info


def looks_ok(info: dict, min_rows: int) -> bool:
    if info.get("status") != 200 or info.get("rows", 0) < min_rows:
        return False
    first = info.get("first_line", "").lower()
    return "<html" not in first and "access denied" not in first


def fetch(session: requests.Session, url: str) -> dict:
    t0 = time.time()
    try:
        resp = session.get(url, headers=HEADERS, timeout=TIMEOUT)
        info = describe(resp)
    except requests.RequestException as exc:
        info = {"status": "error", "error": f"{type(exc).__name__}: {exc}"[:200]}
    info["seconds"] = round(time.time() - t0, 2)
    info["url"] = url
    return info


def try_dates(session, name, template, min_rows, date_fmt="%d%m%Y"):
    """Try a dated file for recent weekdays until one works."""
    attempts = []
    for day in recent_weekdays():
        url = template.format(d=day.strftime(date_fmt))
        info = fetch(session, url)
        info["date"] = day.isoformat()
        attempts.append(info)
        if looks_ok(info, min_rows):
            return {"name": name, "ok": True, "result": info, "attempts": len(attempts)}
        time.sleep(1)
    return {"name": name, "ok": False, "result": attempts[-1], "attempts": len(attempts),
            "all_attempts": attempts}


def try_once(session, name, url, min_rows):
    info = fetch(session, url)
    return {"name": name, "ok": looks_ok(info, min_rows), "result": info, "attempts": 1}


def try_yahoo(session, name, symbol):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           "?range=1mo&interval=1d")
    info = fetch(session, url)
    ok = False
    if info.get("status") == 200:
        try:
            resp = session.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
            data = resp.json()["chart"]["result"][0]
            closes = [c for c in data["indicators"]["quote"][0]["close"] if c]
            info["rows"] = len(closes)
            info["first_line"] = f"last close {closes[-1]:.2f}" if closes else ""
            ok = len(closes) >= 10
        except Exception as exc:  # noqa: BLE001 - report any parse issue
            info["error"] = f"parse: {exc}"[:200]
    return {"name": name, "ok": ok, "result": info, "attempts": 1}


def main() -> int:
    session = requests.Session()
    # Visiting the home page first gives NSE's cookies, which some
    # endpoints require.
    warmup = fetch(session, "https://www.nseindia.com/")

    checks = [
        # --- Sector index history (core of the tool) ---
        try_dates(session, "NSE all-indices daily close (nsearchives)",
                  "https://nsearchives.nseindia.com/content/indices/ind_close_all_{d}.csv", 50),
        try_dates(session, "NSE all-indices daily close (archives)",
                  "https://archives.nseindia.com/content/indices/ind_close_all_{d}.csv", 50),
        # --- Stock prices for the drill-down ---
        try_dates(session, "NSE full bhavcopy with delivery % (nsearchives)",
                  "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d}.csv", 500),
        try_dates(session, "NSE UDiFF bhavcopy zip (nsearchives)",
                  "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{d}_F_0000.csv.zip",
                  500, date_fmt="%Y%m%d"),
        # --- Sector constituents ---
        try_once(session, "Constituents: Nifty IT (niftyindices.com)",
                 "https://www.niftyindices.com/IndexConstituent/ind_niftyitlist.csv", 5),
        try_once(session, "Constituents: Nifty IT (nsearchives)",
                 "https://nsearchives.nseindia.com/content/indices/ind_niftyitlist.csv", 5),
        try_once(session, "Constituents: Nifty Bank (nsearchives)",
                 "https://nsearchives.nseindia.com/content/indices/ind_niftybanklist.csv", 5),
        # --- F&O stock list (to flag F&O stocks) ---
        try_once(session, "F&O lot-size list (nsearchives)",
                 "https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv", 50),
        # --- NSE JSON API (needs cookies; often blocked from cloud) ---
        try_once(session, "NSE API: all indices snapshot",
                 "https://www.nseindia.com/api/allIndices", 1),
        # --- Fallback source ---
        try_yahoo(session, "Yahoo: NIFTY 50 (^NSEI)", "%5ENSEI"),
        try_yahoo(session, "Yahoo: NIFTY IT (^CNXIT)", "%5ECNXIT"),
        try_yahoo(session, "Yahoo: RELIANCE.NS", "RELIANCE.NS"),
    ]

    report = {
        "run_at_ist": dt.datetime.now(IST).isoformat(timespec="seconds"),
        "warmup": warmup,
        "checks": checks,
    }
    os.makedirs("probe_output", exist_ok=True)
    with open("probe_output/probe_results.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    # --- Markdown summary ---
    passed = sum(c["ok"] for c in checks)
    md = [
        "# Data source feasibility test",
        f"Run at {report['run_at_ist']} IST - **{passed}/{len(checks)} sources working**",
        f"NSE home page warm-up: status `{warmup.get('status')}`",
        "",
        "| Source | Result | HTTP | Rows | Data date | First line |",
        "|---|---|---|---|---|---|",
    ]
    for c in checks:
        r = c["result"]
        first = str(r.get("first_line") or r.get("error", "")).replace("|", "/")[:80]
        md.append(
            f"| {c['name']} | {'PASS' if c['ok'] else 'FAIL'} | {r.get('status')} | "
            f"{r.get('rows', '-')} | {r.get('date', '-')} | `{first}` |"
        )

    core_index = any(c["ok"] for c in checks[:2])
    core_stock = any(c["ok"] for c in checks[2:4])
    yahoo = all(c["ok"] for c in checks[-3:])
    md += ["", "## Verdict"]
    if core_index and core_stock:
        md.append("- NSE archive files work from GitHub Actions: build on **NSE data**.")
    elif yahoo:
        md.append("- NSE files are blocked or incomplete: use **Yahoo** as the primary source.")
    else:
        md.append("- Neither source is fully usable: needs a different approach.")
    text = "\n".join(md)
    print(text)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
