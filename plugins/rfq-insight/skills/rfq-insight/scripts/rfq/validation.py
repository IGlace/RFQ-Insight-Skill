"""Validate workflow checkpoints and evaluate completed RFQ reports."""

import json
import os
import re

from pydantic import ValidationError

from .figures import picture_source, resolve_picture_file, slide_source_line
from .guidance import INFO_NOT_AVAILABLE, load_guidance, vocabulary
from .opportunity import MAIN_COLUMNS, OPPORTUNITY_ROWS, build_opportunity_slide
from . import confidence
from .schema import (ADDITIONAL_INFO_ID, COLLABORATION, DELIVERABLES,
                     DESCRIPTION, OPPORTUNITY, PHASES, RISKS, RULES, SCOPE,
                     SECTION_IDS, SECTION_MODES, SECTION_SHAPES, STANDARDS,
                     TECHNICAL, TIMING, TITLES, AnalysisResult, LoosePlanDraft,
                     SlidePlan, describe_shapes, rules_for,
                     section_number_errors, tighten_plan)
from .sources import NOT_FOUND_LINE, check_sources

MAX_CORPUS_CHARS = 600_000
ANSWER_FIELDS = ("id", "answer", "not_found", "deductions", "sources")
# The sections the analysis model answers; the runner builds the rest
# (Source Material) itself.
MODEL_SECTION_IDS = tuple(number for number in SECTION_IDS
                          if SECTION_MODES[number] != "python")
PYTHON_SECTION_IDS = tuple(number for number in SECTION_IDS
                           if SECTION_MODES[number] == "python")
# Codes only the runner writes (reviewer verdicts, corpus misses, unread
# files). A stored analysis may carry them; the model's output may not.
RUNNER_CODES = tuple(code for code, rule in RULES.items()
                     if rule.source == "python")
MAX_DEDUCTION_WORDS = 25
# Sections whose answer may be trimmed to the items that fit a slide.
SHOWN_SECTIONS = tuple(confidence.SHOWN_NOUNS)
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
def strip_python_sections(analysis):
    """Drop the answers Python builds itself (Source Material) from an
    analysis: an older checkpoint or a model may still carry one. Mutates
    and returns `analysis`."""
    if isinstance(analysis, dict) and isinstance(analysis.get("answers"), list):
        analysis["answers"] = [
            a for a in analysis["answers"]
            if not (isinstance(a, dict) and a.get("id") in PYTHON_SECTION_IDS)]
    return analysis


def _check_deductions(answer: dict, label: str, runner_codes=()) -> list:
    """The answer's `deductions` against the rule catalogue and `shown`
    against its section. Codes in `runner_codes` are accepted as the
    runner's own (a stored analysis); any other runner code is the model's
    and refused."""
    number = answer.get("id")
    problems = []
    deductions = answer.get("deductions", [])
    if not isinstance(deductions, list) or any(
            not isinstance(entry, dict) for entry in deductions):
        problems.append(f"{label} 'deductions' must be a list of objects "
                        f"(rule, count, items, basis).")
        deductions = [entry for entry in deductions
                      if isinstance(entry, dict)] if isinstance(
                          deductions, list) else []
    if number in MODEL_SECTION_IDS:      # a tuple: an unhashable id is no crash
        allowed = ", ".join(rule.code for rule in rules_for(number))
        for entry in deductions:
            runner = str(entry.get("rule", "")) in runner_codes
            try:
                # One entry at a time, so a single attempt hears about
                # every bad code, not only the first.
                confidence.resolve([entry], number, allow_python=runner)
            except ValueError as exc:
                message = str(exc)
                if not message.startswith(label):
                    message = f"{label}: {message}"
                problems.append(f"{message} Use one of: {allowed}.")
            items = entry.get("items", "")
            # The word limit is the model's; a runner entry lists every
            # token it found missing.
            if (not runner and isinstance(items, str)
                    and len(items.split()) > MAX_DEDUCTION_WORDS):
                problems.append(
                    f"{label} deduction {entry.get('rule')}: items must be at "
                    f"most {MAX_DEDUCTION_WORDS} words")
    shown = answer.get("shown")
    if shown is not None:
        if number not in SHOWN_SECTIONS:
            problems.append(
                f"{label} has 'shown', which only sections "
                f"{', '.join(map(str, SHOWN_SECTIONS[:-1]))} and "
                f"{SHOWN_SECTIONS[-1]} may carry; set it to null.")
        found = shown.get("found") if isinstance(shown, dict) else None
        kept = shown.get("shown") if isinstance(shown, dict) else None
        if (type(found) is not int or type(kept) is not int
                or not found >= kept >= 1):
            problems.append(
                f"{label} 'shown' must be {{\"found\": <n>, \"shown\": <m>}} "
                f"with whole numbers and found >= shown >= 1, or null.")
    return problems


