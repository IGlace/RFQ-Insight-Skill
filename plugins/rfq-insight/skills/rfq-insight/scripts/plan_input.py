#!/usr/bin/env python3
"""Shape the analysis into what the slide-plan stage is allowed to see.

    python plan_input.py "C:/RFQs/Acme V6"

Reads  .work/analysis.json, .work/corpus.json
Writes .work/plan_input.json

Two jobs, both about keeping authority in the right place:

  * SECTION IDENTITY IS NOT THE MODEL'S. Each answer is enriched with its
    canonical title_en/title_de, matched on `id` alone. Stage 1 never
    supplies titles and stage 2 never invents them.
  * The debug-only fields `tldr` and `evidence_files` are stripped. The
    slide-plan prompt reads `id`, `answer` and `confidence`; sending the
    rest only gives it more to accidentally present.

The `confidence` carried here is the POST-verify value, so a refuted
section arrives at the deck already marked low.
"""

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from rfq.schema import TITLES                            # noqa: E402


def build_plan_input(corpus: dict, analysis: dict) -> dict:
    answers = []
    for a in analysis.get("answers", []):
        try:
            title = TITLES.get(int(a.get("id", 0)))
        except (TypeError, ValueError):
            title = None
        if title is None:
            print(f"Skipping an answer with an unknown section id: "
                  f"{a.get('id')!r}", file=sys.stderr)
            continue
        answers.append({
            "id": a["id"],
            "title_en": title[0],
            "title_de": title[1],
            "answer": a.get("answer", ""),
            "confidence": a.get("confidence", ""),
        })
    return {"projectName": corpus.get("projectName", ""), "answers": answers}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the slide-plan input.")
    ap.add_argument("folder", help="the folder holding the RFQ package")
    args = ap.parse_args(argv)

    work = os.path.join(os.path.abspath(args.folder), "output", ".work")
    corpus_path = os.path.join(work, "corpus.json")
    analysis_path = os.path.join(work, "analysis.json")
    if not (os.path.exists(corpus_path) and os.path.exists(analysis_path)):
        # A resume lands here often. A bare FileNotFoundError traceback
        # tells a salesperson nothing and looks like a crash.
        print("A checkpoint is missing - I can't prepare the deck plan "
              "from here.", file=sys.stderr)
        return 2
    with open(corpus_path, encoding="utf-8") as fh:
        corpus = json.load(fh)
    with open(analysis_path, encoding="utf-8") as fh:
        analysis = json.load(fh)

    payload = build_plan_input(corpus, analysis)
    with open(os.path.join(work, "plan_input.json"), "w",
              encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    print(f"Prepared {len(payload['answers'])} section(s) for the deck plan.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
