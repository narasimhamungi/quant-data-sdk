"""
CIK <-> ticker crosswalk, sourced from SEC's own company_tickers.json —
the same source pit-fundamentals-store already uses for its own ticker
resolution (see that repo's universe.py).

Disclosed limitation, inherited from that same precedent: this is a
CURRENT mapping only. It is not a source of dated historical ticker
identity — if a ticker was ever reassigned or a company changed its
ticker, this cannot tell you what was true as of a past date, only
what's true today. dim_security has the identical limitation on the
price side (business key is ticker, no cross-reference across a ticker
rename) — this doesn't fix that, it just centralizes the same disclosed
limitation instead of leaving it implicit in a hardcoded dict.

SEC requires a descriptive User-Agent on every request — set
QDS_SEC_USER_AGENT in .env before calling this. Cached to a local file
for CACHE_MAX_AGE_SECONDS; this is current-mapping data, not worth
re-fetching on every call.

UNTESTED against the live SEC endpoint as of writing — the JSON
structure below (row-number keys, {cik_str, ticker, title} values) is
confirmed from SEC's own published documentation and multiple
independent client implementations, not yet verified by an actual call
from this codebase.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv(override=True)

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
CACHE_PATH = Path(__file__).resolve().parent.parent.parent / ".cache" / "company_tickers.json"
CACHE_MAX_AGE_SECONDS = 24 * 60 * 60  # 1 day

_ticker_to_cik: Optional[dict] = None


def _fetch_live() -> dict:
    user_agent = os.environ.get("QDS_SEC_USER_AGENT")
    if not user_agent:
        raise RuntimeError(
            "QDS_SEC_USER_AGENT is not set in .env — SEC requires a real, "
            "descriptive User-Agent (name + contact email) on every request."
        )
    resp = requests.get(SEC_TICKERS_URL, headers={"User-Agent": user_agent}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _load_cached_or_fetch() -> dict:
    if CACHE_PATH.exists():
        age_seconds = time.time() - CACHE_PATH.stat().st_mtime
        if age_seconds < CACHE_MAX_AGE_SECONDS:
            return json.loads(CACHE_PATH.read_text())
    data = _fetch_live()
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(data))
    return data


def _index() -> dict:
    global _ticker_to_cik
    if _ticker_to_cik is None:
        raw = _load_cached_or_fetch()
        # raw is keyed by row-number strings; each value is
        # {"cik_str": int, "ticker": str, "title": str}
        _ticker_to_cik = {entry["ticker"].upper(): int(entry["cik_str"]) for entry in raw.values()}
    return _ticker_to_cik


def get_cik_for_ticker(ticker: str) -> int:
    """
    Resolve a ticker to its CIK via SEC's current mapping. Fails loudly
    on an unresolvable ticker rather than silently dropping it — same
    philosophy pit-fundamentals-store states for its own ticker
    resolution.
    """
    cik = _index().get(ticker.upper())
    if cik is None:
        raise ValueError(
            f"Ticker {ticker!r} not found in SEC's current company_tickers.json. "
            "This crosswalk is current-mapping-only (see module docstring) — "
            "a delisted, renamed, or very recently listed ticker may not "
            "resolve even if it's a real company."
        )
    return cik
