"""A small dry run: four hand-made breaks through the real AI.

Run from the repo root: python -m classify.dry_run
Four calls to the cheapest model, so a fraction of a cent. Decisions are saved in
data/audit/dry_run.jsonl, and a rerun reuses them (free). Delete that file to
ask the model again.
"""

from classify.llm_step import BreakCase, JsonlAuditLog, classify_break
from classify.providers import ROOT, AnthropicProvider

CASES = {
    "S1 two trades fit (BUY 100 / SELL 100)": BreakCase(
        "S1", "2026-06-01", 100, 0, 100, "ambiguous",
        [{"transaction_id": 1, "side": "BUY", "quantity": 100},
         {"transaction_id": 2, "side": "SELL", "quantity": 100}]),
    "S2 two identical BUYs, one missing": BreakCase(
        "S2", "2026-06-01", 50, 100, -50, "ambiguous",
        [{"transaction_id": 3, "side": "BUY", "quantity": 50},
         {"transaction_id": 4, "side": "BUY", "quantity": 50}]),
    "S3 one clean candidate": BreakCase(
        "S3", "2026-06-01", 0, 100, -100, "no_signature",
        [{"transaction_id": 5, "side": "BUY", "quantity": 100}]),
    "S4 missing trade plus split": BreakCase(
        "S4", "2026-06-02", 100, 300, -200, "no_signature",
        [{"transaction_id": 11, "side": "BUY", "quantity": 50}], split_factor_on_day=2.0),
}

if __name__ == "__main__":
    provider = AnthropicProvider()
    audit = JsonlAuditLog(ROOT / "data" / "audit" / "dry_run.jsonl")
    print(f"model: {provider.model}\n")
    for label, case in CASES.items():
        r = classify_break(case, provider, audit)
        print(f"{label}\n  cause: {r.final_cause}  confidence: {r.confidence}  "
              f"min level: {r.min_action_level}  reused: {r.from_cache}")
        print(f"  reason: {r.reason}")
        if r.validation_error:
            print(f"  problem: {r.validation_error}")
