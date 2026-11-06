"""Paths, calendar and file-writing helper shared by the ingest scripts.

Every script that lands data used to build its own partition folder and write
its own Parquet file. Doing it in one place means they all write the same way.
"""
import os
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pandas as pd
from pandas.tseries.offsets import CustomBusinessDay

ROOT = Path(__file__).resolve().parent.parent
LANDING_ROOT = ROOT / "data" / "landing"

# NYSE full-day closures for 2026 (hardcoded; extend this list if the date range
# moves to another year). Federal holidays are not enough: Good Friday is an NYSE
# closure but not a federal holiday.
NYSE_HOLIDAYS = pd.to_datetime([
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
])
# One business day on the exchange calendar: used for trade dates and T+1 settlement.
MARKET_BDAY = CustomBusinessDay(holidays=NYSE_HOLIDAYS)


def partition_file(source: str, ingest_date=None) -> Path:
    """Path of a source's part file for one ingest date (default: today, UTC)."""
    ingest_date = ingest_date or datetime.now(timezone.utc).date()
    return LANDING_ROOT / source / f"ingest_date={ingest_date}" / "part-0001.parquet"


def write_partition(data, source: str, ingest_date=None) -> Path:
    """Write data to data/landing/<source>/ingest_date=<date>/part-0001.parquet.

    The file is written under a temporary name and swapped into place in one
    step, so a crash can never leave a half-written file for the loader to pick
    up. data is a pandas DataFrame or a pyarrow Table. ingest_date defaults to
    today (UTC).
    """
    final = partition_file(source, ingest_date)
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = final.with_name(final.name + ".tmp")
    if isinstance(data, pa.Table):
        pq.write_table(data, tmp)
    else:
        data.to_parquet(tmp, index=False)
    os.replace(tmp, final)  # the loader only globs *.parquet, so it never sees the temp file
    return final
