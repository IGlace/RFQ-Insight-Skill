"""Validate workflow checkpoints and evaluate completed RFQ reports."""

import json
import os
import re

from pydantic import ValidationError

from .figures import picture_source, resolve_picture_file, slide_source_line
from .guidance import INFO_NOT_AVAILABLE, load_guidance, vocabulary
from .opportunity import MAIN_COLUMNS, OPPORTUNITY_ROWS, build_opportunity_slide
from .schema import (ADDITIONAL_INFO_ID, COLLABORATION, DESCRIPTION, OPPORTUNITY,
                     PHASES, RISKS, SECTION_IDS, SECTION_SHAPES, STANDARDS,
                     TIMING, TITLES, AnalysisResult, LoosePlanDraft, SlidePlan,
                     describe_shapes, section_number_errors, tighten_plan)
from .sources import NOT_FOUND_LINE, check_sources
from .verification import model_rating

MAX_CORPUS_CHARS = 600_000
CONFIDENCES = {"high", "medium", "low"}
MIN_REASON_CHARS = 40
MAX_REASON_CHARS = 900     # 1-3 short sentences; the reason fills the slide notes
ANSWER_FIELDS = ("id", "answer", "tldr", "not_found", "confidence",
                 "confidence_reason", "sources")
LAYOUTS = {"bullets", "table", "twoColumn", "panel", "prosCons", "timeline",
           "gantt", "kpi", "prose", "phases", "collab", "ownership",
           "opportunity"}


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
    # our own corpus.py, so it is well formed in a normal run - but
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
        if not isinstance(entry.get("filename"), str) or not entry.get("filename"):
            problems.append(f"File {n} filename must be a nonempty string.")
        if "extracted_text" not in entry:
            problems.append(
                f"{entry.get('filename', f'file {n}')} has no extracted_text.")
        elif entry["extracted_text"] is not None and not isinstance(entry["extracted_text"], str):
            problems.append(f"File {n} extracted_text must be a string.")

    if problems:
        return problems
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
def check_analysis(analysis: dict, corpus: dict | None = None) -> list:
    problems = []
    corpus_files = None
    if isinstance(corpus, dict):
        corpus_files = [f for f in (corpus.get("filesContents")
                                    or corpus.get("files") or [])
                        if isinstance(f, dict)]
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

    missing = [i for i in SECTION_IDS if i not in ids]
    if missing:
        problems.append("Missing section(s): "
                        + ", ".join(str(i) for i in missing))
    unknown = [i for i in ids if i not in SECTION_IDS]
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
        reason = str(answer.get("confidence_reason", "") or "").strip()
        if "confidence_reason" in answer and len(reason) < MIN_REASON_CHARS:
            problems.append(
                f"{label} confidence_reason is too short; explain the "
                f"rating in 2-4 sentences (what it rests on, what is "
                f"inferred, which items are not available and why).")
        # Only the model's own words count: a resume validates an analysis
        # whose lowered sections rfq/verification.py has extended.
        own = model_rating(answer)[1]
        if len(own) > MAX_REASON_CHARS:
            problems.append(
                f"{label} confidence_reason is too long ({len(own)} "
                f"characters); keep the reason to 2-4 sentences (at most "
                f"{MAX_REASON_CHARS} characters).")
        if corpus_files is not None:
            problems.extend(check_sources(
                answer.get("sources") or [], corpus_files, label,
                require=not answer.get("not_found")))
    problems += _check_opportunity(
        analysis.get("opportunity") if isinstance(analysis, dict) else None)
    return problems


OPPORTUNITY_SEP = " – "        # en dash, one space either side


