#!/usr/bin/env python3
"""Gate the output of each stage before the next one builds on it.

    python validate.py --corpus   .work/corpus.json
    python validate.py --analysis .work/analysis.json
    python validate.py --plan     .work/slide_plan.json

Exit 0 when valid, 2 when not (problems printed one per line), 1 when the
file is missing or is not JSON.

A stage that fails is REGENERATED, at most three times. That is why the
messages here name the exact section, field or layout at fault rather than
saying "invalid": they are the only thing the next attempt has to go on.

The corpus size message is carried over verbatim from the container app's
fail-fast guard - it is the one message in this file a user reads.
"""

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from pydantic import ValidationError                            # noqa: E402

from rfq.schema import (AnalysisResult, LoosePlanDraft,         # noqa: E402
                        SlidePlan, TITLES, tighten_plan)

MAX_CORPUS_CHARS = 600_000
CONFIDENCES = {"high", "medium", "low"}
ANSWER_FIELDS = ("id", "answer", "tldr", "not_found", "confidence",
                 "evidence_files")
LAYOUTS = {"bullets", "table", "twoColumn", "panel", "prosCons", "timeline",
           "gantt", "kpi", "prose", "phases", "collab", "ownership"}


def _has_duplicates(values: list) -> bool:
    """True if any value repeats. Avoids `set(values)`, which raises on an
    unhashable id/number (e.g. a malformed `"id": [1, 2]`) - a validator
    must report that shape fault elsewhere, not crash checking for
    duplicates."""
    seen = []
    for v in values:
        if v in seen:
            return True
        seen.append(v)
    return False


def _in_ascending_order(values: list) -> bool:
    """True if `values` is sorted ascending, tolerating `None` and mixed,
    unorderable types (a malformed id/number is reported elsewhere - this
    must never raise, or it costs the retry every other message in the
    pass). `None` sorts last; genuinely unorderable pairs are treated as
    already out of order rather than crashing."""
    order_key = lambda v: (v is None, v)                    # noqa: E731
    try:
        return values == sorted(values, key=order_key)
    except TypeError:
        return False


# ----------------------------------------------------------------- corpus
def check_corpus(corpus: dict) -> list:
    problems = []
    # Guarded like check_analysis and check_plan. corpus.json is written by
    # our own extract_corpus.py, so it is well formed in a normal run - but
    # --corpus accepts any path, and a hand-edited or truncated checkpoint
    # must be REPORTED, never raise. A validator that crashes tells the
    # reader nothing.
    if not isinstance(corpus, dict):
        return ["The corpus file does not contain a JSON object."]
    files = corpus.get("filesContents") or corpus.get("files") or []
    if not isinstance(files, list):
        return ["'filesContents' must be a list."]
    if not files:
        return ["The corpus has no files in it."]
    malformed = [n for n, f in enumerate(files, start=1)
                 if not isinstance(f, dict)]
    if malformed:
        problems.append("These file entries are not objects: "
                        + ", ".join(f"#{n}" for n in malformed))
    files = [f for f in files if isinstance(f, dict)]

    for n, entry in enumerate(files, start=1):
        if not entry.get("filename"):
            problems.append(f"File {n} has no filename.")
        if "extracted_text" not in entry:
            problems.append(
                f"{entry.get('filename', f'file {n}')} has no extracted_text.")

    total = sum(len(f.get("extracted_text", "") or "") for f in files)
    if total > MAX_CORPUS_CHARS:
        largest = sorted(((len(f.get("extracted_text", "") or ""),
                           f.get("filename", "?")) for f in files),
                         reverse=True)[:5]
        detail = ", ".join(f"{name} ({count:,} chars)"
                           for count, name in largest)
        problems.append(
            f"Corpus too large to analyze: {total:,} characters of "
            f"extracted text across {len(files)} file(s); the limit is "
            f"{MAX_CORPUS_CHARS:,} chars (~"
            f"{MAX_CORPUS_CHARS // 4:,} tokens — the model context "
            f"must also hold the prompts, knowledge pack and the answer). "
            f"Largest files: {detail}. Remove non-essential files (signed "
            f"scans, duplicated annexes, price lists) or split the RFQ "
            f"package into separate runs.")
    return problems


