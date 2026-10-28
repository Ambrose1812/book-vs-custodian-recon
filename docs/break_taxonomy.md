# Break taxonomy

Status says WHAT the recon sees (`recon_status`). Cause says WHY. This file defines cause.
Source of truth in code: `classify/taxonomy.py`.

## Causes (one per break, matching what the generator plants)

| Cause | Signature in the data | Planted by |
|---|---|---|
| `missing_trade` | From the bad trade's settlement date, gap = -1 x that trade's signed quantity | `plant_errors`, N_MISSING |
| `duplicate_trade` | From the bad trade's settlement date, gap = +1 x that trade's signed quantity | N_DUPLICATE |
| `wrong_quantity` | From the bad trade's settlement date, gap = +9 x that trade's signed quantity (10x slip) | N_WRONG_QTY |
| `split_not_applied` | From the ex-date, custodian quantity = book quantity / split factor, held security only | N_SPLIT_SKIPPED |
| `unknown` | No signature matches within tolerance | never planted |

Gap = custodian quantity - book quantity, trade basis, using `recon_tolerance` (0.001 shares).

## Key identification rule

The first break day is the bad trade's settlement date (the same `effective_date` the
answer key stores). So: find the trades in the book that settle on the first break day
for that security, then compute gap / signed_qty. A ratio of -1, +1 or +9 names the
cause and the trade. If no trade fits, or the first break day is a split ex-date, try
the split ratio. If nothing fits, `unknown`.

## Known ambiguity to test on purpose

A missing SELL and a duplicated BUY of the same size give the same gap sign and size.
The settlement-date lookup usually separates them, but a security with two trades
settling the same day does not. Plant that case in a harder tier.

## What is NOT in the taxonomy, and why

- `price_mismatch`, `identifier_mismatch`: the custodian feed is quantity-only, so
  these cannot be detected or scored.
- `timing_difference`: already a recon status, and not a break (see decisions.md).
  It expires by construction: it is defined against the settled book, so once a trade
  settles the explanation no longer applies and a remaining gap becomes `quantity_break`.
- Combined causes: the generator plants one cause per security. Needs a generator
  change first, then a second scored tier.

## Difficulty tiers

- **Tier 1 (in the data):** one cause per security, one candidate trade. Rules baseline scores 14 of 14.
- **Tier 2 (hand-built fixtures, `unit_tests_cause_baseline.yml`):** ambiguity (two trades settle the same day and both explain the gap) and combined causes (missing trade plus unapplied split). Correct behavior is to abstain with `unknown`, never to guess. Scored as `abstained`, not `wrong`, in `eval_cause_scoring.outcome`.
- **Why fixtures, not more planted breaks:** 14 of the 19 securities already carry a planted cause (5 controls left), and the transaction generator is unseeded, so regenerating would change every number in Project A. Fixtures add hard cases without touching the real data.
- **Identifiable in principle?** A gap that two different trades explain equally well cannot be resolved from positions alone. Any approach, rules or LLM, should abstain there. A settlement-status feed would resolve it, which is why that feed is a good later extension.
