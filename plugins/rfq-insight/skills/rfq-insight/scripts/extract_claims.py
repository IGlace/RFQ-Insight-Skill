#!/usr/bin/env python3
"""Harvest the checkable assertions out of the analysis.

    python extract_claims.py "C:/RFQs/Acme V6"

Reads  .work/analysis.json
Writes .work/claims.json  ->  {"claims": [...]}

Two kinds are worth an adversarial second look:

  * ABSENCE  - "not found", "info not available", "not stated". A false
    "not found" is the most damaging error class this system can make: the
    deck tells a customer that AVL did not see something that was in their
    own package.
  * DERIVED  - a line tagged "(inferred)" that contains a digit, i.e. a
    date or quantity the analysis worked out rather than read.

Capped at 3 per section and 20 overall, so the verify pass stays cheap.
Each claim carries 1 200 characters of the surrounding answer as `context`,
so the verifier can see what the claim itself already acknowledges - that
is what stops it "refuting" a caveat the answer already made.
"""

import argparse
import json
import os
import re
import sys

ABSENCE_MARKERS = ("not found", "info not available", "not stated")


def extract_claims(analysis: dict, max_claims: int = 20) -> list:
    """Pull the checkable claims out of the stage-1 answers."""
    claims = []
    for a in analysis.get("answers", []):
        sid = a.get("id")
        per_section = 0
        for line in str(a.get("answer", "")).splitlines():
            low = line.lower()
            is_absence = any(m in low for m in ABSENCE_MARKERS)
            is_derived = "(inferred)" in low and any(c.isdigit() for c in line)
            if not (is_absence or is_derived):
                continue
            per_section += 1
            if per_section > 3:
                break
            clean = re.sub(r"[*|#]+", "", line).strip().lstrip("- ").strip()
            claims.append({
                "id": len(claims) + 1,
                "section": sid,
                "kind": "absence" if is_absence else "derived",
                "claim": clean[:300],
                "context": str(a.get("answer", ""))[:1200],
            })
            if len(claims) >= max_claims:
                return claims
    return claims


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Harvest claims to verify.")
    ap.add_argument("folder", help="the folder holding the RFQ package")
    args = ap.parse_args(argv)

    work = os.path.join(os.path.abspath(args.folder), "output", ".work")
    analysis_path = os.path.join(work, "analysis.json")
    if not os.path.exists(analysis_path):
        # A resume lands here often. A bare FileNotFoundError traceback
        # tells a salesperson nothing and looks like a crash.
        print("A checkpoint is missing - I haven't got an analysis to "
              "check yet.", file=sys.stderr)
        return 2
    with open(analysis_path, encoding="utf-8") as fh:
        analysis = json.load(fh)

    claims = extract_claims(analysis)
    with open(os.path.join(work, "claims.json"), "w", encoding="utf-8") as fh:
        json.dump({"claims": claims}, fh, ensure_ascii=False, indent=2)

    print(f"{len(claims)} statement(s) to double-check.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
