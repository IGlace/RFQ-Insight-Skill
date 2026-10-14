"""Finalize RFQ decks, replay saved plans, and choose deliverable filenames."""
import copy
import datetime
import json
import os
import re

from .dates import compact_date
from .verification import attach_confidence_notes        # noqa: E402
from .corpus import corpus_revision                # noqa: E402
from .opportunity import (account_match_is_current, account_risk_line,  # noqa: E402
                             add_account_risk, apply_account_match,
                             display_name, fill_opportunity_slide,
                             place_account_risk)
from .renderer import render_to_bytes                 # noqa: E402
from .planning import sanitize_plan                    # noqa: E402
from .sources import DOWNGRADE_NOTE, attach_sources    # noqa: E402
from .schema import ADDITIONAL_INFO_ID, SlidePlan, tighten_plan    # noqa: E402
from .validation import check_final_opportunity, check_opportunity_values  # noqa: E402


# Characters Windows does not allow in a file name, plus control characters.
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# A generous per-string cap. It does NOT by itself keep the full path under
# Windows' 260-character limit - the RFQ folder itself can be deeply nested,
# so deck_basename() additionally truncates the opportunity-name part
# against the real output folder (MAX_PATH below).
MAX_NAME = 150
MAX_PATH = 240     # the full "<out_dir>/<base>.pptx" path, safety margin kept
_PREFIX = "RFQ Insight_"
EXT_MARGIN = len(".pptx") + 4   # + room for next_free()'s "_2", "_3", ...


def safe_filename(text: str) -> str:
    """A file-name-safe version of `text` that stays readable: spaces, the
    en dash and accented letters are kept; only what Windows forbids is
    dropped. Idempotent."""
    name = _ILLEGAL.sub("", str(text or ""))
    name = re.sub(r"\s+", " ", name).strip().rstrip(". ")
    name = name[:MAX_NAME].rstrip(". ")
    return name or "RFQ"


def truncate_at_word(name: str, budget: int) -> str:
    """`name` cut to at most `budget` characters, at a word boundary when
    one exists, so a long opportunity name never splits mid-word."""
    if budget <= 0:
        return ""
    if len(name) <= budget:
        return name
    cut = name[:budget]
    sp = cut.rfind(" ")
    if sp > 0:
        cut = cut[:sp]
    return cut.rstrip(". –-")


def deck_basename(opportunity_name: str, iso_date: str, out_dir: str = "") -> str:
    """'RFQ Insight_<Opportunity name>_<DDMMYYYY>' (client format), without
    the extension.

    When `out_dir` is given, the opportunity-name part is truncated (at a
    word boundary; the prefix and date are never touched) so the full
    deliverable path `out_dir/<base>.pptx` stays within MAX_PATH - a deeply
    nested RFQ folder plus a long opportunity name can otherwise exceed
    Windows' 260-character limit and fail the write."""
    suffix = f"_{compact_date(iso_date)}"
    name = safe_filename(opportunity_name)
    if out_dir:
        budget = (MAX_PATH - len(out_dir) - 1 - len(_PREFIX) - len(suffix)
                 - EXT_MARGIN)
        name = truncate_at_word(name, budget) or "RFQ"
    return f"{_PREFIX}{name}{suffix}"


def next_free(out_dir: str, base: str, exts=(".pptx", ".json")) -> str:
    """`out_dir/base`, or `base_2`, `base_3`, ... - the first variant for
    which none of `exts` exists yet. Returned without an extension."""
    candidate = os.path.join(out_dir, base)
    version = 2
    while any(os.path.lexists(candidate + ext) for ext in exts):
        candidate = os.path.join(out_dir, f"{base}_{version}")
        version += 1
    return candidate


ANALYSIS_PROMPT = "RFQ_QA_Extraction_Prompt_v13.md"
SLIDE_PLAN_PROMPT = "RFQ_Slide_Plan_Prompt_v13.md"
USAGE = {"mode": "in-session", "note": "not measured"}


def deliverable_paths(folder: str, opportunity_name: str, iso_date: str):
    """(pptx, json) under the client's name, never overwriting a previous
    pair (`_2`, `_3`, ... are appended when needed)."""
    out_dir = os.path.join(os.path.abspath(folder), "output")
    base = next_free(out_dir, deck_basename(opportunity_name, iso_date,
                                            out_dir=out_dir))
    return base + ".pptx", base + ".json"


