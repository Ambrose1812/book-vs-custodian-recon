# Requires-action policy

Level 0 none | 1 routine | 2 review | 3 escalate. Highest trigger wins; all fired triggers go in `action_reason`.
Values live in `classify/action_policy.py`.

| Level | Triggers |
|---|---|
| 0 | matched, or timing_difference still inside its settlement window |
| 1 | cause identified by rules, gap < 0.5 bp of portfolio MV, age < 3 trading days |
| 2 | cause unknown; any LLM-assigned label; gap >= 0.5 bp; age >= 3 days; unexplained remainder; cause changed while open; timing gap that outlived settlement |
| 3 | gap >= 5 bp; gap >= 10% of position; age >= 6 days; split_not_applied; recurrence within 20 days; gap >= 50 bp also tagged NAV-error candidate |

## What is sourced and what is not

- **Sourced:** NAV error materiality is 0.5% (50 bp) of NAV, the line where funds must reimburse and reprocess investors. US industry practice also uses $0.01 per share. Ireland proposes 0.10% for money market funds. Luxembourg uses 0.2% for MMFs, 1% for equity UCITS, 0.5% for fixed income.
- **Sourced idea:** regulators treat recurring and cumulative errors as material even when each is small, so recurrence is a trigger.
- **Anchored (my reasoning, not a published number):** 5 bp escalate is 10% of the 50 bp line. 0.5 bp review matches one vendor's marketing example for a per-fund sign-off hold, so treat it as an example, not a standard.
- **Placeholder (no public number found):** age limits, relative-gap threshold, recurrence window. Real firms set these internally by asset class and fund size. Tune against the level distribution this project produces; if nearly everything is level 3, the thresholds are wrong for the data.
- **Not used:** the 0-30/31-60/61-90/90+ buckets common online. They come from month-end ledger reconciliation, far too slow for daily position breaks.