def check_analysis(analysis: dict, corpus: dict | None = None,
                   runner_codes=()) -> list:
    """Problems with an analysis (the model's output, or a stored checkpoint
    when `runner_codes` names the runner codes it may already carry).
    Sections 1-11 are required; a Source Material answer is ignored."""
    problems = []
    corpus_files = None
    if isinstance(corpus, dict):
        corpus_files = [f for f in (corpus.get("filesContents")
                                    or corpus.get("files") or [])
                        if isinstance(f, dict)]
    shaped = analysis
    if isinstance(analysis, dict) and isinstance(analysis.get("answers"), list):
        shaped = strip_python_sections(dict(analysis))
    try:
        AnalysisResult.model_validate(shaped)
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
    answers = [a for a in answers if isinstance(a, dict)
               and a.get("id") not in PYTHON_SECTION_IDS]
    ids = [a.get("id") for a in answers]

    missing = [i for i in MODEL_SECTION_IDS if i not in ids]
    if missing:
        problems.append("Missing section(s): "
                        + ", ".join(str(i) for i in missing))
    unknown = [i for i in ids if i not in MODEL_SECTION_IDS]
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
        problems.extend(_check_deductions(answer, label, runner_codes))
        if corpus_files is not None:
            problems.extend(check_sources(
                answer.get("sources") or [], corpus_files, label,
                require=not answer.get("not_found")))
    problems += _check_opportunity(
        analysis.get("opportunity") if isinstance(analysis, dict) else None)
    return problems


# ----------------------------------------------------------- faithfulness
# What an extracted section copies from the documents must occur in them.
# Rows and lines tagged (inferred) are exempt: the model declares those (G3).
STANDARD_RE = re.compile(
    r"\b(ISO|IEC|DIN|EN|VDA|SAE|GB(?:/T)?|GMW|VW|MBN|TL|ASTM|JIS|UN(?:ECE)?|ECE)"
    r"\s?[-\s]?[0-9][0-9A-Za-z.\-/]*(?::\d{2,4})?")
# A version written right after a designation ("VW 80000 v2.1").
VERSION_RE = re.compile(r"[vV]?\d+\.\d+(?:\.\d+)?\b")
_NEXT_VERSION_RE = re.compile(r"[ \t]*[,(]?[ \t]*(?:[Vv]ersion[ \t]+)?("
                              + VERSION_RE.pattern + ")")
# A single-letter unit followed by a hyphen is a word ("2 A-Samples").
_UNITS = r"(?:kW|Nm|rpm|°C|bar|mm|kg|g/km|km|Hz|ms|%|(?:K|h|V|A|l|L|s)(?!-))"
QUANTITY_RE = re.compile(r"(\d[\d.,]*)(\s?)(" + _UNITS + r")(?![A-Za-z])")
DELIVERABLE_RE = re.compile(r"\b(?:D|WP|D-)\d{1,3}\b")
# Separators between the two ends of a date range in a timing cell.
_RANGE_SPLIT_RE = re.compile(r"\s+(?:–|—|-|to|bis)\s+|\s*[–—]\s*")
INFERRED_TAG = "(inferred)"

# Owner cells of the Scope of Work matrix (lower case), shared by the
# analysis-time gate and the deck evaluation (C4). "joint" marks a task the
# RFQ gives two parties at once; a blank or dash means nobody in that phase.
OWNER_VALUES = frozenset({"avl", "supplier", "joint", "customer", "", "—", "-"})
# Matrix columns that name stages rather than owners.
STAGE_HEADERS = frozenset({"phase", "phases", "stage", "development stage",
                           "development phase", "dev stage",
                           "development stages"})


def owner_allowed(cell, customer_short="") -> bool:
    """True if `cell` is an owner value (the customer's short name included)."""
    value = str(cell).strip().lower()
    return value in OWNER_VALUES or (
        bool(str(customer_short).strip())
        and value == str(customer_short).strip().lower())