def add_product_pictures(plan: dict, manifest, images_dir):
    """Remove the retired picture appendix, including saved draft slides."""
    for question in plan.get("questions", []):
        question["slides"] = [slide for slide in question.get("slides", [])
                              if slide.get("layout") != "pictures"]
    return plan, [], []


def finalize(corpus: dict, analysis: dict, draft_plan: dict,
             verification=None, execution=None, account=None,
             followups=None, downgrades=None, manifest=None,
             images_dir=None):
    """(plan, deck_bytes, report). Raises ValueError if the plan is unusable.

    `followups` ({"followups": [...]}, entries in the deck flagged in_deck)
    only matters for a plan that carries the Additional Information
    section; the normal run's 12-section plan never does. `downgrades`
    (.work/source_downgrades.json) lists the citations the last analysis
    attempt had to keep as whole-file sources; the report and the section's
    slide notes name them.
    Figure extraction remains analysis evidence; product-picture slides are
    excluded from client presentations."""
    from pydantic import ValidationError

    if not isinstance(analysis, dict):
        raise ValueError("The analysis must be a JSON object.")

    # A missing, corrupt or stale account_match.json must never silently
    # skip the lookup: it gets the same Document Risk line a lookup that
    # genuinely found nothing would, and the slide falls back to "Info not
    # available" (apply_account_match below applies the same gate). Copied
    # first so add_account_risk's in-place append never mutates the
    # caller's analysis object.
    analysis = copy.deepcopy(analysis)
    opp_info = analysis.get("opportunity")
    if not isinstance(opp_info, dict):
        opp_info = {}
    lookup = account
    if not account_match_is_current(opp_info, account):
        lookup = {"status": "unreadable",
                  "customer": opp_info.get("customer", "")}
        add_account_risk(analysis, lookup)
    analysis = apply_account_match(analysis, account)

    # A deep copy: `tighten_plan` reassigns each question's "slides" list,
    # and a shallow `dict(draft_plan)` would leave those nested question
    # dicts shared with the caller's object, so the caller's draft would be
    # mutated as a side effect of calling finalize().
    plan = copy.deepcopy(draft_plan)
    # None-pruning only accepts object slides. Reject malformed containers
    # before that transformation; the strict union below checks their fields.
    if not isinstance(plan, dict) or not isinstance(plan.get("questions"), list):
        raise ValueError("The slide plan must be an object with a questions list.")
    for index, question in enumerate(plan["questions"], start=1):
        if not isinstance(question, dict):
            raise ValueError(f"The slide plan question #{index} must be an object.")
        slides = question.get("slides", [])
        if not isinstance(slides, list) or any(
                not isinstance(slide, dict) for slide in slides):
            raise ValueError(f"The slide plan question #{index} slides must be "
                             "a list of objects.")
    add_product_pictures(plan, None, None)
    plan = tighten_plan(plan)
    plan["date"] = datetime.date.today().isoformat()
    plan["oppId"] = ""
    # Cover, footer and end slide carry the opportunity name once the
    # analysis has one; until then the run's own name (--project or the
    # folder's). Set here only: follow-up decks and rfq_run.py render replay
    # the report's slidePlan, so they keep it.
    plan["projectName"] = display_name(
        opp_info, corpus.get("projectName") or plan.get("projectName", ""))
    try:
        plan = SlidePlan.model_validate(plan).model_dump()
    except ValidationError as exc:
        raise ValueError(f"the slide plan does not validate: {exc}") from exc

    # Validate raw percentages before deterministic table construction can
    # convert strings/bools or crash on malformed rows.
    problems = check_opportunity_values(analysis.get("opportunity"))
    if problems:
        raise ValueError(" ".join(problems))

    # Where each section comes from - computed here, never by the model.
    attach_sources(plan, analysis, followups,
                   files=corpus.get("filesContents"))
    # Each section's band (the chip), score and deductions, computed from
    # the analysis's deductions and explained in the slide notes;
    # Opportunity Info also explains the account lookup (the one finalize
    # actually applied).
    notes_actions = attach_confidence_notes(plan, analysis, verification,
                                            lookup, downgrades)

    # Section 1 is built here from the structured opportunity object; the
    # slide-plan model only emitted a placeholder for it.
    opportunity_actions = fill_opportunity_slide(plan, analysis)
    # The account risk line on section 11's slides is the application's
    # too: the model's own account items go, the current lookup's line (if
    # it has one) becomes the last Document Risks item.
    # A complete typed plan can prove a source risk mentions Salesforce for
    # substantive reasons. Preserve those exact authoritative items while
    # continuing to replace the application's own lookup sentence.
    from .planning import authoritative_risk_items
    protected = authoritative_risk_items(analysis)
    opportunity_actions += place_account_risk(plan, account_risk_line(lookup), protected)

    files = corpus.get("filesContents", [])
    corpus_text = "\n".join(f.get("extracted_text", "") or "" for f in files)
    # Stage-1 answers are a second trace source for phase names: a phase
    # grounded in the answers is legitimate even when the extraction garbled
    # the wording it came from.
    analysis_text = "\n".join(str(a.get("answer", ""))
                              for a in analysis.get("answers", []))
    plan, actions = sanitize_plan(plan, corpus_text, analysis_text)
    actions = opportunity_actions + notes_actions + actions
    plan, pictures_chosen, pictures_skipped = add_product_pictures(
        plan, manifest, images_dir)
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

    problems = check_final_opportunity(analysis, plan)
    if problems:
        raise ValueError(" ".join(problems))

    deck = render_to_bytes(plan, images_dir=images_dir)

    extraction = {k: v for k, v in corpus.get("extraction", {}).items()
                  if k != "preprocess"}
    report = {
        "run": {
            "generatedAt": datetime.datetime.now().isoformat(
                timespec="seconds"),
            "projectName": corpus.get("projectName", ""),
            "oppId": "",
            "corpusFiles": [f.get("filename", "") for f in files],
            "corpusRevision": corpus_revision(corpus),
            "prompts": {"analysis": ANALYSIS_PROMPT,
                        "slidePlan": SLIDE_PLAN_PROMPT},
            "usage": dict(USAGE),
            "preprocess": corpus.get("extraction", {}).get("preprocess", {}),
            "sanitizer": actions,
            "extraction": extraction,
            "pictures": pictures_chosen,
            "pictures_skipped": pictures_skipped,
            # images.json ids whose figure worker left no valid
            # classification (figures.apply_classifications)
            "pictures_unclassified": list((manifest or {}).get(
                "unclassified") or []),
        },
        "analysis": analysis,
        "slidePlan": plan,
    }
    if verification is not None:
        report["verification"] = verification
    if execution is not None:
        report["run"]["execution"] = copy.deepcopy(execution)
    if downgrades:
        report["run"]["sourceDowngrades"] = DOWNGRADE_NOTE + "; ".join(
            str(d) for d in downgrades)
    return plan, deck, report


