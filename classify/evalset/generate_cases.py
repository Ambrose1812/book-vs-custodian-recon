"""Builds the test set for the AI-versus-rules experiment.

Run from the repo root: python -m classify.evalset.generate_cases

42 base cases in five groups, with a known right answer for each. The ambiguous
ones are written three ways (numbers only, plus a structured status per trade,
plus a free-text ops note), so the experiment can show what each kind of extra
evidence is worth. That gives 62 test packets in cases.jsonl.

Every case is checked while it is built: a brute-force search lists every way the
numbers could be explained, and the case only survives if that list looks the way
the group says it should (one explanation for a clean case, two or more for an
ambiguous one, none for noise). The seed is fixed, so the output never changes
unless the code does.

These cases are invented by me, not taken from real data. The origin field says
which ones copy a pattern from the real planted breaks.
"""
from __future__ import annotations

import itertools
import json
import random
from pathlib import Path

OUT_DIR = Path(__file__).parent
SEED = 7
TOL = 0.001

# How many times the custodian recorded a trade, compared with once when it is correct.
DEVIATION_M = {"missing": 0, "duplicate": 2, "wrong": 10}
CAUSE_OF = {"missing": "missing_trade", "duplicate": "duplicate_trade", "wrong": "wrong_quantity"}
STATUS_OF = {
    None: "matched_and_settled",
    "missing": "never_received_by_custodian",
    "duplicate": "received_twice",
    "wrong": "received_with_different_quantity",
}
QTY = [20, 25, 30, 40, 50, 60, 75, 80, 100, 120, 150, 200, 250, 300]
DAYS = ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05",
        "2026-06-08", "2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12"]


def num(x):
    x = round(x, 6)
    return int(x) if x == int(x) else x


def baseline(packet):
    """My Python copy of the rules in fct_break_cause_baseline.sql, so the same
    rules can be run on invented cases. Checked against the dbt unit test cases
    in test_cases.py."""
    gap = packet["gap_vs_settled"]
    matches = []
    for t in packet["candidate_trades"]:
        for cause, mult in (("missing_trade", -1.0), ("duplicate_trade", 1.0), ("wrong_quantity", 9.0)):
            if abs(gap - mult * t["effect_on_day"]) <= TOL:
                matches.append((cause, t["transaction_id"]))
    if len(matches) == 1:
        return matches[0][0], "trade_ratio"
    if len(matches) > 1:
        return "unknown", "ambiguous"
    s = packet["split_factor_on_day"]
    if s != 1 and abs(packet["custodian_quantity"] * s - packet["book_quantity_settled_basis"]) <= TOL * max(s, 1):
        return "split_not_applied", "split_ratio"
    return "unknown", "no_signature"


def explanations(base):
    """Every way the numbers can be explained: an optional skipped split plus up
    to two trades the custodian got wrong."""
    found = []
    s = base["split"]
    for skip in ([False, True] if s != 1 else [False]):
        for n_dev in (0, 1, 2):
            for chosen in itertools.combinations(base["trades"], n_dev):
                for kinds in itertools.product(DEVIATION_M, repeat=n_dev):
                    pred = base["book"] + sum((DEVIATION_M[k] - 1) * t["effect"] for t, k in zip(chosen, kinds))
                    if skip:
                        pred /= s
                    if abs(pred - base["custodian"]) <= TOL * max(s, 1):
                        found.append({"skip": skip, "deviations": {t["id"]: k for t, k in zip(chosen, kinds)}})
    return found


def build(case_id, group, origin, why, trades, deviations, s=1.0, skip=False,
          prior_now=0, gap_override=None, variants=False, cause_identifiable=True):
    for t in trades:
        t["effect"] = (t["qty"] if t["side"] == "BUY" else -t["qty"]) * s
    book = prior_now + sum(t["effect"] for t in trades)
    if gap_override is not None:
        custodian = book + gap_override
    else:
        pred = book + sum((DEVIATION_M[deviations[t["id"]]] - 1) * t["effect"] for t in trades if t["id"] in deviations)
        custodian = pred / s if skip else pred
    causes = (["split_not_applied"] if skip else []) + [CAUSE_OF[deviations[i]] for i in sorted(deviations)]
    return {
        "id": case_id, "group": group, "origin": origin, "why": why, "trades": trades,
        "deviations": deviations, "split": s, "skip": skip, "book": book, "custodian": custodian,
        "causes": causes or ["unknown"], "trade_ids": sorted(deviations),
        "variants": variants, "cause_identifiable": cause_identifiable,
    }


