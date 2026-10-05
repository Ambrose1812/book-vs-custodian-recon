import csv
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
UNIVERSE = ROOT / "ingest" / "universe.csv"
LANDING = ROOT / "data" / "landing" / "openfigi"
URL = "https://api.openfigi.com/v3/mapping"
BATCH_SIZE = 10  # no-key limit from memory; check OpenFIGI docs
FIELDS = ["figi", "name", "ticker", "exchCode", "compositeFIGI",
          "shareClassFIGI", "securityType", "securityType2", "marketSector"]

load_dotenv(ROOT / ".env")
API_KEY = os.getenv("OPENFIGI_API_KEY")


def read_universe():
    with open(UNIVERSE, newline="") as f:
        return list(csv.DictReader(f))


def post_batch(jobs, max_retries=5):
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["X-OPENFIGI-APIKEY"] = API_KEY
    for attempt in range(max_retries):
        resp = requests.post(URL, json=jobs, headers=headers, timeout=30)
        if resp.status_code == 429:  # rate limited: wait, then retry
            time.sleep(10 * (attempt + 1))
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError("Still rate limited after retries")


def flatten(batch, results, batch_id, ingested_at):
    rows = []
    for row, result in zip(batch, results):  # results come back in input order
        base = {
            "input_ticker": row["ticker"],
            "input_exch_code": row["exch_code"],
            "_ingested_at": ingested_at,
            "_source": "openfigi",
            "_batch_id": batch_id,
            "raw_response": json.dumps(result),
        }
        matches = result.get("data", [])
        if not matches:
            rows.append({**base, "match_status": "no_match", "match_count": 0,
                         **{f: None for f in FIELDS}})
        for m in matches:
            rows.append({**base, "match_status": "matched",
                         "match_count": len(matches),
                         **{f: m.get(f) for f in FIELDS}})
    return rows


def write_parquet(rows, ingest_date):
    out_dir = LANDING / f"ingest_date={ingest_date}"
    out_dir.mkdir(parents=True, exist_ok=True)
    final = out_dir / "part-0001.parquet"
    tmp = out_dir / "part-0001.parquet.tmp"
    pq.write_table(pa.Table.from_pylist(rows), tmp)
    os.replace(tmp, final)  # swap into place in one step
    return final


def main():
    universe = read_universe()
    batch_id = str(uuid.uuid4())
    ingested_at = datetime.now(timezone.utc).isoformat()
    all_rows = []

    for i in range(0, len(universe), BATCH_SIZE):
        batch = universe[i:i + BATCH_SIZE]
        jobs = [{"idType": "TICKER", "idValue": r["ticker"],
                 "exchCode": r["exch_code"]} for r in batch]
        results = post_batch(jobs)
        assert len(results) == len(jobs), "response size mismatch"
        all_rows += flatten(batch, results, batch_id, ingested_at)
        time.sleep(3)  # stay under the per-minute limit

    path = write_parquet(all_rows, ingested_at[:10])
    unmapped = sum(r["match_status"] == "no_match" for r in all_rows)
    print(f"Wrote {len(all_rows)} rows to {path} ({unmapped} unmapped)")


if __name__ == "__main__":
    main()