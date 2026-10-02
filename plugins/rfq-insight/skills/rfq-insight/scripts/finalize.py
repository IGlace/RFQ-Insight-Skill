#!/usr/bin/env python3
"""The deterministic tail: slide plan in, deck and run report out.

    python finalize.py "C:/RFQs/Acme V6"

Reads  .work/slide_plan.json, .work/analysis.json, .work/corpus.json,
       .work/verification.json (optional)
Writes <folder>/output/<name>_RFQ_Analysis.pptx
       <folder>/output/<name>_RFQ_Analysis.json

The order below is load-bearing and is carried over unchanged from the
container app's pipeline:

    tighten      drop the None fields so the strict discriminated union fits
    stamp        date (today) and oppId - by this layer, NEVER by the model
    validate     SlidePlan, the exact contract the renderer expects
    confidence   re-attached from the analysis, matched on the verbatim title
    sanitize     the deterministic guards; every action is recorded
    validate     again - a guard must not be able to produce an invalid plan
    tighten      again - the second validate re-introduced the None fields,
                 and the renderer cannot take them (see the note below)
    render       python-pptx, offline, deterministic
    report       run + analysis + slidePlan + verification

`run.usage` keeps its key but tells the truth: in-session there is no token
accounting to report.
"""

import argparse
import copy
import datetime
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from rfq.renderer import render_to_bytes                 # noqa: E402
from rfq.sanitize import sanitize_plan                    # noqa: E402
from rfq.schema import SlidePlan, TITLES, tighten_plan    # noqa: E402

ANALYSIS_PROMPT = "RFQ_QA_Extraction_Prompt_v12.md"
SLIDE_PLAN_PROMPT = "RFQ_Slide_Plan_Prompt_v11.md"
USAGE = {"mode": "in-session", "note": "not measured"}
SUFFIX = "_RFQ_Analysis"


def safe_name(project_name: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "_", (project_name or "").strip())
    return clean.strip("._-") or "RFQ"


def deliverable_paths(folder: str, project_name: str):
    out_dir = os.path.join(os.path.abspath(folder), "output")
    base = os.path.join(out_dir, safe_name(project_name) + SUFFIX)
    candidate = base
    version = 2
    while any(os.path.lexists(candidate + ext) for ext in (".pptx", ".json")):
        candidate = f"{base}_{version}"
        version += 1
    return candidate + ".pptx", candidate + ".json"


def finalize(corpus: dict, analysis: dict, draft_plan: dict,
             verification=None, execution=None):
    """(plan, deck_bytes, report). Raises ValueError if the plan is unusable."""
    from pydantic import ValidationError

    # A deep copy: `tighten_plan` reassigns each question's "slides" list,
    # and a shallow `dict(draft_plan)` would leave those nested question
    # dicts shared with the caller's object, so the caller's draft would be
    # mutated as a side effect of calling finalize().
    plan = tighten_plan(copy.deepcopy(draft_plan))
    plan["date"] = datetime.date.today().isoformat()
    plan["oppId"] = ""
    try:
        plan = SlidePlan.model_validate(plan).model_dump()
    except ValidationError as exc:
        raise ValueError(f"the slide plan does not validate: {exc}") from exc

    # Each question's confidence comes from the analysis, matched on the
    # canonical title the plan echoes verbatim. Rendered as a chip.
    confidence_by_title = {}
    for a in analysis.get("answers", []):
        title = TITLES.get(a.get("id"))
        if title:
            confidence_by_title[title[0]] = a.get("confidence", "")
    for question in plan["questions"]:
        title_en = question["titleEn"]
        if title_en not in confidence_by_title:
            print(f"No analysis confidence found for question titled "
                  f"{title_en!r}; leaving it blank.", file=sys.stderr)
        question["confidence"] = confidence_by_title.get(title_en, "")

    files = corpus.get("filesContents", [])
    corpus_text = "\n".join(f.get("extracted_text", "") or "" for f in files)
    # Stage-1 answers are a second trace source for phase names: a phase
    # grounded in the answers is legitimate even when the extraction garbled
    # the wording it came from.
    analysis_text = "\n".join(str(a.get("answer", ""))
                              for a in analysis.get("answers", []))
    plan, actions = sanitize_plan(plan, corpus_text, analysis_text)
    try:
        plan = SlidePlan.model_validate(plan).model_dump()
    except ValidationError as exc:
        raise ValueError(f"the guards produced an invalid plan: {exc}") from exc

    # `model_dump()` makes every unset optional slide field (hub, callout,
    # bars, customerAbbr, ...) explicit as None. The renderer leans on
    # `d.get(key, default)`, which only falls back for an ABSENT key, so an
    # explicit None (e.g. a collab slide's `hub`) reaches python-pptx as a
    # literal None and crashes. tighten_plan's "drop the None fields" pass
    # is exactly the fix; reuse it here, right before the plan is handed to
    # the renderer and frozen into the report.
    plan = tighten_plan(plan)

    deck = render_to_bytes(plan)

    extraction = {k: v for k, v in corpus.get("extraction", {}).items()
                  if k != "preprocess"}
    report = {
        "run": {
            "generatedAt": datetime.datetime.now().isoformat(
                timespec="seconds"),
            "projectName": corpus.get("projectName", ""),
            "oppId": "",
            "corpusFiles": [f.get("filename", "") for f in files],
            "prompts": {"analysis": ANALYSIS_PROMPT,
                        "slidePlan": SLIDE_PLAN_PROMPT},
            "usage": dict(USAGE),
            "preprocess": corpus.get("extraction", {}).get("preprocess", {}),
            "sanitizer": actions,
            "extraction": extraction,
        },
        "analysis": analysis,
        "slidePlan": plan,
    }
    if verification is not None:
        report["verification"] = verification
    if execution is not None:
        report["run"]["execution"] = copy.deepcopy(execution)
    return plan, deck, report


def _load(path: str, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the deck and run report.")
    ap.add_argument("folder", help="the folder holding the RFQ package")
    args = ap.parse_args(argv)

    folder = os.path.abspath(args.folder)
    work = os.path.join(folder, "output", ".work")
    corpus = _load(os.path.join(work, "corpus.json"))
    analysis = _load(os.path.join(work, "analysis.json"))
    draft = _load(os.path.join(work, "slide_plan.json"))
    verification = _load(os.path.join(work, "verification.json"))
    try:
        execution = _load(os.path.join(work, "execution.json"))
    except (ValueError, OSError) as exc:
        # Optional routing metadata must not prevent delivery of a valid deck.
        execution = {"status": "error", "note": f"Execution history unreadable: {exc}"}
    if corpus is None or analysis is None or draft is None:
        print("A checkpoint is missing - I can't build the deck from here.",
              file=sys.stderr)
        return 2

    try:
        plan, deck, report = finalize(corpus, analysis, draft, verification, execution)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    pptx_path, report_path = deliverable_paths(
        folder, corpus.get("projectName", ""))
    os.makedirs(os.path.dirname(pptx_path), exist_ok=True)
    # Exclusive creation also protects a file created after path selection.
    with open(pptx_path, "xb") as fh:
        fh.write(deck)
    with open(report_path, "x", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(work, "deliverables.json"), "w", encoding="utf-8") as fh:
        json.dump({"pptx": pptx_path, "report": report_path}, fh, indent=2)

    slides = sum(len(q.get("slides", [])) for q in plan.get("questions", []))
    print(f"Wrote the deck ({len(plan['questions'])} sections, {slides} "
          f"slides) to {pptx_path}")
    print(f"Wrote the report to {report_path}")
    for action in report["run"]["sanitizer"]:
        print(f"  adjusted: {action}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
