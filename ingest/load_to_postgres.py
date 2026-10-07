"""Load OpenFIGI landing Parquet into Postgres raw.openfigi_mappings.

Idempotent per ingest_date: each partition is deleted and re-inserted
inside one transaction, so reruns never duplicate rows.
"""
import os
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

LANDING = ROOT / "data" / "landing" / "openfigi"
SCHEMA, TABLE = "raw", "openfigi_mappings"


def get_engine():
    url = URL.create(
        "postgresql+psycopg2",
        username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        host="localhost",
        port=5433,
        database=os.environ["POSTGRES_DB"],
    )
    return create_engine(url)


def load_partition(engine, partition_dir: Path) -> int:
    ingest_date = date.fromisoformat(partition_dir.name.split("=")[1])
    files = sorted(partition_dir.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"No parquet files in {partition_dir}")

    df = pd.concat(
        [pd.read_parquet(f).assign(_source_file=f.name) for f in files],
        ignore_index=True,
    )
    df["ingest_date"] = ingest_date
    df["_loaded_at"] = datetime.now(timezone.utc)

    with engine.begin() as conn:  # one transaction: all or nothing
        if inspect(conn).has_table(TABLE, schema=SCHEMA):
            conn.execute(
                text(f"DELETE FROM {SCHEMA}.{TABLE} WHERE ingest_date = :d"),
                {"d": ingest_date},
            )
        df.to_sql(TABLE, conn, schema=SCHEMA, if_exists="append", index=False)
    return len(df)


if __name__ == "__main__":
    engine = get_engine()
    for partition in sorted(LANDING.glob("ingest_date=*")):
        n = load_partition(engine, partition)
        print(f"{partition.name}: loaded {n} rows")