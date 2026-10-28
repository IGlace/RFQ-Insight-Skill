"""Finalize RFQ decks, replay saved plans, and choose deliverable filenames."""
import copy
import datetime
import json
import os
import re

from . import branding
from .dates import compact_date
from .verification import (attach_confidence_notes,   # noqa: E402
                           section_confidence)
from .corpus import (ATTACHMENT_SEP, UNREAD_ATTACHMENT, UNREAD_MAIL_SUFFIX,  # noqa: E402
                     corpus_revision)
from .opportunity import (account_match_is_current, account_risk_line,  # noqa: E402
                             add_account_risk, apply_account_match,
                             display_name, fill_opportunity_slide,
                             place_account_risk)
from .planning import _typed_table, sanitize_plan      # noqa: E402
from .sources import (DOWNGRADE_NOTE, _SHEET_MARKER_RE,  # noqa: E402
                      attach_sources)
from .schema import (ADDITIONAL_INFO_ID, SOURCES, SlidePlan,  # noqa: E402
                     tighten_plan)
from .validation import (check_final_opportunity,       # noqa: E402
                         check_opportunity_values, strip_python_sections)
from .workers import PROMPTS                             # noqa: E402


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


ANALYSIS_PROMPT = PROMPTS["analysis"]
SLIDE_PLAN_PROMPT = PROMPTS["slides"]
USAGE = {"mode": "in-session", "note": "not measured"}


# ------------------------------------------------ Source Material (Python)
# Section 12 is built here from the corpus, never by a model: one row per
# file, what of it was read and which sections cite it. It carries no
# deductions: an unread page or a skipped file is reported in the Read
# column and never costs points (the section always scores 10/10).
SOURCE_COLUMNS = ["File", "Type", "Read", "Used by sections"]
WHOLE_FILE = "whole file"
# States the fact instead of a bare dash the reader has to guess at (client
# requirement 3, 15.10.2026): the file WAS read, no section needed to cite it.
NONE_CELL = "Not cited"
_PAGE_MARK = re.compile(r"^--- Page (\d+) ---$", re.MULTILINE)
_SLIDE_MARK = re.compile(r"^--- Slide (\d+) ---$", re.MULTILINE)
# What the extractors and the figure stage leave where something could not
# be read (rfq/extractors.py extract_pdf, rfq/figures.py unread_note). The
# "small figure(s) ... not read" note is not counted: those are icons by
# design (extractors._embedded_page_images).
_UNREAD_PAGE = re.compile(r"\[\[PAGE (\d+) could not be read\]\]")
_UNREAD_PICTURE = re.compile(r"\[\[PICTURE \S+ at [^\]]*? could not be read\]\]")


def _cell(value) -> str:
    """One table cell: a single line without the pipe that ends cells."""
    return " ".join(str(value or "").replace("|", "/").split()) or NONE_CELL


# Marks an attachment row once per level beneath its mail ("↳ Spec.pdf",
# "↳ ↳ Spec.pdf"). A visible mark, not an indent: the plan strips the
# whitespace around every table cell, so spaces would be lost on the slide.
ATTACHMENT_MARK = "\u21b3 "


def _span(numbers, noun) -> str:
    """The marker numbers as one span: "page 1", "pages 1-12"."""
    numbers = sorted(set(numbers))
    if len(numbers) == 1:
        return f"{noun} {numbers[0]}"
    return f"{noun}s {numbers[0]}-{numbers[-1]}"


def _coverage(text: str) -> str:
    """What the file's location markers say was read."""
    pages = [int(n) for n in _PAGE_MARK.findall(text)]
    if pages:
        return _span(pages, "page")
    slides = [int(n) for n in _SLIDE_MARK.findall(text)]
    if slides:
        return _span(slides, "slide")
    sheets = list(dict.fromkeys(_SHEET_MARKER_RE.findall(text)))
    if sheets:
        return ("sheet: " if len(sheets) == 1 else "sheets: ") + ", ".join(sheets)
    return WHOLE_FILE


