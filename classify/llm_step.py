"""The AI step for break causes, in one small file.

The rules baseline runs first. Only the breaks it calls unknown come here. The
model reads the facts and proposes a cause, and everything around it is plain
code: what it is allowed to say, what happens to a bad answer, and the record
kept of every call. The model never closes a break. Anything it labels is
at least level 2 (review), so a person confirms it.

Which AI sits behind this is a one-line swap. A provider is anything with a
name, a model, and a complete(prompt) method that returns text. MockProvider is
the stand-in until I pick one and have an API key.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from classify import action_policy
from classify.taxonomy import CAUSES

# Bump this whenever the prompt text changes, so old decisions can be traced
# back to the exact prompt that produced them.
PROMPT_VERSION = "v1"

CAUSE_HELP = {
    "missing_trade": "the custodian never recorded one of our trades (gap is -1x that trade's quantity)",
    "duplicate_trade": "the custodian recorded one trade twice (gap is +1x)",
    "wrong_quantity": "the custodian recorded one trade at 10x the size (gap is +9x)",
    "split_not_applied": "the custodian skipped a stock split (constant ratio from the ex-date)",
    "unknown": "the facts do not point to one cause",
}


@dataclass
class BreakCase:
    """Everything the model gets to see. If it is not here, the model does not know it."""
    security_id: str
    first_break_date: str
    custodian_quantity: float
    book_quantity_settled_basis: float
    gap_vs_settled: float
    baseline_method: str  # why the rules gave up: 'ambiguous' or 'no_signature'
    candidate_trades: list = field(default_factory=list)  # trades settling that day
    split_factor_on_day: float = 1.0


@dataclass
class Result:
    final_cause: str
    confidence: float
    reason: str
    min_action_level: int
    validation_error: str | None
    from_cache: bool


class MockProvider:
    """A fake AI that returns whatever reply I give it. For tests and dry runs."""
    name = "mock"
    model = "mock-1"

    def __init__(self, reply: str | None = None):
        self.reply = reply if reply is not None else '{"cause": "unknown", "confidence": 0.0, "reason": "mock provider"}'
        self.calls = 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        return self.reply


class JsonlAuditLog:
    """One line per decision. The same fields go into audit.llm_decisions
    (classify/audit_llm_decisions.sql) once this runs inside the pipeline."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def find(self, input_hash: str):
        if not self.path.exists():
            return None
        with self.path.open() as f:
            for line in f:
                rec = json.loads(line)
                # Only successful decisions are reused. A failed call should be retried.
                if rec["input_hash"] == input_hash and rec["validation_error"] is None:
                    return rec
        return None

    def write(self, record: dict) -> None:
        with self.path.open("a") as f:
            f.write(json.dumps(record) + "\n")


def build_prompt(case: BreakCase) -> str:
    causes = "\n".join(f"- {c}: {CAUSE_HELP[c]}" for c in CAUSES)
    return (
        "You help an operations team work out why their position records disagree "
        "with the custodian's.\n\n"
        f"Allowed causes:\n{causes}\n\n"
        f"Facts about this break:\n{json.dumps(asdict(case), indent=2)}\n\n"
        "Rules:\n"
        "- Use only the facts above. Do not invent trades or numbers.\n"
        "- If the facts do not tell you which cause it is, answer unknown.\n"
        '- Reply with JSON only: {"cause": "<one allowed cause>", '
        '"confidence": <number from 0 to 1>, "reason": "<one sentence>"}\n'
    )


def parse_reply(raw: str):
    """Returns (cause, confidence, reason, error). Anything off becomes unknown."""
    if not raw or not raw.strip():
        return "unknown", 0.0, "", "empty reply"
    try:
        start, end = raw.index("{"), raw.rindex("}") + 1  # tolerates code fences around the JSON
        data = json.loads(raw[start:end])
    except (ValueError, AttributeError):
        return "unknown", 0.0, "", "reply was not valid JSON"
    cause = data.get("cause")
    confidence = data.get("confidence")
    reason = str(data.get("reason", ""))
    if cause not in CAUSES:
        return "unknown", 0.0, reason, f"cause not in taxonomy: {cause!r}"
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        return "unknown", 0.0, reason, f"confidence not a number from 0 to 1: {confidence!r}"
    return cause, float(confidence), reason, None


def classify_break(case: BreakCase, provider, audit: JsonlAuditLog) -> Result:
    prompt = build_prompt(case)
    input_hash = hashlib.sha256(
        json.dumps([asdict(case), PROMPT_VERSION, provider.model], sort_keys=True).encode()
    ).hexdigest()

    # Same case, same prompt version, same model: reuse the earlier decision, so
    # a rerun never quietly relabels a break (same idea as the idempotent loader).
    prior = audit.find(input_hash)
    if prior:
        return Result(prior["final_cause"], prior["confidence"], prior["reason"],
                      prior["min_action_level"], prior["validation_error"], from_cache=True)

    try:
        raw = provider.complete(prompt)
        cause, confidence, reason, error = parse_reply(raw)
    except Exception as exc:  # a timeout or an API error is not a reason to stop the pipeline
        raw, cause, confidence, reason, error = None, "unknown", 0.0, "", f"provider error: {exc}"

    result = Result(cause, confidence, reason, action_policy.LLM_ASSIGNED_MIN_LEVEL, error, from_cache=False)
    audit.write({
        "decision_id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "security_id": case.security_id,
        "first_break_date": case.first_break_date,
        "input_hash": input_hash,
        "provider": provider.name,
        "model": provider.model,
        "prompt_version": PROMPT_VERSION,
        "prompt_text": prompt,
        "raw_response": raw,
        "provider_meta": getattr(provider, "last_meta", None),  # stop reason and token counts
        "final_cause": result.final_cause,
        "confidence": result.confidence,
        "reason": result.reason,
        "min_action_level": result.min_action_level,
        "validation_error": result.validation_error,
    })
    return result
