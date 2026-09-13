"""
Two independent Postgres connections.

quant-data-sdk deliberately does NOT import marketdata-lakehouse's or
pit-fundamentals-store's Python packages. Those are separate repos with
their own dependency trees; this SDK treats both only as databases it
reads from over the wire. That's a real architectural boundary, not
laziness — importing across three separately-versioned portfolio repos
would tightly couple them and break the "generalizable, standalone
project" story each one is supposed to tell on its own.

Two independent .env blocks, one per upstream Postgres instance, on the
known 5432/5433 split (marketdata-lakehouse defaulted to 5432;
pit-fundamentals-store moved to 5433 after they collided locally).
override=True beats stale setx env vars, same convention as the other
two repos.
"""
from __future__ import annotations

import os

import psycopg2
from dotenv import load_dotenv

load_dotenv(override=True)


def get_marketdata_connection():
    """marketdata-lakehouse gold layer — port 5432 by convention."""
    return psycopg2.connect(
        host=os.environ.get("QDS_MARKETDATA_HOST", "localhost"),
        port=int(os.environ.get("QDS_MARKETDATA_PORT", 5432)),
        dbname=os.environ["QDS_MARKETDATA_DB"],
        user=os.environ["QDS_MARKETDATA_USER"],
        password=os.environ["QDS_MARKETDATA_PASSWORD"],
    )


def get_fundamentals_connection():
    """pit-fundamentals-store — port 5433 by convention (collided with
    marketdata-lakehouse's default 5432 during that project's build)."""
    return psycopg2.connect(
        host=os.environ.get("QDS_FUNDAMENTALS_HOST", "localhost"),
        port=int(os.environ.get("QDS_FUNDAMENTALS_PORT", 5433)),
        dbname=os.environ["QDS_FUNDAMENTALS_DB"],
        user=os.environ["QDS_FUNDAMENTALS_USER"],
        password=os.environ["QDS_FUNDAMENTALS_PASSWORD"],
    )
