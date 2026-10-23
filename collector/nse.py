"""Small HTTP helper for NSE's public archive files."""

from __future__ import annotations

import time

import requests

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


class BlockedError(RuntimeError):
    """NSE answered with something that is not the expected file."""


class NSEClient:
    def __init__(self, pause: float = 0.35, timeout: int = 30):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.pause = pause
        self.timeout = timeout
        self.requests_made = 0
        self.warm_up()

    def warm_up(self) -> None:
        """Visit the home page once so NSE sets its cookies."""
        try:
            self.session.get("https://www.nseindia.com/", timeout=self.timeout)
        except requests.RequestException:
            pass

    def get_bytes(self, url: str, timeout: int | None = None) -> bytes | None:
        """Raw bytes of a binary file (e.g. a zip), None on 404/error."""
        time.sleep(self.pause)
        self.requests_made += 1
        try:
            resp = self.session.get(url, timeout=timeout or self.timeout)
        except requests.RequestException:
            return None
        return resp.content if resp.status_code == 200 else None

    def get_text(self, url: str, attempts: int = 3) -> str | None:
        """Return the file's text, or None if it does not exist (404).

        A missing dated file normally means a market holiday or that the
        day's file is not published yet.
        """
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            time.sleep(self.pause)
            self.requests_made += 1
            try:
                resp = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = exc
                time.sleep(2 * attempt)
                continue
            if resp.status_code == 404:
                return None
            if resp.status_code in (401, 403):
                last_error = BlockedError(f"{resp.status_code} for {url}")
                self.warm_up()
                time.sleep(3 * attempt)
                continue
            if resp.status_code >= 500:
                last_error = BlockedError(f"{resp.status_code} for {url}")
                time.sleep(3 * attempt)
                continue
            text = resp.content.decode("utf-8-sig", "replace")
            if text.lstrip()[:1] == "<":  # an HTML page instead of a CSV
                last_error = BlockedError(f"HTML instead of CSV for {url}")
                time.sleep(3 * attempt)
                continue
            return text
        raise BlockedError(f"Failed after {attempts} attempts: {url} ({last_error})")
