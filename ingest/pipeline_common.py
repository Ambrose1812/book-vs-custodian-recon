"""Paths, calendar and file-writing helper shared by the ingest scripts.

Every script that lands data used to build its own partition folder and write
its own Parquet file. Doing it in one place means they all write the same way.
"""
import os
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

ROOT = Path(__file__).resolve().parent.parent
LANDING_ROOT = ROOT / "data" / "landing"

# US federal holidays, not the NYSE calendar (see README, known limitations).
US_BDAY = CustomBusinessDay(calendar=USFederalHolidayCalendar())


def write_partition(data, source: str, ingest_date=None) -> Path:
    """Write data to data/landing/<source>/ingest_date=<date>/part-0001.parquet.

    The file is written under a temporary name and swapped into place in one
    step, so a crash can never leave a half-written file for the loader to pick
    up. data is a pandas DataFrame or a pyarrow Table. ingest_date defaults to
    today (UTC).
    """
    ingest_date = ingest_date or datetime.now(timezone.utc).date()
    out_dir = LANDING_ROOT / source / f"ingest_date={ingest_date}"
    out_dir.mkdir(parents=True, exist_ok=True)
    final = out_dir / "part-0001.parquet"
    tmp = out_dir / "part-0001.parquet.tmp"
    if isinstance(data, pa.Table):
        pq.write_table(data, tmp)
    else:
        data.to_parquet(tmp, index=False)
    os.replace(tmp, final)  # the loader only globs *.parquet, so it never sees the temp file
    return final
