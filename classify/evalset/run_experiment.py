"""The AI-versus-rules experiment: every test packet through the rules and the model.

Run from the repo root:
    python -m classify.evalset.run_experiment          real model, needs ANTHROPIC_API_KEY
    python -m classify.evalset.run_experiment --mock   fake model that always says unknown;
                                                       writes to a temp folder, not the repo
    python -m classify.evalset.run_experiment --holdout   the held-out set (holdout.jsonl).
        Scored once per prompt version: it refuses to run again if that version's
        held-out results exist. Only run it on a prompt you have stopped changing.

Three systems are scored against the known right answer of each packet:
    rules     the rules baseline alone (already stored in cases.jsonl)
    model     the model alone, called through classify_break, so the reply is
              validated and every call is written to the audit log
    pipeline  what would actually ship: rules first, model only where the rules
              said unknown

Model decisions are kept in data/audit/experiment.jsonl and reused on a rerun, so a
second run costs nothing and gives the same numbers. Delete that file to ask again.

Outputs, next to this file, named after the prompt version so earlier runs are
kept for comparison: results_<version>.jsonl (one line per packet) and
RESULTS_<version>.md (the summary tables). Both are generated. Write conclusions
somewhere else.
"""
from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass, fields
from pathlib import Path

from classify.llm_step import PROMPT_VERSION, BreakCase, JsonlAuditLog, MockProvider, classify_break

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
SYSTEMS = ("rules", "model", "pipeline")
OUTCOMES = ("correct", "abstained", "wrong")


@dataclass
class EvalCase(BreakCase):
    """A BreakCase plus the free-text ops note that some test packets carry."""
    ops_note: str | None = None


def to_case(record: dict) -> EvalCase:
    packet = dict(record["packet"])
    # On a clean case the rules already found the answer, and baseline_method would
    # say how ("split_ratio" gives it away). The model alone must not see that.
    if record["baseline"]["label"] != "unknown":
        packet["baseline_method"] = "not_run"
    return EvalCase(**{f.name: packet[f.name] for f in fields(EvalCase)})


def expected_label(truth: dict) -> str:
    """The right single label. If the facts cannot identify the cause, or there
    are two causes at once, the only honest single label is unknown."""
    causes = truth["causes"]
    return causes[0] if truth["cause_identifiable"] and len(causes) == 1 else "unknown"


def score(answer: str, truth: dict) -> str:
    """correct    the right label, including a correct "unknown"
    abstained  said unknown when a cause could be named: a safe miss, a human looks
    wrong      named a cause the facts do not support: the dangerous one"""
    if answer == expected_label(truth):
        return "correct"
    return "abstained" if answer == "unknown" else "wrong"


def run(records: list[dict], provider, audit: JsonlAuditLog) -> list[dict]:
    rows = []
    for i, rec in enumerate(records, 1):
        result = classify_break(to_case(rec), provider, audit)
        rules = rec["baseline"]["label"]
        answers = {
            "rules": rules,
            "model": result.final_cause,
            "pipeline": rules if rules != "unknown" else result.final_cause,
        }
        row = {
            "case_id": rec["case_id"], "group": rec["group"], "variant": rec["variant"],
            "true_causes": rec["truth"]["causes"], "expected": expected_label(rec["truth"]),
            "model_confidence": result.confidence, "model_reason": result.reason,
            "model_error": result.validation_error, "from_cache": result.from_cache,
        }
        for s in SYSTEMS:
            row[s] = answers[s]
            row[f"{s}_outcome"] = score(answers[s], rec["truth"])
        # A wrong answer that still names one of the real causes (a lucky guess on an
        # ambiguous case, or one cause out of two on a combined case).
        row["model_named_a_true_cause"] = (
            row["model_outcome"] == "wrong" and result.final_cause in rec["truth"]["causes"])
        rows.append(row)
        print(f"[{i}/{len(records)}] {rec['case_id']}: model={result.final_cause} "
              f"({row['model_outcome']}{', cached' if result.from_cache else ''})")
    return rows


def tally(rows: list[dict], system: str) -> dict:
    counts = dict.fromkeys(OUTCOMES, 0)
    for r in rows:
        counts[r[f"{system}_outcome"]] += 1
    return counts


