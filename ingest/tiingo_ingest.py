"""Fetch daily prices (with splits and dividends) from Tiingo for every
security in marts.dim_security_master, over the full transaction window.

Tiingo returns one row per security per trading day, including
splitFactor (1.0 on a normal day, e.g. 4.0 on a 4-for-1 split day) and
divCash (dividend paid that day, 0.0 if none). These are the actual
corporate-action signals positions will need to apply later.
"""
import os
import time

import pandas as pd
import requests
from dotenv import load_dotenv
from sqlalchemy import text

from load_to_postgres import get_engine
from pipeline_common import ROOT, write_partition

load_dotenv(ROOT / ".env")

API_KEY = os.environ["TIINGO_API_KEY"]

START_DATE = "2026-04-01"
END_DATE = "2026-10-01"


def load_tickers(engine) -> list[str]:
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
    for i, ticker in enumerate(tickers):
        print(f"Fetching {ticker}...")
        frames.append(fetch_prices(ticker))
        if i < len(tickers) - 1:
            time.sleep(1.5)  # stay under Tiingo's free-tier rate limit

    df = pd.concat(frames, ignore_index=True)
    out_path = write_partition(df, "tiingo")
    print(f"Wrote {len(df)} price rows for {len(tickers)} tickers to {out_path}")