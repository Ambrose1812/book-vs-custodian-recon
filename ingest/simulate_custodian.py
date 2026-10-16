"""Simulate the custodian's daily holdings statement, with planted breaks.

The custodian is an independent record: it is built from the raw transaction
feed (not from our fct_positions model), so any disagreement with our book has
a real cause. Differences from our book:

  * It reports SETTLED holdings: a trade counts from its settlement date, not
    its trade date. This creates legitimate timing differences (not errors).
  * It reports in as-of share terms, like a real custodian, using the same
    cumulative split factors as our prices.

On top of that we plant known errors, one cause per security so that results
can be scored cleanly, and keep five or more securities untouched as controls
(a recon that flags those is producing false positives):

  missing_trade    the custodian never recorded one trade
  wrong_quantity   one trade recorded with 10x the quantity (decimal slip)
  duplicate_trade  one trade recorded twice
  split_not_applied the custodian never applied one stock split

The answer key is written to data/landing/truth/ and loads to
raw.planted_breaks, so a dbt test can score the recon against it. It is a
simulation fixture, never an input to the recon models. A fixed seed makes the
plant reproducible for a given transaction file.
"""
import random
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay
from sqlalchemy import text

from load_to_postgres import get_engine

ROOT = Path(__file__).resolve().parent.parent
TX_LANDING = ROOT / "data" / "landing" / "transactions"
OUT = ROOT / "data" / "landing" / "custodian"
TRUTH = ROOT / "data" / "landing" / "truth"

SEED = 42
N_MISSING = 6
N_WRONG_QTY = 4
N_DUPLICATE = 3
N_SPLIT_SKIPPED = 2

US_BDAY = CustomBusinessDay(calendar=USFederalHolidayCalendar())


def ns(values) -> np.ndarray:
    """Dates as datetime64[ns] so searchsorted compares like with like."""
    return pd.to_datetime(pd.Series(values)).to_numpy().astype("datetime64[ns]")


def make_factor_lookup(prices: pd.DataFrame, skipped: list[dict]):
    """Return f(ticker, dates) -> cumulative split factor in force on each date.

    A date before a ticker's first price, or a ticker with no prices, gets 1.
    For each skipped split, dates on or after its ex-date are divided by that
    split's factor, i.e. the custodian behaves as if the split never happened.
    """
    series = {}
    for ticker, g in prices.sort_values("price_date").groupby("ticker"):
        series[ticker] = (ns(g["price_date"]), g["cum_split_factor"].astype(float).to_numpy())

    def factor_of(ticker: str, dates) -> np.ndarray:
        q = ns(dates)
        if ticker not in series:
            f = np.ones(len(q))
        else:
            px_dates, cum = series[ticker]
            idx = np.searchsorted(px_dates, q, side="right") - 1
            f = np.where(idx >= 0, cum[np.maximum(idx, 0)], 1.0)
        for s in skipped:
            if s["ticker"] == ticker:
                f = np.where(q >= ns([s["ex_date"]])[0], f / s["split_factor"], f)
        return f

    return factor_of