def owner_columns(columns) -> list:
    """Indexes of the matrix columns that hold owner values."""
    return [i for i in range(1, len(columns))
            if str(columns[i]).strip().lower() not in STAGE_HEADERS]


def _cells(line: str) -> list:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _tables(text: str) -> list:
    """The pipe tables of a markdown answer as (header cells, [(cells,
    line), ...]) with the separator row removed."""
    tables, block = [], []
    for line in str(text).splitlines() + [""]:
        if line.strip().startswith("|"):
            block.append(line)
            continue
        if len(block) >= 2 and all(re.fullmatch(r":?-+:?", cell)
                                   for cell in _cells(block[1])):
            tables.append((_cells(block[0]),
                           [(_cells(row), row) for row in block[2:]]))
        block = []
    return tables


def _inferred(line: str) -> bool:
    return INFERRED_TAG in str(line).lower()


def _pattern(token: str, case: bool = False):
    """A regex that finds `token` in the corpus: any whitespace run where
    the token has one, and no letter or digit glued on at either end."""
    body = r"\s+".join(re.escape(part) for part in token.split())
    if token[:1].isalnum():
        body = r"(?<![0-9A-Za-z])" + body
    if token[-1:].isalnum():
        body += r"(?![0-9A-Za-z])"
    return re.compile(body, 0 if case else re.IGNORECASE)


def _occurs(token: str, corpus_text: str, case: bool = False) -> bool:
    return bool(token.strip()) and bool(
        _pattern(token, case).search(corpus_text))


def _date_occurs(token: str, corpus_text: str) -> bool:
    """Like _occurs, but a letter run and the digits after it may be written
    apart or together ("KW 38/2026" = "KW38/2026")."""
    token = re.sub(r"(?<=[A-Za-z])\s+(?=\d)", "", token.strip())
    if not token:
        return False
    body = r"\s+".join(
        r"\s*".join(re.escape(piece)
                    for piece in re.split(r"(?<=[A-Za-z])(?=\d)", part))
        for part in token.split())
    if token[:1].isalnum():
        body = r"(?<![0-9A-Za-z])" + body
    if token[-1:].isalnum():
        body += r"(?![0-9A-Za-z])"
    return bool(re.search(body, corpus_text, re.IGNORECASE))


def _designation_occurs(token: str, prefix: str, corpus_text: str) -> bool:
    """Case-sensitive; "ISO 26262", "ISO-26262" and "ISO26262" are one
    designation."""
    rest = token[len(prefix):].lstrip(" -")
    body = (r"(?<![A-Za-z0-9])" + re.escape(prefix) + r"[\s\-]*"
            + r"\s+".join(re.escape(part) for part in rest.split())
            + r"(?![0-9A-Za-z])")
    return bool(re.search(body, corpus_text))


def _number_forms(number: str) -> set:
    """The spellings of one number across conventions: as written, with "."
    and "," swapped ("3.5" / "3,5"), and without thousands separators
    ("1,500" / "1.500" / "1500")."""
    swapped = number.translate(str.maketrans(".,", ",."))
    forms = {number, swapped}
    return forms | {re.sub(r"[.,](?=\d{3}(?!\d))", "", form) for form in forms}


# How far from a bare number a unit in its own table cell may sit.
_UNIT_WINDOW = 60


def _unit_beside(unit: str, before: str, after: str) -> bool:
    """`unit` as a token of its own in the text just before or after a bare
    number on the same line (a table's unit cell: "| Displacement | L |
    2.996 |"), not attached to another number ("| 20 | 220 kW |")."""
    flags = re.IGNORECASE if len(unit) > 1 or unit in "lL" else 0
    pattern = re.compile(r"(?<![0-9A-Za-z])" + re.escape(unit)
                         + r"(?![0-9A-Za-z])", flags)
    return any(not re.search(r"\d\s?$", text[:found.start()])
               for text in (before, after) for found in pattern.finditer(text))