def _unread(text: str) -> str:
    """What the file's text marks as unread ("page 2 and 1 picture"), or
    an empty string."""
    pages = sorted({int(n) for n in _UNREAD_PAGE.findall(text)})
    pictures = len(_UNREAD_PICTURE.findall(text))
    parts = []
    if pages:
        parts.append(("page " if len(pages) == 1 else "pages ")
                     + ", ".join(map(str, pages)))
    if pictures:
        parts.append(f"{pictures} picture" + ("" if pictures == 1 else "s"))
    return " and ".join(parts)


def _file_type(filename: str, extension="") -> str:
    last = str(filename).split(ATTACHMENT_SEP)[-1]
    ext = str(extension or os.path.splitext(last)[1]).lstrip(".")
    if not ext:
        return "Unknown"
    return "E-mail" if ext.lower() == "msg" else ext.upper()


def _not_read_reason(name: str) -> str:
    """Why an attachment listed in extraction.ignored was not read."""
    last = name.split(ATTACHMENT_SEP)[-1]
    if last == UNREAD_ATTACHMENT:
        return "attachment could not be read"
    if last.endswith(UNREAD_MAIL_SUFFIX):
        return "e-mail could not be read"
    if last.lower().endswith(".msg"):
        return "nested e-mail"
    return "unsupported file type"


def build_source_material(corpus: dict, analysis: dict, catalog=None) -> dict:
    """The Source Material answer (section 12), built from corpus.json.

    One `| File | Type | Read | Used by sections |` row per corpus file in
    corpus order, then one per skipped file. An attachment sits beneath
    its mail, marked once per level; its skipped and not-read attachments
    (extraction.ignored: unsupported type, mail nested too deep, could not
    be unpacked) follow the ones that were read. Read is what the location
    markers cover ("pages 1-12", "slides 1-8", "sheets: A, B", else "whole
    file"); a file with an unreadable page or picture reads "partly: ...",
    a skipped one "skipped: <reason>" and an ignored attachment "not read:
    <reason>". Used by lists the sections whose
    sources cite the file. There are no deductions (the section scores
    10/10); the sources are every read file. `catalog`
    (source_catalog.json) is accepted for callers that hold it; it is built
    from the same markers, so it adds nothing here."""
    corpus = corpus if isinstance(corpus, dict) else {}
    analysis = analysis if isinstance(analysis, dict) else {}
    cited = {}
    for answer in analysis.get("answers") or []:
        if (not isinstance(answer, dict) or type(answer.get("id")) is not int
                or answer["id"] == SOURCES):
            continue
        for source in answer.get("sources") or []:
            if isinstance(source, dict):
                cited.setdefault(str(source.get("filename", "")), set()).add(
                    answer["id"])

    def used_by(name):
        return ", ".join(map(str, sorted(cited.get(name, ())))) or NONE_CELL

    # One row per file path: a file listed twice is one row, and two files
    # sharing a basename in different folders are named by their paths.
    files = [entry for entry in corpus.get("filesContents") or []
             if isinstance(entry, dict)]
    extraction = corpus.get("extraction") or {}
    skips = [entry for entry in extraction.get("skipped") or []
             if isinstance(entry, dict)]
    not_read = [{"filename": item[:-len(UNREAD_MAIL_SUFFIX)]
                 if item.endswith(UNREAD_MAIL_SUFFIX) else item,
                 "path": item, "not_read": _not_read_reason(item)}
                for item in extraction.get("ignored") or []
                if isinstance(item, str) and ATTACHMENT_SEP in item]

    def name_of(entry):
        return str(entry.get("filename")
                   or os.path.basename(str(entry.get("path", ""))))

    def path_of(entry):
        return str(entry.get("path") or name_of(entry))

    paths = {}
    for entry in files + skips:
        paths.setdefault(name_of(entry), set()).add(path_of(entry))
    seen = set()

    def first(entry):
        if path_of(entry) in seen:
            return False
        seen.add(path_of(entry))
        return True

    def label(entry):
        name = name_of(entry)
        if ATTACHMENT_SEP in name:
            # An attachment sits under its mail, which precedes it.
            parts = name.split(ATTACHMENT_SEP)
            return ATTACHMENT_MARK * (len(parts) - 1) + parts[-1]
        return path_of(entry) if len(paths[name]) > 1 else name

    def skipped_row(entry):
        name = name_of(entry)
        if entry.get("not_read"):
            how = f"not read: {entry['not_read']}"
        else:
            how = f"skipped: {entry.get('reason') or 'it could not be opened'}"
        return [_cell(label(entry)), _cell(_file_type(name)), _cell(how),
                used_by(name)]

    rows, row_paths, read = [], [], []
    for entry in files:
        if not first(entry):
            continue
        name = name_of(entry)
        text = str(entry.get("extracted_text", "") or "")
        coverage, unread = _coverage(text), _unread(text)
        how = coverage
        if unread:
            how = f"partly: {unread} could not be read" + (
                f" ({coverage})" if coverage != WHOLE_FILE else "")
        rows.append([_cell(label(entry)),
                     _cell(_file_type(name, entry.get("extension"))),
                     _cell(how), used_by(name)])
        row_paths.append(path_of(entry))
        read.append(name)
    # An attachment that was not read sits at the end of its parent's
    # rows (the parent's own read attachments and theirs); the other
    # skipped files follow all of them.
    rest = []
    for entry in [e for e in skips if ATTACHMENT_SEP in name_of(e)] + not_read:
        parent = path_of(entry).rsplit(ATTACHMENT_SEP, 1)[0]
        under = [i for i, p in enumerate(row_paths)
                 if p == parent or p.startswith(parent + ATTACHMENT_SEP)]
        if not under:
            rest.append(entry)
        elif first(entry):
            rows.insert(under[-1] + 1, skipped_row(entry))
            row_paths.insert(under[-1] + 1, path_of(entry))
    for entry in [e for e in skips if ATTACHMENT_SEP not in name_of(e)] + rest:
        if not first(entry):
            continue
        rows.append(skipped_row(entry))

    return {"id": SOURCES, "answer": _typed_table(SOURCE_COLUMNS, rows),
            "not_found": False, "shown": None, "deductions": [],
            "sources": [{"filename": name, "locator": ""}
                        for name in dict.fromkeys(read)]}