def note_for(base, rng):
    parts = []
    for t in base["trades"]:
        kind = base["deviations"].get(t["id"])
        who = f"transaction {t['id']} ({t['side']} {num(t['qty'])})"
        if kind == "missing":
            parts.append(rng.choice([
                f"Called custodian ops: they have no record of our instruction for {who}.",
                f"Custodian ops replied by email that {who} never reached their system.",
                f"Custodian confirmed by phone they cannot find {who} anywhere in their queue.",
            ]))
        elif kind == "duplicate":
            parts.append(rng.choice([
                f"Custodian ops said {who} was loaded twice on their side after a feed retry, and both copies settled.",
                f"Custodian email: {who} shows two identical entries on their books after a resend.",
                f"Ops note: custodian admits {who} was processed twice, with the second copy settling too.",
            ]))
        elif kind == "wrong":
            parts.append(rng.choice([
                f"Custodian confirmed {who} sits on their books at {num(t['qty'] * 10)} shares. Looks like a keying error on their side.",
                f"Custodian ops: {who} is recorded at ten times the size we sent, a decimal slip in their entry.",
                f"Ops call: custodian's record of {who} shows {num(t['qty'] * 10)} shares, not {num(t['qty'])}.",
            ]))
    others = [t for t in base["trades"] if t["id"] not in base["deviations"]]
    if parts and others:
        parts.append("The other trade from that day matches on both sides." if len(others) == 1
                     else "The other trades from that day match on both sides.")
    if base["skip"]:
        parts.append("Custodian says the stock split has not been applied to this account yet.")
    return " ".join(parts)


def packets(base, rng):
    day = rng.choice(DAYS)
    variants = ["numbers_only", "with_structured", "with_note"] if base["variants"] else ["numbers_only"]
    note = note_for(base, rng) if base["variants"] else None
    out = []
    for v in variants:
        trades = []
        for t in base["trades"]:
            d = {"transaction_id": t["id"], "side": t["side"], "quantity": num(t["qty"]), "effect_on_day": num(t["effect"])}
            if v == "with_structured":
                d["custodian_instruction_status"] = STATUS_OF[base["deviations"].get(t["id"])]
            trades.append(d)
        p = {
            "security_id": "SYN-" + base["id"], "first_break_date": day,
            "custodian_quantity": num(base["custodian"]), "book_quantity_settled_basis": num(base["book"]),
            "gap_vs_settled": num(base["custodian"] - base["book"]), "baseline_method": None,
            "candidate_trades": trades, "split_factor_on_day": num(base["split"]),
            "ops_note": note if v == "with_note" else None,
        }
        label, method = baseline(p)
        p["baseline_method"] = method
        evidence_helps = base["variants"] and v != "numbers_only"
        out.append({
            "case_id": f"{base['id']}-{v}", "base_id": base["id"], "group": base["group"],
            "variant": v, "origin": base["origin"], "packet": p,
            "truth": {
                "causes": base["causes"], "trade_ids": base["trade_ids"],
                "cause_identifiable": base["cause_identifiable"] or evidence_helps,
                "trade_identifiable": (base["group"] in ("clean", "combined")) or evidence_helps,
            },
            "baseline": {"label": label, "method": method},
        })
    return out


# ---- the five groups -------------------------------------------------------------