def _quantity_occurs(number: str, unit: str, corpus_text: str) -> bool:
    """`number` `unit` in the corpus, in any of the number's spellings:
    written together, or the bare number with the unit on the same line
    within _UNIT_WINDOW characters (number and unit in separate cells)."""
    unit_re = re.escape(unit) + (r"(?!-)" if len(unit) == 1 else "")
    body = r"(?<![\d.,])(\d[\d.,]*)\s?" + unit_re + r"(?![A-Za-z])"
    forms = _number_forms(number)
    if any(_number_forms(found.group(1).rstrip(".,")) & forms
           for found in re.finditer(body, corpus_text, re.IGNORECASE)):
        return True
    for found in re.finditer(r"(?<![\d.,])\d[\d.,]*", corpus_text):
        if not _number_forms(found.group(0).rstrip(".,")) & forms:
            continue
        start = corpus_text.rfind("\n", 0, found.start()) + 1
        end = corpus_text.find("\n", found.end())
        end = len(corpus_text) if end < 0 else end
        before = corpus_text[max(start, found.start() - _UNIT_WINDOW):found.start()]
        after = corpus_text[found.end():min(end, found.end() + _UNIT_WINDOW)]
        if _unit_beside(unit, before, after):
            return True
    return False


def _version_occurs(version: str, corpus_text: str) -> bool:
    number = version.lstrip("vV")
    return bool(re.search(r"(?<!\d)(?<!\d\.)" + re.escape(number)
                          + r"(?!\.?\d)", corpus_text))


def _lines(answer: dict) -> list:
    """The answer's lines that are not tagged (inferred)."""
    return [line for line in str(answer.get("answer", "")).splitlines()
            if not _inferred(line)]


def _standards(answer, corpus_text):
    for line in _lines(answer):
        for match in STANDARD_RE.finditer(line):
            # "ISO 26262-compliant" names ISO 26262; part numbers ("-1") stay.
            token = re.sub(r"(?:-[A-Za-z]{2,})+$", "",
                           match.group(0).rstrip(".-/")).rstrip(".-/")
            if not _designation_occurs(token, match.group(1), corpus_text):
                yield token, (f"names '{token}', which does not occur in the "
                              f"RFQ documents; copy the designation as "
                              f"written or remove it.")
            version = _NEXT_VERSION_RE.match(line, match.end())
            if version and not _version_occurs(version.group(1), corpus_text):
                found = version.group(1)
                yield found, (f"gives '{token}' the version '{found}', which "
                              f"does not occur in the RFQ documents; copy the "
                              f"version as written or remove it.")


def _quantities(answer, corpus_text):
    for line in _lines(answer):
        for match in QUANTITY_RE.finditer(line):
            number, space, unit = match.groups()
            number = number.rstrip(".,")
            token = f"{number}{space}{unit}"
            if not _quantity_occurs(number, unit, corpus_text):
                yield token, (f"states '{token}', which does not occur in the "
                              f"RFQ documents; copy the value and unit as "
                              f"written, tag the row (inferred) if you "
                              f"derived it, or remove it.")


def _timing_cells(answer, corpus_text):
    from .dates import time_pos
    for header, rows in _tables(answer.get("answer", "")):
        names = [cell.lower() for cell in header]
        if "target timing" not in names:
            continue
        index = names.index("target timing")
        for cells, line in rows:
            if _inferred(line) or index >= len(cells):
                continue
            cell = cells[index]
            if time_pos(cell) is None or _date_occurs(cell, corpus_text):
                continue
            # Not as one string: each date of a range (remarks in
            # brackets dropped) must occur on its own.
            parts = [re.sub(r"\([^)]*\)", "", part).strip()
                     for part in _RANGE_SPLIT_RE.split(cell)]
            parts = [part for part in parts if time_pos(part) is not None]
            missing = ([part for part in parts
                        if not _date_occurs(part, corpus_text)]
                       if parts else [cell])
            for part in missing:
                yield part, (f"gives the target timing '{part}', which does "
                             f"not occur in the RFQ documents; copy the date "
                             f"as written, or tag the row (inferred) if you "
                             f"derived it.")


def _phase_names(answer, corpus_text):
    corpus_norm = _norm(corpus_text)
    for _header, rows in _tables(answer.get("answer", "")):
        for cells, line in rows:
            name = cells[0].strip("* ").strip() if cells else ""
            if not name or _inferred(line) or _phase_ok(name, corpus_norm):
                continue
            yield name, (f"names the phase '{name}', which does not occur in "
                         f"the RFQ documents; use the phase name the RFQ "
                         f"gives, or tag the row (inferred) if the RFQ names "
                         f"no phases.")


