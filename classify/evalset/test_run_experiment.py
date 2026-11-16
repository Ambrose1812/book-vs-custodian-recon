"""Checks for the experiment runner. Run from the repo root:
python -m unittest classify.evalset.test_run_experiment -v"""
import json
import tempfile
import unittest
from pathlib import Path

from classify.evalset.run_experiment import expected_label, run, score, tally, to_case
from classify.llm_step import JsonlAuditLog, MockProvider, build_prompt

RECORDS = [json.loads(line) for line in (Path(__file__).parent / "cases.jsonl").read_text().splitlines()]


def truth(causes, identifiable=True):
    return {"causes": causes, "cause_identifiable": identifiable}


class ScoringTests(unittest.TestCase):
    def test_expected_label(self):
        self.assertEqual(expected_label(truth(["missing_trade"])), "missing_trade")
        self.assertEqual(expected_label(truth(["missing_trade"], identifiable=False)), "unknown")
        self.assertEqual(expected_label(truth(["split_not_applied", "missing_trade"])), "unknown")

    def test_three_outcomes(self):
        t = truth(["missing_trade"])
        self.assertEqual(score("missing_trade", t), "correct")
        self.assertEqual(score("unknown", t), "abstained")
        self.assertEqual(score("duplicate_trade", t), "wrong")

    def test_unknown_is_correct_when_the_facts_cannot_tell(self):
        t = truth(["missing_trade"], identifiable=False)
        self.assertEqual(score("unknown", t), "correct")
        self.assertEqual(score("missing_trade", t), "wrong")  # a lucky guess is still unsupported


class RunTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.audit = JsonlAuditLog(Path(self.dir.name) / "audit.jsonl")

    def tearDown(self):
        self.dir.cleanup()

    def test_clean_cases_do_not_show_the_model_how_the_rules_solved_them(self):
        for rec in RECORDS:
            case = to_case(rec)
            if rec["group"] == "clean":
                self.assertEqual(case.baseline_method, "not_run", rec["case_id"])
                self.assertNotIn("split_ratio", build_prompt(case))
            else:
                self.assertEqual(case.baseline_method, rec["packet"]["baseline_method"])

    def test_the_ops_note_reaches_the_prompt(self):
        rec = next(r for r in RECORDS if r["variant"] == "with_note")
        self.assertIn(rec["packet"]["ops_note"], json.loads(json.dumps(build_prompt(to_case(rec)))))

    def test_a_model_that_always_says_unknown(self):
        rows = run(RECORDS, MockProvider(), self.audit)
        self.assertEqual(len(rows), 62)
        # With an always-unknown model, the pipeline is exactly the rules.
        self.assertEqual(tally(rows, "pipeline"), tally(rows, "rules"))
        # The rules solve the 8 clean cases and abstain everywhere else, never wrong.
        self.assertEqual(tally(rows, "rules")["wrong"], 0)
        self.assertEqual(sum(r["rules_outcome"] == "correct" and r["group"] == "clean" for r in rows), 8)

    def test_a_rerun_reuses_every_decision(self):
        provider = MockProvider('{"cause": "missing_trade", "confidence": 0.9, "reason": "test"}')
        first = run(RECORDS, provider, self.audit)
        calls = provider.calls
        second = run(RECORDS, provider, self.audit)
        self.assertEqual(provider.calls, calls)
        self.assertTrue(all(r["from_cache"] for r in second))
        self.assertEqual([r["model"] for r in first], [r["model"] for r in second])

    def test_pipeline_only_uses_the_model_where_the_rules_gave_up(self):
        rows = run(RECORDS, MockProvider('{"cause": "duplicate_trade", "confidence": 1, "reason": "x"}'), self.audit)
        for r in rows:
            self.assertEqual(r["pipeline"], r["rules"] if r["rules"] != "unknown" else "duplicate_trade")


if __name__ == "__main__":
    unittest.main()
