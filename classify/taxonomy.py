"""Break causes, in one place.

The rules baseline, the LLM step, and the scoring all import these labels so
they can't drift apart. The causes match what ingest/simulate_custodian.py
plants (one cause per security). I only add a label if the generator plants it,
because without an answer key there is nothing to score it against.
"""

# Each cause with its one-line description. The LLM prompt prints these lines
# word for word, so changing one changes the prompt (bump PROMPT_VERSION).
# The first four are scored against raw.planted_breaks. "unknown" is the
# answer for "I can't tell", and it always goes to a human.
CAUSE_DESCRIPTIONS = {
    "missing_trade": "the custodian never recorded one of our trades (gap = -1 x that trade's effect_on_day)",
    "duplicate_trade": "the custodian recorded one trade twice (gap = +1 x that trade's effect_on_day)",
    "wrong_quantity": "the custodian recorded one trade at 10x the size (gap = +9 x that trade's effect_on_day)",
    "split_not_applied": "the custodian skipped a stock split "
                         "(custodian_quantity x split_factor_on_day = book_quantity_settled_basis)",
    "unknown": "the facts do not point to one cause",
}
CAUSES = tuple(CAUSE_DESCRIPTIONS)

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