def daily_holdings(trades: pd.DataFrame, factor_of, dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Settled holdings per security per date, in as-of share terms.

    shares_D = F_D * sum(q_i / F_i) over trades settled on or before D, where
    F_i is the cumulative split factor on trade i's trade date and F_D the
    factor on date D. Zero positions are omitted, like a real statement.
    """
    day_ns = ns(dates)
    frames = []
    for sec, g in trades.groupby("security_id"):
        ticker = g["ticker"].iloc[0]
        base = g["signed_qty"].to_numpy() / factor_of(ticker, g["trade_date"])
        order = np.argsort(ns(g["settlement_date"]))
        settle = ns(g["settlement_date"])[order]
        cum = np.cumsum(base[order])
        idx = np.searchsorted(settle, day_ns, side="right")
        settled_base = np.where(idx > 0, cum[np.maximum(idx - 1, 0)], 0.0)
        qty = np.round(settled_base * factor_of(ticker, day_ns), 6)
        keep = np.abs(qty) > 1e-6
        frames.append(pd.DataFrame({
            "as_of_date": pd.to_datetime(day_ns[keep]).date,
            "security_id": sec,
            "quantity": qty[keep],
        }))
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["as_of_date", "security_id", "quantity"])
    return out.sort_values(["as_of_date", "security_id"]).reset_index(drop=True)


def plant_errors(trades: pd.DataFrame, split_events: pd.DataFrame, rng: random.Random):
    """Return (custodian_trades, skipped_splits, truth_rows). One cause per security."""
    secs = sorted(trades["security_id"].unique())
    rng.shuffle(secs)

    # Securities whose split actually matters: shares settled before the ex-date.
    first_settle = trades.groupby("security_id")["settlement_date"].min()
    skipped = []
    for ev in split_events.sample(frac=1, random_state=SEED).itertuples():
        if len(skipped) == N_SPLIT_SKIPPED:
            break
        if ev.security_id in first_settle.index and first_settle[ev.security_id] < ev.ex_date \
                and all(s["security_id"] != ev.security_id for s in skipped):
            skipped.append(dict(security_id=ev.security_id, ticker=ev.ticker,
                                ex_date=ev.ex_date, split_factor=float(ev.split_factor)))
    used = {s["security_id"] for s in skipped}
    pool = [s for s in secs if s not in used]

    def pick_trade(sec):
        g = trades[trades["security_id"] == sec]
        return g.iloc[rng.randrange(len(g))]

    truth = [dict(break_type="split_not_applied", security_id=s["security_id"], ticker=s["ticker"],
                  transaction_id=None, effective_date=s["ex_date"].date(),
                  detail=f"custodian never applied the {s['split_factor']:g}-for-1 split")
             for s in skipped]

    cust = trades.copy()
    plan = [("missing_trade", N_MISSING), ("wrong_quantity", N_WRONG_QTY), ("duplicate_trade", N_DUPLICATE)]
    extra_rows = []
    for kind, n in plan:
        for _ in range(n):
            sec = pool.pop()
            t = pick_trade(sec)
            tid = t["transaction_id"]
            if kind == "missing_trade":
                cust = cust[cust["transaction_id"] != tid]
                detail = f"trade {tid} ({t['side']} {t['quantity']}) not recorded by custodian"
            elif kind == "wrong_quantity":
                cust.loc[cust["transaction_id"] == tid, "quantity"] = t["quantity"] * 10
                cust.loc[cust["transaction_id"] == tid, "signed_qty"] = t["signed_qty"] * 10
                detail = f"trade {tid} recorded as {t['quantity'] * 10} instead of {t['quantity']}"
            else:
                extra_rows.append(t.to_dict())
                detail = f"trade {tid} ({t['side']} {t['quantity']}) recorded twice"
            truth.append(dict(break_type=kind, security_id=sec, ticker=t["ticker"], transaction_id=int(tid),
                              effective_date=pd.Timestamp(t["settlement_date"]).date(), detail=detail))
    if extra_rows:
        cust = pd.concat([cust, pd.DataFrame(extra_rows)], ignore_index=True)
    return cust, skipped, pd.DataFrame(truth)


def load_inputs(engine):
    with engine.connect() as conn:
        sec = pd.read_sql(text("SELECT security_id, ticker FROM marts.dim_security_master"), conn)
        prices = pd.read_sql(text(
            "SELECT ticker, price_date, split_factor, cum_split_factor "
            "FROM intermediate.int_prices_split_indexed"), conn)
    partition = sorted(TX_LANDING.glob("ingest_date=*"))[-1]
    trades = pd.concat([pd.read_parquet(f) for f in sorted(partition.glob("*.parquet"))], ignore_index=True)
    return sec, prices, trades


if __name__ == "__main__":
    engine = get_engine()
    sec, prices, trades = load_inputs(engine)
    if trades.empty or prices.empty:
        raise SystemExit("Need transactions in the landing zone and built prices (run dbt first).")

    sec = sec.drop_duplicates("ticker")
    trades = trades.merge(sec, on="security_id", how="left")
    for col in ("trade_date", "settlement_date"):
        trades[col] = pd.to_datetime(trades[col])
    prices["price_date"] = pd.to_datetime(prices["price_date"])
    trades["signed_qty"] = np.where(trades["side"] == "BUY", trades["quantity"], -trades["quantity"])

    split_events = prices[prices["split_factor"].astype(float) != 1.0].merge(sec, on="ticker")
    split_events = split_events.rename(columns={"price_date": "ex_date"})[
        ["security_id", "ticker", "ex_date", "split_factor"]]

    rng = random.Random(SEED)
    cust_trades, skipped, truth = plant_errors(trades, split_events, rng)
    factor_of = make_factor_lookup(prices, skipped)
    dates = pd.date_range(trades["trade_date"].min(), prices["price_date"].max(), freq=US_BDAY)
    holdings = daily_holdings(cust_trades, factor_of, dates)

    ingest_date = datetime.now(timezone.utc).date()
    part = OUT / f"ingest_date={ingest_date}"
    part.mkdir(parents=True, exist_ok=True)
    holdings.to_parquet(part / "part-0001.parquet", index=False)

    truth_part = TRUTH / f"ingest_date={ingest_date}"
    truth_part.mkdir(parents=True, exist_ok=True)
    truth.insert(0, "break_id", range(1, len(truth) + 1))
    truth["transaction_id"] = truth["transaction_id"].astype("Int64")
    truth.to_parquet(truth_part / "part-0001.parquet", index=False)

    clean = trades["security_id"].nunique() - len(truth)
    print(f"Wrote {len(holdings)} holdings rows to {part / 'part-0001.parquet'}")
    print(f"Planted {len(truth)} breaks ({truth['break_type'].value_counts().to_dict()}); "
          f"{clean} securities left clean as controls")
    if len(skipped) < N_SPLIT_SKIPPED:
        print(f"Note: only {len(skipped)} split(s) were eligible to skip.")
