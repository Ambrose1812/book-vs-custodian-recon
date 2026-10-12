"""Fetch daily prices (with splits and dividends) from Tiingo for every
security in marts.dim_security_master, over the full transaction window.

Tiingo returns one row per security per trading day, including
splitFactor (1.0 on a normal day, e.g. 4.0 on a 4-for-1 split day) and
divCash (dividend paid that day, 0.0 if none). These are the actual
corporate-action signals positions will need to apply later.
"""
import os
from datetime import date, datetime, timezone
from pathlib import Path

import time

import pandas as pd
import requests
from dotenv import load_dotenv

from load_to_postgres import get_engine

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

OUT = ROOT / "data" / "landing" / "tiingo"
API_KEY = os.environ["TIINGO_API_KEY"]

START_DATE = "2026-04-01"
END_DATE = "2026-10-01"


def load_tickers(engine) -> list[str]:
    from sqlalchemy import text
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT ticker FROM marts.dim_security_master")).scalars().all()
    return list(rows)


def tiingo_symbol(ticker: str) -> str:
    """Tiingo's URL path uses a hyphen for share classes (BRK-B),
    while our security master stores the conventional slash (BRK/B)."""
    return ticker.replace("/", "-")


def fetch_prices(ticker: str) -> pd.DataFrame:
    symbol = tiingo_symbol(ticker)
    url = f"https://api.tiingo.com/tiingo/daily/{symbol}/prices"
    params = {
        "startDate": START_DATE,
        "endDate": END_DATE,
        "token": API_KEY,
        "format": "json",
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()  # fail loudly on a bad response, don't continue silently

    df = pd.DataFrame(resp.json())
    df["ticker"] = ticker  # keep the original, conventional form in the data
    return df


if __name__ == "__main__":
    engine = get_engine()
    tickers = load_tickers(engine)
    if not tickers:
        raise SystemExit("marts.dim_security_master is empty — build it first.")

    frames = []
    for ticker in tickers:
        print(f"Fetching {ticker}...")
        frames.append(fetch_prices(ticker))
        time.sleep(1.5)  # stay under Tiingo's free-tier rate limit

    df = pd.concat(frames, ignore_index=True)

    ingest_date = datetime.now(timezone.utc).date()
    partition_dir = OUT / f"ingest_date={ingest_date}"
    partition_dir.mkdir(parents=True, exist_ok=True)

    out_path = partition_dir / "part-0001.parquet"
    df.to_parquet(out_path, index=False)
    print(f"Wrote {len(df)} price rows for {len(tickers)} tickers to {out_path}")