def make_all(rng):
    bases = []

    def attempt(maker, check):
        for _ in range(200):
            base = maker()
            if check(base, explanations(base)):
                return base
        raise RuntimeError("could not build a valid case")

    def one(base, found):
        return len(found) == 1 and found[0] == {"skip": base["skip"], "deviations": base["deviations"]}

    def several(base, found):
        return len(found) >= 2 and {"skip": base["skip"], "deviations": base["deviations"]} in found

    def none(base, found):
        return len(found) == 0

    prior = lambda: rng.choice([300, 500, 800, 1000, 1500, 2000])

    # Clean: one clear explanation. These copy the four planted break types.
    for i, (kind, side) in enumerate([("missing", "BUY"), ("missing", "SELL"), ("missing", "BUY"),
                                      ("duplicate", "BUY"), ("duplicate", "SELL"),
                                      ("wrong", "BUY"), ("wrong", "SELL")], 1):
        def mk(kind=kind, side=side, i=i):
            trades = [{"id": 100 + i, "side": side, "qty": rng.choice(QTY)}]
            if rng.random() < 0.5:
                trades.append({"id": 200 + i, "side": rng.choice(["BUY", "SELL"]), "qty": rng.choice(QTY)})
            return build(f"CLN-{i:02d}", "clean", "mirrors a planted break type",
                         f"One clear explanation: {kind} {side}. Both methods should get it.",
                         trades, {100 + i: kind}, prior_now=prior())
        bases.append(attempt(mk, one))

    def mk_split():
        s = rng.choice([2, 3, 4])
        return build("CLN-08", "clean", "mirrors a planted break type",
                     "A skipped stock split with no trades involved. Both methods should get it.",
                     [], {}, s=s, skip=True, prior_now=rng.choice([100, 200, 300, 500]) * s)
    bases.append(attempt(mk_split, one))

    # Ambiguous: two trades both fit when only the numbers are known.
    a1 = [("missing", "SELL"), ("missing", "SELL"), ("duplicate", "BUY"), ("duplicate", "BUY")]
    for i, (kind, _) in enumerate(a1, 1):
        def mk(kind=kind, i=i):
            q = rng.choice(QTY)
            buy, sell = {"id": 300 + i, "side": "BUY", "qty": q}, {"id": 400 + i, "side": "SELL", "qty": q}
            target = sell["id"] if kind == "missing" else buy["id"]
            return build(f"AMB-{i:02d}", "ambiguous", "invented",
                         "A BUY and a SELL of the same size settle together. A missing SELL and a duplicated BUY "
                         "give the same gap, so the numbers alone cannot say which.",
                         [buy, sell], {target: kind}, prior_now=prior(), variants=True, cause_identifiable=False)
        bases.append(attempt(mk, several))
    for i in range(5, 8):
        def mk(i=i):
            q = rng.choice(QTY)
            trades = [{"id": 500 + i, "side": "BUY", "qty": q}, {"id": 600 + i, "side": "BUY", "qty": q}]
            return build(f"AMB-{i:02d}", "ambiguous", "invented",
                         "Two identical BUYs settle together and one is missing. The cause is clear, "
                         "but the numbers cannot say which trade.",
                         trades, {rng.choice([500 + i, 600 + i]): "missing"}, prior_now=prior(),
                         variants=True, cause_identifiable=True)
        bases.append(attempt(mk, several))
    for i, kind in zip(range(8, 11), ["wrong", "missing", "wrong"]):
        def mk(kind=kind, i=i):
            b = rng.choice([20, 25, 30, 40, 50])
            buy, sell = {"id": 700 + i, "side": "BUY", "qty": b}, {"id": 800 + i, "side": "SELL", "qty": 9 * b}
            target = buy["id"] if kind == "wrong" else sell["id"]
            return build(f"AMB-{i:02d}", "ambiguous", "invented",
                         "A small BUY recorded at ten times its size gives the same gap as a missing SELL nine times as big.",
                         [buy, sell], {target: kind}, prior_now=prior(), variants=True, cause_identifiable=False)
        bases.append(attempt(mk, several))

    # Combined: more than one cause on one break.
    for i, kind in enumerate(["missing", "missing", "missing", "missing", "duplicate", "duplicate"], 1):
        def mk(kind=kind, i=i):
            s = rng.choice([2, 3, 4])
            trades = [{"id": 900 + i, "side": "BUY", "qty": rng.choice(QTY)}]
            return build(f"CMB-{i:02d}", "combined", "invented",
                         f"A skipped split and a {kind} trade on the same security at the same time.",
                         trades, {900 + i: kind}, s=s, skip=True, prior_now=rng.choice([100, 200, 300, 500]) * s)
        bases.append(attempt(mk, one))
    for i, (k1, k2) in enumerate([("missing", "duplicate"), ("missing", "duplicate"),
                                  ("missing", "wrong"), ("duplicate", "wrong")], 7):
        def mk(k1=k1, k2=k2, i=i):
            qa, qb = rng.sample(QTY, 2)
            trades = [{"id": 1000 + i, "side": "BUY", "qty": qa}, {"id": 1100 + i, "side": "BUY", "qty": qb}]
            return build(f"CMB-{i:02d}", "combined", "invented",
                         f"Two different trades went wrong at once: one {k1}, one {k2}. No single cause fits.",
                         trades, {1000 + i: k1, 1100 + i: k2}, prior_now=prior())
        bases.append(attempt(mk, one))

    # Noise: the gap fits nothing, so unknown is the right answer.
    for i, gap in enumerate([0.37, -1.62, 2.5, None, None, None], 1):
        def mk(gap=gap, i=i):
            q = rng.choice(QTY)
            g = gap if gap is not None else round(q * rng.choice([0.37, 1.9, 3.3, 5.5]), 2)
            return build(f"NOS-{i:02d}", "noise", "invented",
                         "A gap that fits no trade and no split. The right answer is unknown.",
                         [{"id": 1200 + i, "side": "BUY", "qty": q}], {}, prior_now=prior(),
                         gap_override=g, cause_identifiable=False)
        bases.append(attempt(mk, none))

    # Near misses: a gap that is almost a trade multiple but not quite.
    styles = [("missing", 2), ("missing", -3), ("duplicate", 1), ("duplicate", -5),
              ("wrong", 2), ("wrong", -4), ("missing", 5), ("duplicate", -2)]
    for i, (style, shift) in enumerate(styles, 1):
        def mk(style=style, shift=shift, i=i):
            q = rng.choice([50, 75, 100, 120, 150, 200, 250, 300])
            mult = {"missing": -1, "duplicate": 1, "wrong": 9}[style]
            return build(f"NMS-{i:02d}", "near_miss", "invented",
                         f"The gap is within {abs(shift)} shares of a {style} trade but not exact. Close enough "
                         "is wrong here: the right answer is unknown.",
                         [{"id": 1300 + i, "side": "BUY", "qty": q}], {}, prior_now=prior(),
                         gap_override=mult * q + shift, cause_identifiable=False)
        bases.append(attempt(mk, none))
    return bases


