"""Simulate buy/sell transactions for securities in dim_security_master.

Settlement date follows the real US equities rule: trade date + 1 business
day (T+1, in effect since May 2024), using the US federal holiday calendar
so weekends and market holidays are correctly skipped.

A running position is tracked per security while generating, so a SELL
can never exceed shares actually held at that point — never happens in
real markets, so the simulation shouldn't allow it either.

Every transaction's trade_date is decided up front, before generation,
so generation order and chronological order are guaranteed to match —
otherwise the no-oversell check is only valid in generation order, not
in the trade_date order positions actually reads.
"""
import random
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay
from sqlalchemy import text

from load_to_postgres import get_engine

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "landing" / "transactions"

N_TRANSACTIONS = 350
START_DATE = date(2026, 4, 1)
END_DATE = date(2026, 10, 1)

US_BDAY = CustomBusinessDay(calendar=USFederalHolidayCalendar())


def load_securities(engine) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT security_id, ticker FROM marts.dim_security_master")
        ).mappings().all()
    return [dict(r) for r in rows]


def random_business_day(start: date, end: date) -> date:
    days = pd.bdate_range(start, end)
    return days[random.randint(0, len(days) - 1)].date()


def generate_transactions(securities: list[dict], n: int) -> pd.DataFrame:
    rows = []
    holdings = {s["security_id"]: 0 for s in securities}

    # Decide every transaction's security and trade_date FIRST, fixed and final,
    # then sort by that same trade_date before generating sides/quantities.
    # This guarantees generation order == chronological order, so the
    # no-oversell check is enforced in the same order positions will read.
    planned = [
        dict(security_id=s["security_id"], trade_date=random_business_day(START_DATE, END_DATE), seed=True)
        for s in securities
    ]
    planned += [
        dict(
            security_id=random.choice(securities)["security_id"],
            trade_date=random_business_day(START_DATE, END_DATE),
            seed=False,
        )
        for _ in range(n - len(securities))
    ]

    dated = sorted(planned, key=lambda p: p["trade_date"])

    for i, p in enumerate(dated):
        sec_id = p["security_id"]
        trade_date = p["trade_date"]
        settlement_date = trade_date + US_BDAY * 1
        price = round(random.uniform(50, 450), 2)

        if p["seed"] or holdings[sec_id] == 0:
            side, qty = "BUY", random.randint(10, 200)
        else:
            side = random.choices(["BUY", "SELL"], weights=[0.6, 0.4])[0]
            qty = random.randint(1, holdings[sec_id]) if side == "SELL" else random.randint(10, 200)

        holdings[sec_id] += qty if side == "BUY" else -qty

        rows.append(dict(
            transaction_id=i + 1,
            security_id=sec_id,
            trade_date=trade_date,
            settlement_date=settlement_date.date(),
            side=side,
            quantity=qty,
            price=price,
        ))

    return pd.DataFrame(rows).sort_values("trade_date").reset_index(drop=True)


if __name__ == "__main__":
    engine = get_engine()
    securities = load_securities(engine)
    if not securities:
        raise SystemExit("marts.dim_security_master is empty — build it first.")

    df = generate_transactions(securities, N_TRANSACTIONS)

    ingest_date = datetime.now(timezone.utc).date()
    partition_dir = OUT / f"ingest_date={ingest_date}"
    partition_dir.mkdir(parents=True, exist_ok=True)

    out_path = partition_dir / "part-0001.parquet"
    df.to_parquet(out_path, index=False)
    print(f"Wrote {len(df)} transactions to {out_path}")