"""Load landing-zone Parquet into Postgres, for every source this project has.

Idempotent per ingest_date: each partition is deleted and re-inserted
inside one transaction, so reruns never duplicate rows.

Also guarded by a Postgres advisory lock, so two copies of this script
can never run against the same database at the same time.
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

SCHEMA = "raw"
LOCK_KEY = 918273645  # any fixed integer, unique to this pipeline

LANDING = ROOT / "data" / "landing" / "openfigi"
TABLE = "openfigi_mappings"

TRANSACTIONS_LANDING = ROOT / "data" / "landing" / "transactions"
TRANSACTIONS_TABLE = "transactions"

TIINGO_LANDING = ROOT / "data" / "landing" / "tiingo"
PRICES_TABLE = "prices"

# One entry per data source: (label for logging, landing folder, raw table name)
SOURCES = [
    ("openfigi", LANDING, TABLE),
    ("transactions", TRANSACTIONS_LANDING, TRANSACTIONS_TABLE),
    ("tiingo", TIINGO_LANDING, PRICES_TABLE),
]


def get_engine():
    url = URL.create(
        "postgresql+psycopg2",
        username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", "5433")),
        database=os.environ["POSTGRES_DB"],
    )
    return create_engine(url)


def load_table_partition(engine, table: str, partition_dir: Path) -> int:
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
        if inspect(conn).has_table(table, schema=SCHEMA):
            conn.execute(
                text(f"DELETE FROM {SCHEMA}.{table} WHERE ingest_date = :d"),
                {"d": ingest_date},
            )
        df.to_sql(table, conn, schema=SCHEMA, if_exists="append", index=False)
    return len(df)


def run_all_partitions(engine):
    for label, landing_dir, table in SOURCES:
        for partition in sorted(landing_dir.glob("ingest_date=*")):
            n = load_table_partition(engine, table, partition)
            print(f"{label} {partition.name}: loaded {n} rows")


if __name__ == "__main__":
    engine = get_engine()

    with engine.connect() as lock_conn:
        got_lock = lock_conn.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_KEY}
        ).scalar()

        if not got_lock:
            print("Another load is already running. Exiting.")
            raise SystemExit(1)

        try:
            run_all_partitions(engine)
        finally:
            lock_conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})