def _owner_cells(answer, customer_short):
    """Owner cells outside the owner set. Not a corpus miss: an "(inferred)"
    tag exempts nothing here, and the last attempt still blocks on them."""
    owners = ", ".join(["AVL", "Supplier"]
                       + ([customer_short] if customer_short else [])
                       + ["Customer", "Joint", "—"])
    for header, rows in _tables(answer.get("answer", "")):
        columns = owner_columns(header)
        for cells, _line in rows:
            for i in columns:
                if i < len(cells) and not owner_allowed(cells[i], customer_short):
                    yield cells[i], (
                        f"row '{cells[0]}' has the owner '{cells[i]}'; every "
                        f"owner cell must be one of {owners}.")


def _deliverable_ids(answer, corpus_text):
    for line in _lines(answer):
        for match in DELIVERABLE_RE.finditer(line):
            token = match.group(0)
            if not _occurs(token, corpus_text, case=True):
                yield token, (f"names the deliverable '{token}', which does "
                              f"not occur in the RFQ documents; copy the "
                              f"deliverable id as written or remove it.")


def _party_names(answer, corpus_text, customer_short=""):
    """Party names other than AVL and the customer (whose row may carry the
    customer's short form, opportunity.customer_short)."""
    for header, rows in _tables(answer.get("answer", "")):
        if not header or header[0].lower() != "party":
            continue
        for cells, line in rows:
            name = cells[0].strip("* ").strip() if cells else ""
            kind = cells[1].strip().lower() if len(cells) > 1 else ""
            if (not name or _inferred(line) or kind in ("avl", "customer")
                    or name.split()[0].lower() == "avl"
                    or (customer_short
                        and name.lower() == customer_short.lower())):
                continue
            if not _occurs(name, corpus_text):
                yield name, (f"names the party '{name}', which does not occur "
                             f"in the RFQ documents; copy the name as "
                             f"written, or tag the row (inferred).")


def _corpus_text(corpus) -> str:
    if isinstance(corpus, str):
        return corpus
    if not isinstance(corpus, dict):
        return ""
    files = corpus.get("filesContents") or corpus.get("files") or []
    return "\n".join(str(f.get("extracted_text") or "")
                     for f in files if isinstance(f, dict))


def _faithfulness(analysis, corpus) -> list:
    """(section id, token, problem, miss) for every item an extracted
    section states that the corpus does not hold (miss True), and every
    owner cell outside the owner set (miss False: a fault of form, not a
    corpus miss)."""
    if not isinstance(analysis, dict) or not isinstance(
            analysis.get("answers"), list):
        return []
    text = _corpus_text(corpus)
    info = analysis.get("opportunity")
    customer_short = str((info or {}).get("customer_short") or "").strip() \
        if isinstance(info, dict) else ""
    checks = {
        TECHNICAL: lambda a: _quantities(a, text),
        COLLABORATION: lambda a: _party_names(a, text, customer_short),
        PHASES: lambda a: _phase_names(a, text),
        DELIVERABLES: lambda a: _deliverable_ids(a, text),
        TIMING: lambda a: _timing_cells(a, text),
        STANDARDS: lambda a: _standards(a, text),
    }
    found, seen = [], set()
    for answer in analysis["answers"]:
        if not isinstance(answer, dict):
            continue
        number = answer.get("id")
        if type(number) is not int:
            continue
        results = [(token, message, True) for token, message in
                   (checks[number](answer) if number in checks else ())]
        if number == SCOPE:
            results += [(token, message, False) for token, message
                        in _owner_cells(answer, customer_short)]
        for token, message, miss in results:
            if (number, token) not in seen:
                seen.add((number, token))
                found.append((number, token, f"Section {number} {message}",
                              miss))
    return found


def check_faithfulness(analysis, corpus) -> list:
    """Problems for the items extracted sections state that the RFQ
    documents do not: standard designations and their versions (10),
    target timing dates (9), number and unit pairs (3), phase names (6),
    deliverable ids (8) and party names (5); and for owner cells outside
    the owner set (7)."""
    return [problem for _n, _t, problem, _miss in _faithfulness(analysis, corpus)]


def check_owner_cells(analysis) -> list:
    """The owner-cell problems alone: they are never corpus misses, so the
    last attempt still blocks on them."""
    return [problem for _n, _t, problem, miss in _faithfulness(analysis, "")
            if not miss]


