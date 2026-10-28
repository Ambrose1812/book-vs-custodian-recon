"""Break causes, in one place.

The rules baseline, the LLM step, and the scoring all import these labels so
they can't drift apart. The causes match what ingest/simulate_custodian.py
plants (one cause per security). I only add a label if the generator plants it,
because without an answer key there is nothing to score it against.
"""

# The first four are scored against raw.planted_breaks. "unknown" is the
# answer for "I can't tell", and it always goes to a human.
CAUSES = (
    "missing_trade",      # custodian never recorded one trade: gap is -1x that trade's quantity
    "duplicate_trade",    # custodian recorded one trade twice: gap is +1x
    "wrong_quantity",     # custodian recorded one trade at 10x: gap is +9x
    "split_not_applied",  # custodian skipped a split: constant ratio from the ex-date
    "unknown",
)

# The labels that can appear in the answer key. Nothing plants "unknown".
SCORED_CAUSES = CAUSES[:-1]

# How many times one trade's signed quantity the gap is, for each trade-level cause.
TRADE_MULTIPLE = {
    "missing_trade": -1.0,
    "duplicate_trade": 1.0,
    "wrong_quantity": 9.0,
}

# The recon_status values in fct_recon_positions that count as breaks.
# Status is what the recon sees, cause is why it happened. They are different things.
BREAK_STATUSES = ("quantity_break", "missing_on_custodian", "missing_in_book")
