"""Upload the website's data files to the private Supabase database.

The website is private: it signs in with the F&O Desk email and password and
reads its data from the `docs` table (keys ss_sectors, ss_stocks, ...), which
only that email can read. The JSON files are no longer published.

Run after `python -m analysis.build`:  python -m analysis.publish
Needs the repository secrets SUPABASE_URL and SUPABASE_SERVICE_KEY.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

import requests

DATA = Path(__file__).resolve().parent.parent / "site" / "data"


def main() -> int:
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        print("::warning::SUPABASE_URL / SUPABASE_SERVICE_KEY not set: website data not uploaded")
        return 0
    headers = {"apikey": key, "Content-Type": "application/json",
               "Prefer": "resolution=merge-duplicates,return=minimal"}
    if key.startswith("eyJ"):                  # legacy service_role JWT
        headers["Authorization"] = f"Bearer {key}"
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    sent = []
    for path in sorted(DATA.glob("*.json")):
        row = {"key": f"ss_{path.stem}", "data": json.loads(path.read_text(encoding="utf-8")), "updated_at": now}
        r = requests.post(f"{url.rstrip('/')}/rest/v1/docs", params={"on_conflict": "key"},
                          headers=headers, data=json.dumps(row), timeout=120)
        if r.status_code >= 300:
            print(f"::error::Upload of {path.name} failed: HTTP {r.status_code} {r.text[:300]}")
            return 1
        sent.append(f"{path.stem} ({path.stat().st_size // 1024} KB)")
    print("::notice title=Website data uploaded::" + ", ".join(sent))
    return 0


if __name__ == "__main__":
    sys.exit(main())
