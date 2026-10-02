#!/usr/bin/env python3
"""Apply the verify pass's verdicts to the analysis.

    python apply_verdicts.py "C:/RFQs/Acme V6" [--mode in-thread]

Reads  .work/analysis.json, .work/claims.json, .work/verdicts.json
Writes .work/verification.json and the updated .work/analysis.json

Effect of a refutation: **the section's confidence is forced to "low"**,
which turns the deck's chip red. The answer text is never rewritten - the
verifier judges claims, it does not author analysis.

Two deterministic guards on the verdicts themselves:

  * A `refuted` or `ambiguous` verdict with no verbatim quote is REJECTED
    and recorded. The verifier prompt's own bar is "a false refutation is
    worse than a missed one"; this enforces it rather than trusting it.
  * A claim nobody returned a verdict for is `unchecked`, not `confirmed`.

Nothing here is allowed to break the run: a missing or unreadable verdicts
file produces a verification record with status "error" and exit 0. A deck
with an unverified analysis beats no deck.
"""

import argparse
import json
import os
import sys

REFUTING = ("refuted", "ambiguous")


def apply_verdicts(analysis: dict, claims: list, verdicts: dict,
                   mode: str = "subagent") -> dict:
    """Merge verdicts into the claims and cap refuted sections at "low"."""
    if not claims:
        return {"status": "no_claims", "mode": mode, "claims": [],
                "refuted_sections": [], "rejected_verdicts": []}

    by_id = {v.get("id"): v for v in (verdicts or {}).get("verdicts", [])}
    results, refuted_sections, rejected = [], set(), []

    for claim in claims:
        verdict_record = by_id.get(claim["id"], {})
        verdict = verdict_record.get("verdict", "unchecked")
        evidence = str(verdict_record.get("evidence", "") or "").strip()

        if verdict in REFUTING and not evidence:
            rejected.append(
                f"claim {claim['id']} (section {claim['section']}): "
                f"{verdict} without a verbatim quote, so it was not applied")
            verdict = "unchecked"
            evidence = ""

        results.append({**claim, "verdict": verdict, "evidence": evidence})
        if verdict == "refuted":
            refuted_sections.add(claim["section"])

    for answer in analysis.get("answers", []):
        if answer.get("id") in refuted_sections:
            answer["confidence"] = "low"

    return {"status": "ok", "mode": mode, "claims": results,
            "refuted_sections": sorted(refuted_sections),
            "rejected_verdicts": rejected}


def _load(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Apply verify-pass verdicts.")
    ap.add_argument("folder", help="the folder holding the RFQ package")
    ap.add_argument("--mode", default="subagent",
                    choices=("subagent", "in-thread"),
                    help="how the verify pass was run (recorded in the report)")
    args = ap.parse_args(argv)

    work = os.path.join(os.path.abspath(args.folder), "output", ".work")
    analysis_path = os.path.join(work, "analysis.json")
    claims_path = os.path.join(work, "claims.json")
    if not (os.path.exists(analysis_path) and os.path.exists(claims_path)):
        # A resume lands here often. A bare FileNotFoundError traceback
        # tells a salesperson nothing and looks like a crash. A missing
        # verdicts.json is different - that is the sub-analysis having
        # produced nothing, and it is already recorded in the report below.
        print("A checkpoint is missing - I can't apply the double-check "
              "from here.", file=sys.stderr)
        return 2
    analysis = _load(analysis_path)
    claims = _load(claims_path).get("claims", [])

    try:
        verdicts = _load(os.path.join(work, "verdicts.json"))
        record = apply_verdicts(analysis, claims, verdicts, mode=args.mode)
    except Exception as exc:
        record = {"status": "error", "mode": args.mode,
                  "error": f"{type(exc).__name__}: {exc}",
                  "claims": claims, "refuted_sections": [],
                  "rejected_verdicts": []}

    with open(analysis_path, "w", encoding="utf-8") as fh:
        json.dump(analysis, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(work, "verification.json"), "w",
              encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False, indent=2)

    if record["status"] == "error":
        print("I couldn't run the double-check, so I've carried on without "
              "it. The report records that.")
    else:
        print(f"Double-checked {len(record['claims'])} statement(s); "
              f"{len(record['refuted_sections'])} section(s) marked "
              f"low-confidence.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
