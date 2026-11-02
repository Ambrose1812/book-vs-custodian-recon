"""Checks for the AI step. Run from the repo root: python -m unittest classify.test_llm_step -v"""
import json
import tempfile
import unittest
from pathlib import Path

from classify.llm_step import BreakCase, JsonlAuditLog, MockProvider, PROMPT_VERSION, build_prompt, classify_break

CASE = BreakCase(
    security_id="S1", first_break_date="2026-06-01",
    custodian_quantity=100, book_quantity_settled_basis=0, gap_vs_settled=100,
    baseline_method="ambiguous",
    candidate_trades=[{"transaction_id": 1, "side": "BUY", "quantity": 100},
                      {"transaction_id": 2, "side": "SELL", "quantity": 100}],
)


class LlmStepTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.audit = JsonlAuditLog(Path(self.dir.name) / "audit.jsonl")

    def tearDown(self):
        self.dir.cleanup()

    def records(self):
        return [json.loads(line) for line in self.audit.path.read_text().splitlines()]

    def test_good_reply_is_accepted_and_still_needs_review(self):
        p = MockProvider('{"cause": "missing_trade", "confidence": 0.7, "reason": "SELL not recorded"}')
        r = classify_break(CASE, p, self.audit)
        self.assertEqual(r.final_cause, "missing_trade")
        self.assertEqual(r.min_action_level, 2)  # the AI never gets the last word
        self.assertIsNone(r.validation_error)

    def test_label_outside_the_taxonomy_becomes_unknown(self):
        r = classify_break(CASE, MockProvider('{"cause": "price_mismatch", "confidence": 0.9, "reason": "x"}'), self.audit)
        self.assertEqual(r.final_cause, "unknown")
        self.assertIn("not in taxonomy", r.validation_error)

    def test_garbage_reply_becomes_unknown(self):
        r = classify_break(CASE, MockProvider("I think it is probably a missing trade."), self.audit)
        self.assertEqual(r.final_cause, "unknown")
        self.assertIn("not valid JSON", r.validation_error)

    def test_confidence_out_of_range_becomes_unknown(self):
        r = classify_break(CASE, MockProvider('{"cause": "missing_trade", "confidence": 7, "reason": "x"}'), self.audit)
        self.assertEqual(r.final_cause, "unknown")

    def test_json_inside_code_fences_is_accepted(self):
        r = classify_break(CASE, MockProvider('```json\n{"cause": "duplicate_trade", "confidence": 0.5, "reason": "x"}\n```'), self.audit)
        self.assertEqual(r.final_cause, "duplicate_trade")

    def test_provider_failure_does_not_stop_the_pipeline(self):
        class Broken(MockProvider):
            def complete(self, prompt):
                raise TimeoutError("timed out")
        r = classify_break(CASE, Broken(), self.audit)
        self.assertEqual(r.final_cause, "unknown")
        self.assertIn("provider error", r.validation_error)
        self.assertIsNone(self.records()[0]["raw_response"])

    def test_rerun_reuses_the_earlier_decision(self):
        p = MockProvider('{"cause": "missing_trade", "confidence": 0.7, "reason": "x"}')
        first = classify_break(CASE, p, self.audit)
        second = classify_break(CASE, p, self.audit)
        self.assertFalse(first.from_cache)
        self.assertTrue(second.from_cache)
        self.assertEqual(p.calls, 1)           # the model was only asked once
        self.assertEqual(len(self.records()), 1)  # and only one record was written

    def test_failed_call_is_retried_not_reused(self):
        first = classify_break(CASE, MockProvider(""), self.audit)
        self.assertEqual(first.validation_error, "empty reply")
        good = MockProvider('{"cause": "missing_trade", "confidence": 0.7, "reason": "x"}')
        second = classify_break(CASE, good, self.audit)
        self.assertFalse(second.from_cache)
        self.assertEqual(second.final_cause, "missing_trade")

    def test_provider_meta_is_recorded(self):
        p = MockProvider('{"cause": "unknown", "confidence": 0.1, "reason": "x"}')
        p.last_meta = {"stop_reason": "end_turn", "output_tokens": 12}
        classify_break(CASE, p, self.audit)
        self.assertEqual(self.records()[0]["provider_meta"]["stop_reason"], "end_turn")

    def test_audit_record_has_what_an_auditor_needs(self):
        classify_break(CASE, MockProvider(), self.audit)
        rec = self.records()[0]
        for key in ("prompt_text", "raw_response", "provider_meta", "model", "prompt_version", "final_cause", "input_hash"):
            self.assertIn(key, rec)
        self.assertEqual(rec["prompt_version"], PROMPT_VERSION)

    def test_prompt_lists_every_allowed_cause_and_the_facts(self):
        prompt = build_prompt(CASE)
        for cause in ("missing_trade", "duplicate_trade", "wrong_quantity", "split_not_applied", "unknown"):
            self.assertIn(cause, prompt)
        self.assertIn('"gap_vs_settled": 100', prompt)


if __name__ == "__main__":
    unittest.main()