def _load(path: str, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_checkpoints(folder: str) -> dict:
    """The checkpoints finalize() needs. Raises ValueError when a required
    one is missing; unreadable execution metadata never blocks a deck."""
    work = os.path.join(os.path.abspath(folder), "output", ".work")
    corpus = _load(os.path.join(work, "corpus.json"))
    analysis = _load(os.path.join(work, "analysis.json"))
    draft = _load(os.path.join(work, "slide_plan.json"))
    verification = _load(os.path.join(work, "verification.json"))
    try:
        execution = _load(os.path.join(work, "execution.json"))
    except (ValueError, OSError) as exc:
        # Optional routing metadata must not prevent delivery of a valid deck.
        execution = {"status": "error",
                     "note": f"Execution history unreadable: {exc}"}
    if corpus is None or analysis is None or draft is None:
        raise ValueError("A checkpoint is missing - I can't build the deck "
                         "from here.")
    try:
        account = _load(os.path.join(work, "account_match.json"))
    except (ValueError, OSError):
        # Corrupt is treated exactly like missing: finalize() adds the
        # Document Risk line, it never blocks delivery of the deck.
        account = None
    try:
        downgrades = _load(os.path.join(work, "source_downgrades.json"))
    except (ValueError, OSError):
        downgrades = None       # report detail only, never blocks the deck
    try:
        manifest = _load(os.path.join(work, "images.json"), {"images": []})
    except (ValueError, OSError):
        manifest = None         # no product pictures, never a blocker
    return {"corpus": corpus, "analysis": analysis, "draft": draft,
            "verification": verification, "execution": execution,
            "account": account,
            "downgrades": downgrades if isinstance(downgrades, list) else None,
            "manifest": manifest if isinstance(manifest, dict) else None,
            "images_dir": os.path.join(work, "images")}


def write_outputs(folder: str, corpus: dict, deck: bytes,
                  report: dict) -> tuple:
    """Write the deck, the run report and .work/deliverables.json under
    unused names. Returns (pptx_path, report_path)."""
    folder = os.path.abspath(folder)
    work = os.path.join(folder, "output", ".work")
    info = (report.get("analysis") or {}).get("opportunity") or {}
    pptx_path, report_path = deliverable_paths(
        folder, info.get("opportunity_name") or corpus.get("projectName", ""),
        report["slidePlan"]["date"])
    os.makedirs(os.path.dirname(pptx_path), exist_ok=True)
    # Exclusive creation also protects a file created after path selection.
    with open(pptx_path, "xb") as fh:
        fh.write(deck)
    with open(report_path, "x", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    os.makedirs(work, exist_ok=True)
    with open(os.path.join(work, "deliverables.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"pptx": pptx_path, "report": report_path}, fh, indent=2)
    return pptx_path, report_path


def load_plan(path: str) -> dict:
    """Pull the slide plan out of a run report, or accept a bare plan."""
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    plan = payload.get("slidePlan", payload)
    if not isinstance(plan, dict) or "questions" not in plan:
        raise ValueError(f"No slide plan in {path} — expected a run report with "
                         f'"slidePlan", or a plan with "questions".')
    # Validate shape before examining semantic rows, including bare previews.
    SlidePlan.model_validate(plan)
    problems = check_final_opportunity(
        payload.get("analysis", {}) if "slidePlan" in payload else None, plan)
    if problems:
        raise ValueError(" ".join(problems))
    add_product_pictures(plan, None, None)
    if "slidePlan" in payload:
        work = os.path.join(os.path.dirname(os.path.abspath(path)), ".work")
        try:
            corpus = _load(os.path.join(work, "corpus.json")) or {}
        except (OSError, ValueError):
            corpus = {}
        if not isinstance(corpus, dict):
            corpus = {}
        current = (bool(corpus) and (payload.get("run") or {}).get("corpusRevision")
                   == corpus_revision(corpus))
        files = corpus.get("filesContents") if current else None
        # Full report evidence remains authoritative when sibling checkpoints
        # are absent. Never silently reinterpret the saved confidence rating.
        attach_sources(plan, payload.get("analysis") or {}, files=files)
        for question in plan.get("questions", []):
            if question.get("number") == ADDITIONAL_INFO_ID:
                for slide in question.get("slides", []):
                    own = slide.get("sourceDetails") or slide.get("sourceLine") or ""
                    slide["sourceDetails"] = own
                question["sourceDetails"] = "Sources:\nSee each follow-up slide's notes."
        old_account = next(((q.get("confidenceNotes") or "").partition(
            "Account lookup (")[2].partition("\n\nHow the rating works:")[0]
            for q in plan.get("questions", []) if q.get("number") == 1), "")
        try:
            account = _load(os.path.join(work, "account_match.json")) if current else None
            downgrades = _load(os.path.join(work, "source_downgrades.json")) if current else None
        except (OSError, ValueError):
            account, downgrades = None, None
        saved_info = payload.get("analysis", {}).get("opportunity") or {}
        if not account_match_is_current(saved_info, account) or any(
                saved_info.get(key) != (account or {}).get(key)
                for key in ("account_name", "kam_pte")):
            account = None
        attach_confidence_notes(plan, payload.get("analysis") or {},
                                payload.get("verification"), account, downgrades)
        if old_account and not account:
            opportunity = next((q for q in plan["questions"] if q.get("number") == 1), None)
            if opportunity:
                opportunity["confidenceNotes"] += "\n\nAccount lookup (" + old_account
    return plan


def render_report(report_path, out_path=None) -> dict:
    """Render a saved report or bare plan, returning output and count metadata.

    The default output is a preview beside the report. An explicit output
    may replace an earlier preview. Validate tables and saved picture identity
    before creating the output directory or opening the destination.
    """
    report_path = os.fspath(report_path)
    plan = load_plan(report_path)
    plan = tighten_plan(SlidePlan.model_validate(plan).model_dump())
    out_path = (os.fspath(out_path) if out_path is not None else
                os.path.splitext(report_path)[0] + "_preview.pptx")
    images_dir = os.path.join(os.path.dirname(os.path.abspath(report_path)),
                              ".work", "images")
    deck = render_to_bytes(plan, images_dir=images_dir)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as fh:
        fh.write(deck)
    slides = sum(len(q.get("slides", [])) for q in plan.get("questions", []))
    return {"pptx": out_path, "sections": len(plan.get("questions", [])),
            "slides": slides, "bytes": len(deck)}