def add_python_sections(analysis: dict, corpus: dict) -> dict:
    """Replace any Source Material answer in `analysis` with the one built
    from `corpus` (appended last, after section 11). The pipeline calls it
    once the analysis passes its gates, so analysis.json, the slide plan's
    input and the deck all carry the built section. Mutates and returns
    `analysis`."""
    strip_python_sections(analysis)
    analysis["answers"].append(build_source_material(corpus, analysis))
    return analysis


def scored_analysis(analysis) -> bool:
    """True if the analysis is scored from deductions: at least one answer
    carries a `deductions` list. Reports made before the scored confidence
    carry none; their saved chips and notes are replayed as they are."""
    answers = (analysis or {}).get("answers") if isinstance(analysis, dict) else None
    return any(isinstance(a, dict) and isinstance(a.get("deductions"), list)
               for a in answers or [])


def _score_answers(analysis: dict) -> None:
    """Every answer of the report's analysis carries its resolved
    deductions (points and notes line), score and band, so a replay
    (`rfq_run.py render`) and a follow-up deck read the same numbers."""
    for answer in analysis.get("answers") or []:
        if isinstance(answer, dict) and type(answer.get("id")) is int:
            resolved, value, level = section_confidence(answer["id"], answer)
            answer["deductions"], answer["score"], answer["band"] = (
                resolved, value, level)


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
    excluded from client presentations. A `draft_plan` may carry the slide
    stage's parser actions under PLAN_ACTIONS_KEY (load_checkpoints puts
    them there); they open the report's sanitizer actions."""
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
    # Source Material is the runner's (the pipeline writes it into
    # analysis.json after the analysis gates); an analysis without one gets
    # it here, before sources, score and notes are attached. A saved one (a
    # replayed older checkpoint) is kept.
    answers = analysis.get("answers")
    if isinstance(answers, list) and not any(
            isinstance(a, dict) and a.get("id") == SOURCES for a in answers):
        answers.append(build_source_material(corpus, analysis))

    # A deep copy: `tighten_plan` reassigns each question's "slides" list,
    # and a shallow `dict(draft_plan)` would leave those nested question
    # dicts shared with the caller's object, so the caller's draft would be
    # mutated as a side effect of calling finalize().
    plan = copy.deepcopy(draft_plan)
    # None-pruning only accepts object slides. Reject malformed containers
    # before that transformation; the strict union below checks their fields.
    if not isinstance(plan, dict) or not isinstance(plan.get("questions"), list):
        raise ValueError("The slide plan must be an object with a questions list.")
    # The slide stage's own sanitizer actions (text the markdown parser
    # dropped), attached by load_checkpoints from .work/plan_actions.json.
    plan_actions = [str(a) for a in plan.pop(PLAN_ACTIONS_KEY, None) or []
                    if isinstance(a, str)]
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
    # The footer identity: saved with the run (--author/--department), else
    # the machine's configuration, else the fallback (recorded below).
    identity = branding.resolve_identity(corpus.get("author"),
                                         corpus.get("department"))
    plan["author"], plan["department"] = identity["author"], identity["department"]
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
    _score_answers(analysis)

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
    actions = plan_actions + opportunity_actions + notes_actions + actions
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

    from .renderer import render_to_bytes     # python-pptx: only to build a deck
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
        },
        "analysis": analysis,
        "slidePlan": plan,
    }
    report["run"]["identity"] = identity
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


