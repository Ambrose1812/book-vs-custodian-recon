"""Checks for the test set. Run from the repo root: python -m unittest classify.evalset.test_cases -v"""
import json
import unittest
from pathlib import Path

from classify.evalset.generate_cases import baseline, generate

FILE = Path(__file__).parent / "cases.jsonl"


class CaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bases, cls.records = generate()

    def test_counts(self):
        groups = {}
        for r in self.records:
            groups[r["group"]] = groups.get(r["group"], 0) + 1
        self.assertEqual(groups, {"clean": 8, "ambiguous": 30, "combined": 10, "noise": 6, "near_miss": 8})
        self.assertEqual(len(self.bases), 42)

    def test_file_matches_a_fresh_run(self):
        saved = [json.loads(line) for line in FILE.read_text().splitlines()]
        self.assertEqual(saved, json.loads(json.dumps(self.records)))

    def test_rules_solve_every_clean_case(self):
        for r in self.records:
            if r["group"] == "clean":
                self.assertEqual(r["baseline"]["label"], r["truth"]["causes"][0], r["case_id"])

    def test_rules_abstain_on_everything_that_is_not_clean(self):
        for r in self.records:
            if r["group"] != "clean":
                self.assertEqual(r["baseline"]["label"], "unknown", r["case_id"])

    def test_ambiguous_cases_come_in_three_variants(self):
        for b in self.bases:
            if b["group"] == "ambiguous":
                variants = {r["variant"] for r in self.records if r["base_id"] == b["id"]}
                self.assertEqual(variants, {"numbers_only", "with_structured", "with_note"})

    def test_evidence_only_appears_in_its_own_variant(self):
        for r in self.records:
            trades = r["packet"]["candidate_trades"]
            has_status = any("custodian_instruction_status" in t for t in trades)
            self.assertEqual(has_status, r["variant"] == "with_structured", r["case_id"])
            self.assertEqual(r["packet"]["ops_note"] is not None, r["variant"] == "with_note", r["case_id"])

    def test_notes_do_not_contain_the_answer_labels(self):
        for r in self.records:
            note = (r["packet"]["ops_note"] or "").lower()
            for label in ("missing_trade", "duplicate_trade", "wrong_quantity", "split_not_applied"):
                self.assertNotIn(label, note, r["case_id"])

    def test_python_copy_of_the_rules_matches_the_dbt_unit_test_cases(self):
        def packet(gap, custodian, book, trades, s=1.0):
            return {"gap_vs_settled": gap, "custodian_quantity": custodian, "book_quantity_settled_basis": book,
                    "candidate_trades": trades, "split_factor_on_day": s}
        t = lambda i, eff: {"transaction_id": i, "effect_on_day": eff}
        self.assertEqual(baseline(packet(100, 100, 0, [t(1, 100), t(2, -100)])), ("unknown", "ambiguous"))       # S1
        self.assertEqual(baseline(packet(-50, 50, 100, [t(3, 50), t(4, 50)])), ("unknown", "ambiguous"))         # S2
        self.assertEqual(baseline(packet(-100, 0, 100, [t(5, 100)])), ("missing_trade", "trade_ratio"))          # S3
        self.assertEqual(baseline(packet(-200, 100, 300, [t(11, 100)], 2)), ("unknown", "no_signature"))         # S4


if __name__ == "__main__":
    unittest.main()
