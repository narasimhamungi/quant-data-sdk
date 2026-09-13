"""
One-off backfill: adds a single earlier historical dim_security row for
specific, independently-confirmed long-tenured S&P 500 constituents
(AAPL, MSFT) — enough for quant-data-sdk's price-side join to resolve a
security as of 2009, nothing more.

NOT a general historical S&P 500 reconstruction, and deliberately NOT a
call to build_dim_security(). That loader is designed for forward-only
snapshot application: any currently-tracked ticker missing from the
snapshot passed in gets its row closed as "removed from the index."
Calling it here with only {AAPL, MSFT} would have closed every one of
the ~500 OTHER currently-active constituents as of the backfill date —
a silent, destructive corruption of already-correct current data, to
fix two tickers. This script inserts exactly one new row per named
ticker and touches nothing else, by construction — no UPDATE statement
exists anywhere in this file.

Membership claim verified via search this session: AAPL was an
established constituent by 1998, MSFT by 1999 (independent contemporary
sources), comfortably covering the 2009-2010 window this unblocks.
Exact original addition dates were NOT verified and are not claimed.

company_name / gics_sector / gics_sub_industry below are best-known
standard GICS classifications — NOT independently verified this
session, unlike the membership claim itself. figi is left NULL (no
OpenFIGI backfill attempted) — same handling build_dim_security already
gives any row with a failed FIGI mapping.

Idempotent: skips a ticker if its earliest existing effective_from is
already <= BACKFILL_DATE.

Reuses quant-data-sdk's own .env (QDS_MARKETDATA_*) — same database,
no new environment needed. Run from quant-data-sdk's directory:
  python scripts/seed_historical_dim_security.py
"""
from __future__ import annotations

import os
from datetime import date

import psycopg2
from dotenv import load_dotenv

load_dotenv(override=True)

BACKFILL_DATE = date(2009, 1, 1)

# (ticker, company_name, gics_sector, gics_sub_industry)
SECURITIES = [
    ("AAPL", "Apple Inc.", "Information Technology", "Technology Hardware, Storage & Peripherals"),
    ("MSFT", "Microsoft Corporation", "Information Technology", "Systems Software"),
]


def main() -> None:
    conn = psycopg2.connect(
        host=os.environ.get("QDS_MARKETDATA_HOST", "localhost"),
        port=int(os.environ.get("QDS_MARKETDATA_PORT", 5432)),
        dbname=os.environ["QDS_MARKETDATA_DB"],
        user=os.environ["QDS_MARKETDATA_USER"],
        password=os.environ["QDS_MARKETDATA_PASSWORD"],
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM dim_security")
            (before_count,) = cur.fetchone()
            print(f"dim_security row count before: {before_count}")

            for ticker, company_name, sector, sub_industry in SECURITIES:
                cur.execute(
                    "SELECT MIN(effective_from) FROM dim_security WHERE ticker = %s",
                    (ticker,),
                )
                (earliest,) = cur.fetchone()
                if earliest is None:
                    print(
                        f"{ticker}: no existing dim_security row at all — skipping. "
                        f"This script only backfills an EARLIER period for a ticker "
                        f"that already has a current row; if this prints, {ticker} "
                        f"was never ingested in the first place, which is a "
                        f"different problem than this script fixes."
                    )
                    continue
                if earliest <= BACKFILL_DATE:
                    print(
                        f"{ticker}: earliest existing effective_from ({earliest}) is "
                        f"already <= {BACKFILL_DATE} — nothing to backfill, skipping."
                    )
                    continue

                cur.execute(
                    """
                    INSERT INTO dim_security
                        (ticker, company_name, gics_sector, gics_sub_industry, figi,
                         effective_from, effective_to, is_current)
                    VALUES (%s, %s, %s, %s, NULL, %s, %s, FALSE)
                    """,
                    (ticker, company_name, sector, sub_industry, BACKFILL_DATE, earliest),
                )
                print(f"{ticker}: inserted historical row [{BACKFILL_DATE}, {earliest}).")

            conn.commit()

            cur.execute("SELECT COUNT(*) FROM dim_security")
            (after_count,) = cur.fetchone()
            print(f"\ndim_security row count after: {after_count}")
            print(
                f"Expected exactly +{len(SECURITIES)} or fewer (fewer if any ticker "
                f"was skipped above) — verify this matches before trusting the run."
            )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