# The draft key that carries the slide stage's parser actions
# (.work/plan_actions.json) from load_checkpoints to finalize().
PLAN_ACTIONS_KEY = "planActions"


def load_checkpoints(folder: str) -> dict:
    """The checkpoints finalize() needs. Raises ValueError when a required
    one is missing; unreadable execution metadata never blocks a deck.
    The slide stage's parser actions (.work/plan_actions.json) ride on the
    draft under PLAN_ACTIONS_KEY; finalize() moves them into the report's
    sanitizer actions."""
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
    try:
        plan_actions = _load(os.path.join(work, "plan_actions.json"))
    except (ValueError, OSError):
        plan_actions = None     # report detail only, never blocks the deck
    if isinstance(plan_actions, list) and plan_actions and isinstance(draft, dict):
        # finalize() takes the draft's actions out before validating it.
        draft[PLAN_ACTIONS_KEY] = plan_actions
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
        analysis = payload.get("analysis") or {}
        attach_sources(plan, analysis, files=files)
        for question in plan.get("questions", []):
            if question.get("number") == ADDITIONAL_INFO_ID:
                for slide in question.get("slides", []):
                    own = slide.get("sourceDetails") or slide.get("sourceLine") or ""
                    slide["sourceDetails"] = own
                question["sourceDetails"] = "Sources:\nSee each follow-up slide's notes."
        if scored_analysis(analysis):
            _rescore(plan, payload, work, current)
        # A report from before the scored confidence keeps its saved chips
        # and notes: its answers carry no deductions to score again.
    return plan


def _rescore(plan: dict, payload: dict, work: str, current: bool) -> None:
    """Attach score, band and notes to a replayed plan again, from the
    report's own (resolved) deductions; the same numbers it was built
    with. Section 13 keeps its saved notes (no analysis answer)."""
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
    from .renderer import render_to_bytes     # python-pptx: only to build a deck
    deck = render_to_bytes(plan, images_dir=images_dir)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as fh:
        fh.write(deck)
    slides = sum(len(q.get("slides", [])) for q in plan.get("questions", []))
    return {"pptx": out_path, "sections": len(plan.get("questions", [])),
            "slides": slides, "bytes": len(deck)}