def generate():
    rng = random.Random(SEED)
    bases = make_all(rng)
    records = [r for b in bases for r in packets(b, rng)]
    return bases, records


def review_markdown(bases, records):
    by_base = {}
    for r in records:
        by_base.setdefault(r["base_id"], []).append(r)
    lines = ["# Test cases for review", "",
             "Generated by `python -m classify.evalset.generate_cases`. Do not edit by hand.",
             "Read each row and ask: would this really happen? Flag any that feel unrealistic.", "",
             "| Case | Group | Origin | Right answer | Packets | Why it is here |", "|---|---|---|---|---|---|"]
    for b in bases:
        ans = " + ".join(b["causes"]) + (f" (trade {', '.join(map(str, b['trade_ids']))})" if b["trade_ids"] else "")
        lines.append(f"| {b['id']} | {b['group']} | {b['origin']} | {ans} | {len(by_base[b['id']])} | {b['why']} |")
    lines += ["", "## Example free-text notes (ambiguous cases)", ""]
    for r in records:
        if r["variant"] == "with_note":
            lines.append(f"- **{r['base_id']}**: {r['packet']['ops_note']}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    bases, records = generate()
    (OUT_DIR / "cases.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n")
    (OUT_DIR / "CASES_FOR_REVIEW.md").write_text(review_markdown(bases, records))
    counts = {}
    for r in records:
        counts[r["group"]] = counts.get(r["group"], 0) + 1
    print(f"{len(bases)} base cases, {len(records)} packets: {counts}")