def _percent(value):
    """The int behind a percent field, or None (bool is not a number here)."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _check_percent_list(label: str, items, allowed: list) -> list:
    if not isinstance(items, list) or not items:
        return [f"opportunity.{label} must list at least one item."]
    problems, names = [], []
    for item in items:
        if not isinstance(item, dict):
            problems.append(f"opportunity.{label} has an entry that is not "
                            f"an object.")
            continue
        name, pct = item.get("name"), _percent(item.get("percent"))
        names.append(name)
        if name not in allowed:
            problems.append(
                f"opportunity.{label}: {name!r} is not an official Guidance "
                f"value; use one of: {', '.join(allowed)}.")
        if pct is None or not 1 <= pct <= 100:
            problems.append(
                f"opportunity.{label}: {name!r} has percent "
                f"{item.get('percent')!r}; it must be a whole number from 1 "
                f"to 100 (leave 0% items out).")
    if len(set(map(str, names))) != len(names):
        problems.append(f"opportunity.{label} lists a name twice.")
    total = sum(_percent(i.get("percent")) or 0
                for i in items if isinstance(i, dict))
    if total != 100:
        problems.append(f"opportunity.{label} percentages add up to {total}; "
                        f"they must add up to exactly 100.")
    return problems


def check_opportunity_values(info, require_name=True) -> list:
    """Opportunity facts against Guidance, independently of lookup stage."""
    if not isinstance(info, dict):
        return ["The analysis has no 'opportunity' object (section 1 fields, "
                "Products (%) and Skills (%))."]
    problems = []
    for field, kind in (("project_type", "project_types"),
                        ("technology", "technologies"),
                        ("industry", "industries")):
        allowed = vocabulary(kind)
        if info.get(field) not in allowed:
            problems.append(f"opportunity.{field} is {info.get(field)!r}; use "
                            f"exactly one of: {', '.join(allowed)}.")
    problems += _check_percent_list("products", info.get("products"),
                                    vocabulary("products"))
    problems += _check_percent_list("skills", info.get("skills"),
                                    vocabulary("skills"))
    products = info.get("products")
    major = [p.get("name") for p in (products if isinstance(products, list) else [])
             if isinstance(p, dict) and (_percent(p.get("percent")) or 0) >= 5]
    if info.get("lead_product") not in major:
        problems.append(
            f"opportunity.lead_product {info.get('lead_product')!r} must be one "
            f"of the listed products with at least 5%: "
            f"{', '.join(map(str, major)) or 'none'}.")
    short = str(info.get("customer_short") or "").strip()
    title = str(info.get("project_title") or "").strip()
    if require_name and (not short or not title):
        problems.append("opportunity.customer_short and "
                        "opportunity.project_title must both be filled.")
    elif require_name and info.get("opportunity_name") != f"{short}{OPPORTUNITY_SEP}{title}":
        problems.append(
            f"opportunity.opportunity_name must be exactly "
            f"{short + OPPORTUNITY_SEP + title!r} (customer_short, ' – ', "
            f"project_title).")
    return problems


def _check_opportunity(info) -> list:
    """Worker-only account placeholders plus the shared value rules."""
    problems = check_opportunity_values(info)
    if not isinstance(info, dict):
        return problems
    for field in ("account_name", "kam_pte"):
        if info.get(field, INFO_NOT_AVAILABLE) != INFO_NOT_AVAILABLE:
            problems.append(
                f"opportunity.{field} must be {INFO_NOT_AVAILABLE!r}: the "
                f"pipeline fills it from the Salesforce account list, never "
                f"the analysis.")
    return problems


def check_final_account_pair(info):
    def space(value):
        return " ".join(str(value or "").split())
    account = space(info.get("account_name"))
    kam = space(info.get("kam_pte"))
    unavailable = INFO_NOT_AVAILABLE
    if account == unavailable and kam == unavailable:
        return []
    if not account or account == unavailable or not kam:
        return ["The final Account Name (Site) / KAM (PTE) pair is invalid."]
    for row in load_guidance()["accounts"]:
        expected_kam = space(row.get("kam_pte")) or unavailable
        if space(row.get("name")) == account and expected_kam == kam:
            return []
    return ["The final Account Name (Site) / KAM (PTE) pair is not a Guidance row."]


def decode_opportunity_slide(slide):
    rows = slide.get("rows")
    if (slide.get("columns") != list(MAIN_COLUMNS)
            or not isinstance(rows, list)
            or len(rows) != len(OPPORTUNITY_ROWS)
            or any(not isinstance(row, list) or len(row) != 2 for row in rows)
            or [row[0] for row in rows] != [label for label, _ in OPPORTUNITY_ROWS]):
        raise ValueError("Opportunity table columns or row labels are invalid.")
    info = {key: row[1] for (_, key), row in zip(OPPORTUNITY_ROWS, rows)}
    for kind in ("products", "skills"):
        values = slide.get(kind)
        if not isinstance(values, list):
            raise ValueError(f"Opportunity {kind} table is missing.")
        items = []
        for row in values:
            if (not isinstance(row, list) or len(row) != 2
                    or not isinstance(row[1], str)
                    or re.fullmatch(r"\d+%", row[1]) is None):
                raise ValueError(f"Opportunity {kind} row is invalid.")
            items.append({"name": row[0], "percent": int(row[1][:-1])})
        info[kind] = items
    return info


def check_final_opportunity(analysis, plan):
    """Final semantic gate; callers validate SlidePlan structure first."""
    questions = [q for q in plan.get("questions", [])
                 if q.get("number") == OPPORTUNITY]
    if len(questions) != 1:
        return ["The final plan must contain exactly one Opportunity section."]
    slides = questions[0].get("slides") or []
    if len(slides) != 1 or slides[0].get("layout") != "opportunity":
        return ["The Opportunity section must contain exactly one opportunity slide."]
    slide = slides[0]
    if analysis is None:
        try:
            info = decode_opportunity_slide(slide)
        except ValueError as error:
            return [str(error)]
    else:
        info = analysis.get("opportunity") if isinstance(analysis, dict) else None
    errors = check_opportunity_values(info, require_name=analysis is not None)
    if not isinstance(info, dict):
        return errors
    errors += check_final_account_pair(info)
    if errors:
        return errors
    expected = build_opportunity_slide(info)
    for key in ("columns", "rows", "products", "skills"):
        if slide.get(key) != expected[key]:
            errors.append(f"The final Opportunity {key} differ from validated values.")
    return errors


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

    # Inspect the input numbers, before any model normalization can hide a
    # non-integer JSON value. Keep the detailed title/layout checks below.
    raw_questions = plan.get("questions", []) if isinstance(plan, dict) else []
    numbers = [q.get("number") for q in raw_questions if isinstance(q, dict)]
    problems += section_number_errors(numbers, allow_additional=False)
    missing = [i for i in SECTION_IDS if i not in numbers]
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
            problems.append(f"Question {number} is not one of the "
                            f"{len(SECTION_IDS)} sections.")
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
            # The shape check below would only repeat this, at length.
            problems.append(f"Question {number} has no slides.")
            continue
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

        if number == COLLABORATION:
            objects = [s for s in slides if isinstance(s, dict)]
            if [s.get("layout") for s in objects] != ["collab"]:
                problems.append(
                    f"Question {COLLABORATION} ({expected[0]}) must be exactly "
                    f"one 'collab' slide titled {expected[0]!r}.")
            elif len(objects[0].get("parties") or []) < 2:
                problems.append(
                    f"Question {COLLABORATION} ({expected[0]}) must show at "
                    f"least the customer and AVL as parties.")

        if number == OPPORTUNITY and [
                s.get("layout") for s in slides if isinstance(s, dict)
        ] != ["opportunity"]:
            problems.append(
                f"Question {OPPORTUNITY} ({expected[0]}) must be exactly one "
                f"'opportunity' slide; the application fills its tables.")

        # Every other section: the plan may carry only the shapes the section
        # contract names. Opportunity and Collaboration keep the messages
        # above, which say the same thing in their own words.
        if number not in (OPPORTUNITY, COLLABORATION):
            objects = [s for s in slides if isinstance(s, dict)]
            shape = tuple(s.get("layout") for s in objects)
            # SECTION_SHAPES[number], not .get(): every TITLES id has a row,
            # and a future id without one must fail loudly here rather than
            # reject every plan with an empty "it must be exactly ." message.
            if shape not in SECTION_SHAPES[number]:
                problems.append(
                    f"Question {number} ({expected[0]}) has slides "
                    f"{' + '.join(str(s) for s in shape) or '(none)'}; it must "
                    f"be exactly {describe_shapes(number)}. Do not add a slide "
                    f"of your own to a section: long tables, lists and panels "
                    f"stay on one slide and the renderer continues them "
                    f"itself.")
            elif number == RISKS and any(not s.get("items") for s in objects):
                # An empty panel renders as a blank slide, which is the very
                # fault the shape contract exists to prevent.
                problems.append(
                    f"Question {RISKS} ({expected[0]}): both risk panels must "
                    f"carry at least one item.")

    if problems:
        return problems

    # Nothing above catches a slide that is missing the fields ITS layout
    # needs (a "table" with no columns). The strict union does - run it with
    # placeholder stamps, exactly as rfq/delivery.py will.
    tightened = tighten_plan(draft)
    tightened["date"] = "2026-01-01"
    tightened["oppId"] = ""
    try:
        SlidePlan.model_validate(tightened)
    except ValidationError as exc:
        problems.append(f"A slide is missing fields its layout needs: {exc}")
    return problems


TAGS = ("(inferred)", "(assessment)", "(analysis)", "(not found)")

def _loads_lenient(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        out, in_str, esc = [], False, False
        for i, c in enumerate(text):
            if in_str:
                out.append(c)
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == ",":
                j = i + 1
                while j < len(text) and text[j] in " \t\r\n":
                    j += 1
                if j < len(text) and text[j] in "}]":
                    continue
            out.append(c)
        return json.loads("".join(out))


def _walk_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_strings(v)


def _parse_date_key(s):
    """Calendar position shared with the renderer, without importing it."""
    from .dates import time_pos
    return time_pos(s)


def _phase_ok(name, corpus_norm):
    """Use the sanitizer's exact-or-fuzzy phase traceability rule."""
    from .planning import _phase_traceable
    return _phase_traceable(name, corpus_norm)


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def evaluate(payload, corpus_text=None, manifest=None, images_dir=None):
    fails, warns, oks = [], [], []
    if not isinstance(payload, dict):
        return ["C9 final plan structure is invalid: expected a report object"], warns, oks
    analysis = payload.get("analysis", {})
    plan = payload.get("slidePlan", {})
    if not isinstance(analysis, dict):
        return ["C9 report analysis structure is invalid: expected an object"], warns, oks
    answers = {a.get("id"): a for a in analysis.get("answers", [])}

    # C1 all sections present
    missing = [i for i in SECTION_IDS if i not in answers]
    (fails if missing else oks).append(
        f"C1 sections 1-{len(SECTION_IDS)} present"
        + (f" — MISSING {missing}" if missing else ""))

    # C1b complete report plans use the same section contract as finalization
    # and replay. Malformed question containers cannot support later checks.
    if not isinstance(plan, dict):
        return fails + ["C1b slidePlan must be a JSON object."], warns, oks
    questions = plan.get("questions")
    if not isinstance(questions, list):
        return fails + ["C1b 'questions' must be a list."], warns, oks
    if any(not isinstance(question, dict) for question in questions):
        return fails + ["C1b question entries must be JSON objects."], warns, oks
    section_errors = section_number_errors(
        [question.get("number") for question in questions], allow_additional=True)
    (fails if section_errors else oks).append(
        "C1b slide-plan sections appear once each in canonical order"
        + (" — " + " ".join(section_errors) if section_errors else ""))

    try:
        SlidePlan.model_validate(plan)
    except ValueError as exc:
        fails.append(f"C9 final plan structure is invalid: {exc}")
        # Partial evaluator fixtures still exercise independent checks.
        # Malformed slide objects cannot safely enter those checks.
        if any(not isinstance(q.get("slides", []), list)
               or any(not isinstance(s, dict) for s in q.get("slides", []))
               for q in questions):
            return fails, warns, oks
    else:
        problems = check_final_opportunity(analysis, plan)
        (fails if problems else oks).append(
            "C9 final Opportunity values and tables are valid"
            + (" — " + "; ".join(problems) if problems else ""))

    # C2 phases traceable to corpus + stage-1 answers (same sources and same
    # exact-or-fuzzy rule the sanitizer enforces — the slide-plan stage may
    # shorten a phase name, but every distinctive token must trace back)
    if corpus_text is not None:
        corpus_norm = _norm(corpus_text)
        answers_norm = _norm("\n".join(str(a.get("answer", ""))
                                       for a in analysis.get("answers", [])))
        source_norm = (corpus_norm + " " + answers_norm).strip()
        analysis_names, slide_names = [], []
        a6 = str(answers.get(PHASES, {}).get("answer", ""))
        for row in re.findall(r"^\|\s*\*{0,2}([^|*]+?)\*{0,2}\s*\|", a6, re.M):
            name = row.strip()
            if name.lower() in ("phase", "---", ""):
                continue
            analysis_names.append(name)
        for q in plan.get("questions", []):
            for sl in q.get("slides", []):
                if sl.get("layout") == "phases":
                    slide_names += [p.get("name", "") for p in sl.get("phases", [])]
        bad = []
        bad_analysis = []
        for name in set(analysis_names) - set(slide_names):
            if not _phase_ok(name, corpus_norm):
                bad_analysis.append(name)
        for name in set(slide_names):
            if not _phase_ok(name, source_norm):
                bad.append(name)
        (fails if bad else oks).append(
            "C2 phase names on SLIDES traceable to corpus/answers"
            + (f" — NOT TRACEABLE: {bad}" if bad else ""))
        if bad_analysis:
            warns.append("C2a analysis-layer phase names not in corpus "
                         f"(kept off the slides): {bad_analysis[:3]}")

    # C3 checks displayed slide content. Evidence quotes in speaker notes retain
    # the analysis's inference/absence tags so the reader can assess the rating.
    visible_plan = {key: value for key, value in plan.items() if key != "questions"}
    visible_plan["questions"] = [{key: value for key, value in question.items()
                                  if key != "confidenceNotes"}
                                 for question in questions]
    tagged = [s[:60] for s in _walk_strings(visible_plan)
              if any(t in s.lower() for t in TAGS)]
    (fails if tagged else oks).append(
        "C3 no literal tags in slide plan"
        + (f" — FOUND: {tagged[:3]}" if tagged else ""))

    # C4 ownership owner values
    bad_cells = []
    for q in plan.get("questions", []):
        for sl in q.get("slides", []):
            if sl.get("layout") != "ownership":
                continue
            # "joint" is the marker for a task the RFQ assigns to two parties
            # at once - not a fourth owner. It exists so a blank cell means
            # only one thing ("the RFQ assigns nobody"); see
            # renderer.py::OWNER_COLORS.
            allowed = {"avl", "supplier", "joint", "", "—", "-",
                       str(sl.get("customerAbbr", "customer")).lower(),
                       "customer"}
            stage_hdrs = {"phase", "phases", "stage", "development stage",
                          "development phase", "dev stage",
                          "development stages"}
            cols_ = sl.get("columns", [])
            owner_idxs = [i for i in range(1, len(cols_))
                          if str(cols_[i]).strip().lower() not in stage_hdrs]
            for row in sl.get("rows", []):
                for i in owner_idxs:
                    if i < len(row) and str(row[i]).strip().lower() not in allowed:
                        bad_cells.append(str(row[i]))
    (fails if bad_cells else oks).append(
        "C4 ownership cells normalized"
        + (f" — BAD VALUES: {sorted(set(bad_cells))[:5]}" if bad_cells else ""))

    # C5 timeline/gantt chronology
    disorder = []
    for q in plan.get("questions", []):
        for sl in q.get("slides", []):
            if sl.get("layout") not in ("timeline", "gantt"):
                continue
            keys = [(_parse_date_key(st.get("date", "")), st.get("label", ""))
                    for st in sl.get("steps", [])]
            known = [(k, lbl) for k, lbl in keys if k is not None]
            for (k1, l1), (k2, l2) in zip(known, known[1:]):
                if k2 < k1:
                    disorder.append(f"{l2} ({k2}) after {l1} ({k1})")
    if disorder:
        warns.append("C5 timeline steps out of order in the PLAN (renderer "
                     f"sorts them on the deck): {disorder[:3]}")
    else:
        oks.append("C5 timeline chronological")

    # C6 first-slide titles
    bad_titles = []
    for q in plan.get("questions", []):
        slides = q.get("slides", [])
        if slides and slides[0].get("title", "") != q.get("titleEn", ""):
            bad_titles.append(f"{q.get('titleEn')} -> {slides[0].get('title')}")
    (fails if bad_titles else oks).append(
        "C6 first slide titled per section"
        + (f" — {bad_titles[:3]}" if bad_titles else ""))

    # C7 complete source references are available in the speaker notes.
    no_src = [q.get("titleEn") for q in plan.get("questions", [])
              if not str(q.get("sourceDetails") or "").startswith(
                  ("Sources:", NOT_FOUND_LINE))]
    lost_src = [q.get("titleEn") for q in plan.get("questions", [])
                if q.get("sourceDetails") == NOT_FOUND_LINE
                and type(q.get("number")) is int
                and answers.get(q.get("number"), {}).get("not_found") is False]
    if no_src:
        fails.append(f"C7 source references in notes — MISSING: {no_src[:4]}")
    if lost_src:
        fails.append("C7 source references in notes — NOT FOUND although "
                     f"answered: {lost_src[:4]}")
    if not no_src and not lost_src:
        oks.append("C7 source references in notes")

    # W1 description scope
    for q in plan.get("questions", []):
        if q.get("titleEn") != TITLES[DESCRIPTION][0]:
            continue
        slides = q.get("slides", [])
        prose = [s for s in slides if s.get("layout") == "prose"]
        if len(slides) != len(prose) or len(prose) > 2:
            warns.append(f"W1 Description has {len(slides)} slides "
                         f"({[s.get('layout') for s in slides]}) — expected 1 prose")
        elif prose and len(prose[0].get("body", "").split()) > 300:
            warns.append("W1 Description body exceeds 300 words")
        else:
            oks.append("W1 Description is a compact prose slide")

    # W2 standards traceability
    if corpus_text is not None:
        corpus_norm = _norm(corpus_text)
        loose = []
        for q in plan.get("questions", []):
            if q.get("titleEn") != TITLES[STANDARDS][0]:
                continue
            for sl in q.get("slides", []):
                for row in sl.get("rows", []):
                    # SlidePlan permits an empty row, and this check runs
                    # AFTER both deliverables are already on disk - an
                    # IndexError here would be a traceback over a finished
                    # deck. The C4 check above guards the same way.
                    if not row:
                        continue
                    first = _norm(re.split(r"[(/;,]", str(row[0]))[0])
                    token = first.split(" ")[0] if first else ""
                    if token and token not in corpus_norm:
                        loose.append(str(row[0])[:40])
        if loose:
            warns.append(f"W2 standards not obviously in corpus: {loose[:4]}")
        else:
            oks.append("W2 standards traceable to corpus")

    # W3 confidence (the follow-up section has none of its own)
    missing_conf = [q.get("titleEn") for q in plan.get("questions", [])
                    if not q.get("confidence")
                    and q.get("number") != ADDITIONAL_INFO_ID]
    if missing_conf:
        warns.append(f"W3 confidence missing on: {missing_conf[:4]}")
    else:
        oks.append("W3 confidence present on all questions")

    # W4 near-empty twoColumn slides
    thin = []
    for q in plan.get("questions", []):
        for sl in q.get("slides", []):
            if sl.get("layout") == "twoColumn":
                if len(sl.get("leftItems", [])) + len(sl.get("rightItems", [])) < 3:
                    thin.append(sl.get("title", "")[:40])
    if thin:
        warns.append(f"W4 near-empty twoColumn slides: {thin}")
    else:
        oks.append("W4 no near-empty twoColumn slides")

    # W6 Risk Detection: one risk group per slide (client-confirmed format)
    for q in plan.get("questions", []):
        if q.get("titleEn") != TITLES[RISKS][0]:
            continue
        layouts = [sl.get("layout") for sl in q.get("slides", [])]
        if any(l in ("twoColumn", "prosCons") for l in layouts):
            warns.append("W6 Risk Detection mixes Project and Document risks "
                         f"on one slide (layouts: {layouts}) — expected "
                         "separate 'panel' slides per group")
        elif "panel" in layouts:
            oks.append("W6 Risk Detection separates risk groups per slide")

    # W5 Timing carries the one-slide gantt diagram (sales-confirmed format)
    for q in plan.get("questions", []):
        if q.get("titleEn") != TITLES[TIMING][0]:
            continue
        layouts = [sl.get("layout") for sl in q.get("slides", [])]
        if "gantt" in layouts:
            oks.append("W5 Timing uses the gantt diagram")
        elif "timeline" in layouts:
            warns.append("W5 Timing uses the fallback timeline (no gantt) — "
                         "expected only when milestones carry no calendar dates")
        else:
            warns.append(f"W5 Timing has no timing diagram (layouts: {layouts})")

    # CP1 product pictures trace to a real extracted image, captioned+sourced,
    # the slide's source line names them, and the report lists what is shown
    if manifest is not None:
        known = {e.get("id"): e for e in manifest.get("images", [])}
        fields = ("imageId", "file", "sha256", "caption", "source")
        bad_pics, bad_lines, shown = [], [], []
        byte_problems = []
        for q in plan.get("questions", []):
            for sl in q.get("slides", []):
                if sl.get("layout") != "pictures":
                    continue
                pics = sl.get("pictures", [])
                for p in pics:
                    shown.append(tuple(p.get(key) for key in fields))
                    entry = known.get(p.get("imageId"))
                    expected = None if entry is None else (
                        entry.get("id"), entry.get("file"), entry.get("sha256"),
                        " ".join(str(entry.get("caption", "")).split()),
                        picture_source(entry))
                    if (shown[-1] != expected
                            or not all(isinstance(p.get(key), str) and p[key].strip()
                                       for key in fields)):
                        bad_pics.append(str(p.get("imageId")))
                    if images_dir is not None:
                        try:
                            resolve_picture_file(p, images_dir)
                        except ValueError as exc:
                            byte_problems.append(str(exc))
                if sl.get("sourceLine") != slide_source_line(pics, manifest):
                    bad_lines.append(str(sl.get("title", ""))[:60])
        listed = [tuple(p.get(key) for key in fields)
                  for p in (payload.get("run") or {}).get("pictures") or []]
        problems = []
        if bad_pics:
            problems.append(f"BAD: {bad_pics[:4]}")
        if byte_problems:
            problems.extend(dict.fromkeys(byte_problems))
        if bad_lines:
            problems.append(f"source line does not match its pictures on "
                            f"{bad_lines[:2]}")
        if listed and not shown:
            problems.append(f"{len(listed)} picture(s) selected but no "
                            f"picture slide")
        elif listed != shown:
            problems.append("run.pictures identities differ from the slides")
        (fails if problems else oks).append(
            "CP1 product pictures traceable, captioned and sourced"
            + (" — " + "; ".join(problems) if problems else ""))

    # C8 confidence explained in the slide notes (client, 2026-10-07)
    unexplained = [q.get("titleEn") for q in plan.get("questions", [])
                   if q.get("confidence") and not q.get("confidenceNotes")]
    (fails if unexplained else oks).append(
        "C8 confidence explained in the slide notes"
        + (f" — MISSING: {unexplained[:4]}" if unexplained else ""))

    return fails, warns, oks


def run_evaluation(report_path, corpus_path=None, manifest=None, images_dir=None):
    """(fails, warns, oks) for a finished run report. `manifest` is the
    run's images.json (enables CP1)."""
    with open(report_path, encoding="utf-8") as fh:
        payload = json.load(fh)
    corpus_text = None
    if corpus_path:
        with open(corpus_path, encoding="utf-8") as fh:
            corpus = _loads_lenient(fh.read())
        fc = corpus.get("filesContents") or corpus.get("files") or []
        corpus_text = "\n".join(f.get("extracted_text", "") for f in fc)
    if images_dir is None and manifest is not None:
        images_dir = os.path.join(os.path.dirname(os.path.abspath(report_path)),
                                  ".work", "images")
    return evaluate(payload, corpus_text, manifest, images_dir)


def format_lines(fails, warns, oks):
    """The PASS/WARN/FAIL lines main() prints (also saved by the runner)."""
    return ([f"  PASS  {line}" for line in oks]
            + [f"  WARN  {line}" for line in warns]
            + [f"  FAIL  {line}" for line in fails])