# --------------------------------------------------------------- analysis
def check_analysis(analysis: dict) -> list:
    problems = []
    try:
        AnalysisResult.model_validate(analysis)
    except ValidationError as exc:
        # Recorded, NOT returned: every check below reads raw dicts, so it
        # can still run. A regeneration gets three attempts, and each one
        # must learn everything that is wrong - not one fault per round.
        problems.append(
            f"The analysis does not match the required shape: {exc}")

    answers = analysis.get("answers", []) if isinstance(analysis, dict) else []
    if not isinstance(answers, list):
        return problems + ["'answers' must be a list."]
    malformed = [n for n, a in enumerate(answers, start=1)
                 if not isinstance(a, dict)]
    if malformed:
        problems.append(
            "These answer entries are not objects: "
            + ", ".join(f"#{n}" for n in malformed))
    # Continue with what IS checkable. Dropping the bad entries here means
    # every remaining rule still reports, instead of one bad element
    # costing the retry every other message in this pass.
    answers = [a for a in answers if isinstance(a, dict)]
    ids = [a.get("id") for a in answers]

    missing = [i for i in range(1, 12) if i not in ids]
    if missing:
        problems.append("Missing section(s): "
                        + ", ".join(str(i) for i in missing))
    unknown = [i for i in ids if i not in range(1, 12)]
    if unknown:
        problems.append("Unknown section id(s): "
                        + ", ".join(str(i) for i in unknown))
    if _has_duplicates(ids):
        problems.append("A section id appears more than once.")
    if not _in_ascending_order(ids):
        problems.append("Sections must be in ascending id order.")

    for answer in answers:
        label = f"Section {answer.get('id')}"
        for field in ANSWER_FIELDS:
            if field not in answer:
                problems.append(f"{label} is missing the field '{field}'.")
        if not str(answer.get("answer", "")).strip():
            problems.append(f"{label} has an empty answer.")
        confidence = answer.get("confidence")
        if not isinstance(confidence, str) or confidence not in CONFIDENCES:
            problems.append(
                f"{label} has confidence {confidence!r}; it must be one of "
                f"high, medium, low.")
    return problems


# -------------------------------------------------------------- slide plan
def check_plan(plan: dict) -> list:
    problems = []
    try:
        draft = LoosePlanDraft.model_validate(plan).model_dump()
    except ValidationError as exc:
        # Same reasoning as check_analysis: report the shape failure, then
        # keep checking against the raw payload so one regeneration attempt
        # learns about the titles and layouts too, not just the shape.
        problems.append(
            f"The slide plan does not match the required shape: {exc}")
        draft = plan if isinstance(plan, dict) else {}
        if not isinstance(draft.get("questions"), list):
            return problems + ["'questions' must be a list."]

    questions = draft.get("questions") or []
    malformed = [n for n, q in enumerate(questions, start=1)
                 if not isinstance(q, dict)]
    if malformed:
        problems.append(
            "These question entries are not objects: "
            + ", ".join(f"#{n}" for n in malformed))
    questions = [q for q in questions if isinstance(q, dict)]

    numbers = [q.get("number") for q in questions]
    missing = [i for i in range(1, 12) if i not in numbers]
    if missing:
        problems.append("Missing question(s): "
                        + ", ".join(str(i) for i in missing))
    if not _in_ascending_order(numbers):
        problems.append("Questions must be in ascending number order.")

    for question in questions:
        number = question.get("number")
        try:
            expected = TITLES.get(number)
        except TypeError:            # number is an unhashable type
            expected = None
        if expected is None:
            problems.append(f"Question {number} is not one of the 11 sections.")
            continue
        if question.get("titleEn") != expected[0]:
            problems.append(
                f"Question {number} titleEn is {question.get('titleEn')!r}; "
                f"it must be exactly {expected[0]!r}.")
        if question.get("titleDe") != expected[1]:
            problems.append(
                f"Question {number} titleDe is {question.get('titleDe')!r}; "
                f"it must be exactly {expected[1]!r}.")
        slides = question.get("slides") or []
        if not isinstance(slides, list):
            problems.append(f"Question {number} 'slides' must be a list.")
            continue
        if not slides:
            problems.append(f"Question {number} has no slides.")
        for slide in slides:
            if not isinstance(slide, dict):
                problems.append(
                    f"Question {number} has a slide that is not an object.")
                continue
            layout = slide.get("layout")
            if not isinstance(layout, str) or layout not in LAYOUTS:
                problems.append(
                    f"Question {number} uses unknown layout {layout!r}. "
                    f"Supported: {', '.join(sorted(LAYOUTS))}.")

    if problems:
        return problems

    # Nothing above catches a slide that is missing the fields ITS layout
    # needs (a "table" with no columns). The strict union does - run it with
    # placeholder stamps, exactly as finalize.py will.
    tightened = tighten_plan(draft)
    tightened["date"] = "2026-01-01"
    tightened["oppId"] = ""
    try:
        SlidePlan.model_validate(tightened)
    except ValidationError as exc:
        problems.append(f"A slide is missing fields its layout needs: {exc}")
    return problems


# --------------------------------------------------------------------- CLI
_CHECKS = {"corpus": check_corpus, "analysis": check_analysis,
           "plan": check_plan}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Validate one stage output.")
    group = ap.add_mutually_exclusive_group(required=True)
    for name in _CHECKS:
        group.add_argument(f"--{name}", metavar="PATH",
                           help=f"validate a {name} JSON file")
    args = ap.parse_args(argv)

    kind = next(k for k in _CHECKS if getattr(args, k))
    path = getattr(args, kind)
    if not os.path.exists(path):
        print(f"Not found: {path}", file=sys.stderr)
        return 1
    try:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
    except json.JSONDecodeError as exc:
        print(f"{os.path.basename(path)} is not valid JSON: {exc}",
              file=sys.stderr)
        return 1

    problems = _CHECKS[kind](payload)
    if not problems:
        print(f"{kind}: OK")
        return 0
    for problem in problems:
        print(problem, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