def summary_markdown(rows: list[dict], provider, set_name: str = "development") -> str:
    def table(title, key):
        groups = {}
        for r in rows:
            groups.setdefault(key(r), []).append(r)
        head = "| " + title + " | Packets | " + " | ".join(
            f"{s}: correct / abstained / wrong" for s in SYSTEMS) + " |"
        lines = [head, "|---|---|" + "---|" * len(SYSTEMS)]
        for name, part in list(groups.items()) + [("**all**", rows)]:
            cells = [" / ".join(str(tally(part, s)[o]) for o in OUTCOMES) for s in SYSTEMS]
            lines.append(f"| {name} | {len(part)} | " + " | ".join(cells) + " |")
        return lines

    errors = sum(r["model_error"] is not None for r in rows)
    lucky = sum(r["model_named_a_true_cause"] for r in rows)
    wrong_conf = [r["model_confidence"] for r in rows if r["model_outcome"] == "wrong"]
    lines = [
        "# AI versus rules: results", "",
        "Generated by `python -m classify.evalset.run_experiment`. Do not edit by hand.", "",
        f"- Model: `{provider.model}` (provider: {provider.name}), prompt version `{PROMPT_VERSION}`",
        f"- Case set: {set_name}. Packets: {len(rows)}, all invented test cases with a known right answer",
        "- " + ("Held out: generated with a different seed, never read or tuned against before this run."
                if set_name == "held-out" else
                "Development set: the prompt was revised after reading these results (see CASES_FOR_REVIEW.md)."),
        f"- Model replies that failed validation or errored (counted as unknown): {errors}",
        f"- Model answers scored wrong that still named a real cause: {lucky} of {len(wrong_conf)}",
        "- Average model confidence on its wrong answers: "
        + (f"{sum(wrong_conf) / len(wrong_conf):.2f}" if wrong_conf else "n/a (none wrong)"), "",
        "How to read a cell: correct / abstained / wrong.",
        "**correct** includes saying unknown when unknown is right. **abstained** is saying unknown "
        "when a cause could be named (safe: a person looks). **wrong** is naming a cause the facts "
        "do not support (dangerous: it looks resolved).", "",
        "rules = the rules alone. model = the model alone. pipeline = rules first, model only "
        "where the rules said unknown.", "",
        "## By group", "", *table("Group", lambda r: r["group"]), "",
        "## Ambiguous cases, by how much evidence the packet carries", "",
        *table("Evidence", lambda r: r["variant"] if r["group"] == "ambiguous" else "(other groups)"), "",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> None:
    holdout = "--holdout" in argv
    set_name, file, tag = ("held-out", "holdout.jsonl", "_holdout") if holdout else ("development", "cases.jsonl", "")
    records = [json.loads(line) for line in (HERE / file).read_text().splitlines()]
    results_md = f"RESULTS_{PROMPT_VERSION}{tag}.md"
    if holdout and "--mock" not in argv and (HERE / results_md).exists():
        raise SystemExit(f"{results_md} already exists. The held-out set is scored once per prompt "
                         "version; a rerun after looking at the result would make it a tuning set.")
    if "--mock" in argv:  # a plumbing check: nothing it produces belongs in the repo
        out_dir = Path(tempfile.mkdtemp(prefix="experiment_mock_"))
        provider, audit = MockProvider(), JsonlAuditLog(out_dir / "audit.jsonl")
    else:
        from classify.providers import AnthropicProvider
        out_dir = HERE
        provider, audit = AnthropicProvider(), JsonlAuditLog(ROOT / "data" / "audit" / "experiment.jsonl")

    rows = run(records, provider, audit)
    (out_dir / f"results_{PROMPT_VERSION}{tag}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    (out_dir / results_md).write_text(summary_markdown(rows, provider, set_name))

    fresh = sum(not r["from_cache"] for r in rows)
    print(f"\n{len(rows)} packets, {fresh} new model calls, {len(rows) - fresh} reused from the audit log")
    for s in SYSTEMS:
        print(f"  {s:9}", tally(rows, s))
    print(f"Wrote {results_md} and results_{PROMPT_VERSION}{tag}.jsonl in {out_dir}")


if __name__ == "__main__":
    main(sys.argv[1:])