def faithfulness_misses(analysis, corpus) -> dict:
    """{section id: [token, ...]} of the corpus misses check_faithfulness
    reports (owner cells excluded), in answer order, for the runner's V3
    deductions."""
    misses = {}
    for number, token, _problem, miss in _faithfulness(analysis, corpus):
        if miss:
            misses.setdefault(number, []).append(token)
    return misses


# Dates written in free text (a follow-up answer): a full day, a month or a
# quarter, half-year or calendar week with its year. A bare year is not
# looked for: "2026" is too often part of something else.
_MONTH = (r"(?:january|february|march|april|may|june|july|august|september|"
          r"october|november|december|januar|februar|märz|maerz|juni|juli|"
          r"oktober|dezember|jan|feb|mar|mrz|apr|mai|jun|jul|aug|sept|sep|"
          r"oct|okt|nov|dec|dez)\.?")
FREE_DATE_RE = re.compile(
    r"(?<![\w.])(?:"
    r"20\d\d[/.-]\d{1,2}(?:[/.-]\d{1,2})?"
    r"|\d{1,2}[/.-]\d{1,2}[/.-]20\d\d"
    r"|\d{1,2}(?:st|nd|rd|th)?\.?\s+" + _MONTH + r",?\s+20\d\d"
    r"|" + _MONTH + r"\s+\d{1,2}(?:st|nd|rd|th)?,?\s+20\d\d"
    r"|" + _MONTH + r",?\s+20\d\d"
    r"|[QH][1-4]\s*/?\s*20\d\d"
    r"|[KC]W\s*\d{1,2}\s*[/.]?\s*20\d\d"
    r")(?![\w/])", re.IGNORECASE)


def _free_dates(answer, corpus_text):
    from .dates import time_pos
    for line in _lines(answer):
        for match in FREE_DATE_RE.finditer(line):
            token = match.group(0)
            if time_pos(token) is None or _date_occurs(token, corpus_text):
                continue
            yield token, (f"gives the date '{token}', which does not occur in "
                          f"the RFQ documents; copy the date as written, or "
                          f"tag the line (inferred) if you derived it.")


def _text_faithfulness(text, corpus, label):
    """(token, problem) for every date, standard designation (and version)
    and number+unit pair in free text that the corpus does not hold, each
    token once, in check order. Lines tagged (inferred) are exempt."""
    corpus_text = _corpus_text(corpus)
    answer = {"answer": str(text or "")}
    found, seen = [], set()
    for check in (_standards, _free_dates, _quantities):
        for token, message in check(answer, corpus_text):
            if token not in seen:
                seen.add(token)
                found.append((token, f"{label} {message}"))
    return found


def check_text_faithfulness(text, corpus, label="Follow-up") -> list:
    """The analysis gate's date, standard and number+unit checks on free
    text (an extracted follow-up answer): one problem per token the RFQ
    documents do not hold, starting with `label`. `corpus` is corpus.json
    or its text."""
    return [problem for _token, problem in _text_faithfulness(text, corpus, label)]


def text_faithfulness_misses(text, corpus) -> list:
    """The tokens check_text_faithfulness reports, for a V3 deduction."""
    return [token for token, _problem in _text_faithfulness(text, corpus, "")]


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


# The first line of a rated section's notes (rfq/confidence.py notes()).
NOTES_HEADER_RE = re.compile(r"Confidence (?:10|[1-9])/10 \((?:High|Medium|Low)\)")

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

    # C1 every section the analysis answers is present (Source Material is
    # the runner's, so the analysis may come without it)
    missing = [i for i in MODEL_SECTION_IDS if i not in answers]
    (fails if missing else oks).append(
        f"C1 sections 1-{len(MODEL_SECTION_IDS)} present"
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
    # "(inferred)" stays where the renderer draws it in amber (table cells,
    # panel items, bullet text); planning.tagged_strings applies the
    # sanitizer's own rule.
    from .planning import tagged_strings
    tagged = [s[:60] for s in tagged_strings(visible_plan)]
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
            abbr = sl.get("customerAbbr", "customer")
            for row in sl.get("rows", []):
                for i in owner_columns(sl.get("columns", [])):
                    if i < len(row) and not owner_allowed(row[i], abbr):
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

    # C8 confidence explained in the slide notes (client, 2026-10-07): every
    # rated section's notes open with its score and band.
    unexplained = [q.get("titleEn") for q in plan.get("questions", [])
                   if q.get("confidence") and not NOTES_HEADER_RE.match(
                       str(q.get("confidenceNotes") or ""))]
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
