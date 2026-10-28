"""When does a break need a human, and how urgently.

The highest level that fires wins, and every trigger that fired gets written
to action_reason. The thresholds live here and not in the SQL, so I can explain
each one in decisions.md and change it without touching the logic.

Each value is marked as a public number, scaled from one, or a placeholder.
docs/action_policy.md has the sources and what is still a guess.
"""

LEVELS = {0: "none", 1: "routine", 2: "review", 3: "escalate"}

# Size of the gap in market value, as basis points of total portfolio market
# value (1 bp = 0.01%). A percentage works at any fund size, and NAV error
# materiality is quoted as a percent of NAV too.
GAP_BPS_REVIEW = 0.5        # level 2 floor. Scaled from one vendor's example sign-off limit.
GAP_BPS_ESCALATE = 5.0      # level 3. My choice: a tenth of the 50 bp line below.
NAV_MATERIALITY_BPS = 50.0  # public number: 0.5% of NAV. Only used to tag the break.

# Gap as a share of the book position. Catches the 10x slip on a small holding.
RELATIVE_GAP_ESCALATE = 0.10  # placeholder

# Age of an open break episode in trading days. It counts from the first flag,
# which for a trade break is the settlement date.
AGE_REVIEW_TRADING_DAYS = 3     # placeholder: past T+1 plus a day of slack
AGE_ESCALATE_TRADING_DAYS = 6   # placeholder: more than one trading week

# The same security breaks again within this many trading days of clearing.
RECURRENCE_WINDOW_TRADING_DAYS = 20  # placeholder. Recurrence itself is a real materiality factor.

# Rules based on the cause.
ALWAYS_ESCALATE_CAUSES = ("split_not_applied",)  # corporate actions cause quiet errors
ALWAYS_REVIEW_CAUSES = ("unknown",)

# Anything the LLM labels is at least level 2, and the LLM never closes a break.
LLM_ASSIGNED_MIN_LEVEL = 2
LLM_CONFIDENCE_MIN = None  # set once the LLM step exists and I can measure it
