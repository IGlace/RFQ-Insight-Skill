"""The slide plan from the answers' markdown (typed_from_markdown, CONTRACT
§9), the slide worker's input, and the deterministic plan guards."""

import json
import os
import re
import sys

from .schema import (APPLICATION, COLLABORATION, DELIVERABLES, DESCRIPTION,
                     OPPORTUNITY, PHASES, RISKS, SCOPE, SECTION_IDS,
                     SECTION_SHAPES, SOURCES, STANDARDS, TECHNICAL, TIMING,
                     TITLES)

INFERRED = "(inferred)"


def _typed_table(columns: list[str], rows: list[list[str]]) -> str:
    if (not columns or any(len(row) != len(columns) for row in rows)
            or any("|" in cell or "\n" in cell or "\r" in cell
                   for row in [columns, *rows] for cell in row)):
        raise ValueError("Typed tables require unambiguous complete cells.")
    return "\n".join(["| " + " | ".join(columns) + " |",
                      "| " + " | ".join("---" for _ in columns) + " |"]
                     + ["| " + " | ".join(row) + " |" for row in rows])


def _typed_line(text_: str) -> str:
    # Multiline values could inject extra canonical list items or metadata
    # blocks without matching their actual typed item count.
    if len(text_.splitlines()) > 1 or "\n" in text_ or "\r" in text_:
        raise ValueError("Typed list and metadata values must be single lines.")
    return text_


def _typed_answer_block(slide: dict) -> str:
    """The canonical markdown of one typed slide (CONTRACT §9): the inverse
    of `typed_from_markdown`, so a parsed slide written back and parsed
    again is the same slide (the round-trip rule, tested per section).

    Titles are app-owned. What a slide takes from the context rather than
    the answer (an ownership slide's customerAbbr, Timing's chart, which is
    the table's dated rows plus the section-6 spans) writes no text of its
    own; a phases slide writes the section-6 table, its "Referenced only"
    callout as referenced-only rows."""
    layout = slide["layout"]
    callout = slide.get("callout") or {}
    if layout in ("table", "ownership"):
        if callout:
            raise ValueError("The renderer cannot display this layout's callout.")
        return _typed_table(slide["columns"], slide["rows"])
    if layout == "prose":
        return "\n\n".join(slide["body"].split("\n"))
    if layout == "bullets":
        return "\n".join(
            "- " + _typed_line(b["text"]) + (" (inferred)" if b.get("inferred")
                                    and not re.search(r"\(inferred\)", b["text"], re.I)
                                    else "") for b in slide["bullets"])
    if layout == "panel":
        return ("## " + _typed_line(slide["heading"]) + "\n"
                + "\n".join("- " + _typed_line(item) for item in slide["items"]))
    if layout == "phases":
        rows = [[phase["name"], phase.get("desc", ""), "in scope",
                 {True: "yes", False: "no"}.get(phase.get("hw"), ""), ""]
                for phase in slide["phases"]]
        if callout:
            if callout.get("tag") != REFERENCED_TAG:
                raise ValueError("A phases callout holds the referenced-only phases.")
            for entry in _typed_line(callout["text"]).split("; "):
                name, _sep, why = entry.partition(": ")
                rows.append([name, "", "referenced only" + (": " + why if why else ""),
                             "", ""])
        return _typed_table(list(PHASE_COLUMNS), rows)
    if layout == "collab":
        blocks = ["Hub: " + _typed_line(slide["hub"])] if slide.get("hub") else []
        blocks.append(_typed_table(list(PARTY_COLUMNS), [
            [party["name"], party.get("type", ""), party.get("role", "")]
            for party in slide["parties"]]))
        if callout:
            if callout.get("tag") != DEPENDENCIES_TAG:
                raise ValueError("A collab callout holds the dependencies.")
            blocks.append(_typed_line(callout["text"]))
        return "\n\n".join(blocks)
    if layout in ("gantt", "timeline"):
        return ""
    raise ValueError("Unsupported typed presentation layout.")


# ------------------------------------------------- markdown -> typed slides
# The fixed headers of CONTRACT §9 (compared case-insensitively).
PARTY_COLUMNS = ("Party", "Type", "Role")
PHASE_COLUMNS = ("Phase", "Definition", "Scope", "Hardware milestone", "Span")
TIMING_COLUMNS = ("Milestone", "Target timing", "Phase / Task")
RISK_HEADINGS = ("Project Risks", "Document Risks")
PARTY_TYPES = ("customer", "avl", "supplier", "third")
DEPENDENCIES_TAG = "Dependencies"
REFERENCED_TAG = "Referenced only"
# Section 7's single column when section 6 has no in-scope phase.
ALL_PHASES = "All phases"
GANTT_STEPS = 14            # later dated rows still appear in the table
GANTT_BARS = 8
SPLIT_WORDS = 300           # a longer Description takes two prose slides
TABLE_SECTIONS = (TECHNICAL, APPLICATION, DELIVERABLES, STANDARDS, SOURCES)
# A not_found answer is one sentence (prompt v14, 3.5); these sections
# show it as a one-cell table under the section title.
SENTENCE_SECTIONS = (TECHNICAL, APPLICATION, PHASES, DELIVERABLES, STANDARDS)


class _Unparsable(ValueError):
    """The answer does not have its section's canonical shape."""


def _callout_fits(text_: str) -> bool:
    """The diagram layouts' fixed 0.7-inch callout band holds 3 lines."""
    from .renderer import _wrap_count, PAGE_W, M
    return _wrap_count(text_, PAGE_W - 2 * M - 1.85, 11) <= 3


def _same(header, expected) -> bool:
    return [cell.casefold() for cell in header] == [c.casefold() for c in expected]


def _segments(text_: str) -> list:
    """The answer as ("table", header, rows) and ("line", text) segments in
    order. A run of pipe lines that is not exactly one well-formed table
    (no separator, ragged rows, a second separator) is unparsable."""
    from .validation import _tables

    segments, block = [], []

    def flush():
        if not block:
            return
        tables = _tables("\n".join(block))
        if len(tables) != 1:
            raise _Unparsable("a pipe table without its separator row")
        header, rows = tables[0]
        cells = [row for row, _line in rows]
        if any(len(row) != len(header) for row in cells):
            raise _Unparsable("a table row with the wrong number of cells")
        if any(all(re.fullmatch(r":?-+:?", cell) for cell in row) for row in cells):
            raise _Unparsable("two tables without a blank line between them")
        segments.append(("table", header, cells))
        block.clear()

    for line in str(text_).splitlines():
        if line.strip().startswith("|"):
            block.append(line)
            continue
        flush()
        segments.append(("line", " ".join(line.split())))
    flush()
    return segments


def _drop(actions: list, section: int, line: str, where: str = "the table") -> None:
    actions.append(f"Section {section}: dropped text outside {where}: {line[:60]}")


def _one_table(segments: list, section: int, actions: list):
    tables = [segment for segment in segments if segment[0] == "table"]
    if len(tables) != 1:
        raise _Unparsable("exactly one table is required")
    for segment in segments:
        if segment[0] == "line" and segment[1]:
            _drop(actions, section, segment[1])
    return tables[0][1], tables[0][2]


def _sentence_slide(segments: list, section: int):
    """A not_found answer's one sentence as a one-cell table under the
    section title (that table, written back, parses to the same slide), or
    None when the answer holds a table of its own (parsed as usual)."""
    title = TITLES[section][0]
    tables = [segment for segment in segments if segment[0] == "table"]
    lines = [segment[1] for segment in segments if segment[0] == "line" and segment[1]]
    if not tables and lines:
        return {"layout": "table", "columns": [title], "rows": [[" ".join(lines)]]}
    if (len(tables) == 1 and not lines and tables[0][1] == [title]
            and len(tables[0][2]) == 1):
        return {"layout": "table", "columns": [title], "rows": tables[0][2]}
    return None


def _paragraphs(lines) -> list[str]:
    paragraphs, current = [], []
    for line in lines:
        if line:
            current.append(line)
        elif current:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs


def _description(text_: str, actions: list) -> list[dict]:
    lines = []
    for raw in str(text_).splitlines():
        line = " ".join(raw.split())
        if re.match(r"(#|[-*+] |\d+[.)] |\|)", line):
            _drop(actions, DESCRIPTION, line, "the paragraphs")
            line = ""
        lines.append(line)
    paragraphs = _paragraphs(lines)
    if not paragraphs:
        raise _Unparsable("no paragraph")
    counts = [len(paragraph.split()) for paragraph in paragraphs]
    total = sum(counts)
    if total <= SPLIT_WORDS or len(paragraphs) < 2:
        return [{"layout": "prose", "body": "\n".join(paragraphs)}]
    # The paragraph boundary nearest the middle (the earlier one on a tie).
    cut = min(range(1, len(paragraphs)),
              key=lambda k: abs(2 * sum(counts[:k]) - total))
    return [{"layout": "prose", "body": "\n".join(paragraphs[:cut])},
            {"layout": "prose", "body": "\n".join(paragraphs[cut:])}]


def _collaboration(segments: list, context: dict, actions: list) -> list[dict]:
    index = [i for i, segment in enumerate(segments) if segment[0] == "table"]
    if len(index) != 1:
        raise _Unparsable("exactly one party table is required")
    _kind, header, rows = segments[index[0]]
    if not _same(header, PARTY_COLUMNS):
        raise _Unparsable("the party table header")
    hub = None
    for _kind, line in segments[:index[0]]:
        match = re.fullmatch(r"Hub:\s*(.+)", line, re.IGNORECASE)
        if match and hub is None:
            hub = match.group(1).strip()
        elif line:
            _drop(actions, COLLABORATION, line)
    hub = hub or context.get("customer_short") or None
    parties = []
    for name, kind, role in rows:
        if kind.casefold() not in PARTY_TYPES:
            raise _Unparsable(f"the party type {kind!r}")
        parties.append({"name": name, "role": role, "type": kind.casefold(),
                        "dashed": any(INFERRED in cell.lower()
                                      for cell in (name, kind, role))})
    slide = {"layout": "collab", "parties": parties}
    if hub:
        slide["hub"] = hub
    dependencies = " ".join(_paragraphs(
        segment[1] for segment in segments[index[0] + 1:]))
    if dependencies:
        if _callout_fits(dependencies):
            slide["callout"] = {"tag": DEPENDENCIES_TAG, "text": dependencies}
        else:
            actions.append(f"Section {COLLABORATION}: dropped the dependencies, "
                           f"too long for the callout: {dependencies[:60]}")
    return [slide]


def _span(cell: str):
    """(start, end) of a Span cell when both ends parse to a calendar
    position and the end follows the start, else None. A derived span's
    " (inferred)" never reaches the dates."""
    from .dates import time_pos
    from .validation import _RANGE_SPLIT_RE

    parts = [part.strip() for part in
             _RANGE_SPLIT_RE.split(clean_evidence_tags(cell))]
    if len(parts) != 2 or not all(parts):
        return None
    start, end = time_pos(parts[0]), time_pos(parts[1], end=True)
    if start is None or end is None or end <= start:
        return None
    return parts[0], parts[1]


def _phases(segments: list, context: dict, actions: list) -> list[dict]:
    header, rows = _one_table(segments, PHASES, actions)
    if not _same(header, PHASE_COLUMNS):
        raise _Unparsable("the phase table header")
    phases, referenced, bars = [], [], []
    for name, definition, scope, hardware, span in rows:
        kind, _sep, why = scope.partition(":")
        kind = clean_evidence_tags(kind).casefold()
        if kind == "in scope":
            phase = {"name": name, "desc": definition}
            hw = {"yes": True, "no": False}.get(
                clean_evidence_tags(hardware).casefold())
            if hw is not None:
                phase["hw"] = hw
            phases.append(phase)
            if (ends := _span(span)) is not None:
                bars.append({"name": clean_evidence_tags(name),
                             "start": ends[0], "end": ends[1]})
        elif kind == "referenced only":
            referenced.append(name + (": " + why.strip() if why.strip() else ""))
        else:
            raise _Unparsable(f"the phase scope {scope!r}")
    # The section-9 gantt draws these bars (CONTRACT §9).
    context["spans"] = bars
    if not phases:
        # Nothing in scope: the whole table, and section 7 has one column.
        return [{"layout": "table", "columns": header, "rows": rows}]
    slide = {"layout": "phases", "phases": phases}
    if referenced:
        text_ = "; ".join(referenced)
        if _callout_fits(text_):
            slide["callout"] = {"tag": REFERENCED_TAG, "text": text_}
        else:
            actions.append(f"Section {PHASES}: dropped the referenced-only "
                           f"phases, too long for the callout: {text_[:60]}")
    return [slide]


def _timing(segments: list, context: dict, actions: list) -> list[dict]:
    from .dates import time_pos

    header, rows = _one_table(segments, TIMING, actions)
    if not _same(header, TIMING_COLUMNS):
        raise _Unparsable("the timing table header")

    def steps(selected):
        return [{"label": label, "date": date, "desc": desc}
                for label, date, desc in selected]

    dated = [row for row in rows if time_pos(row[1]) is not None]
    if len(dated) >= 2:
        chart = {"layout": "gantt", "steps": steps(dated[:GANTT_STEPS])}
        bars = context.get("spans") or []
        if 0 < len(bars) <= GANTT_BARS:
            chart["bars"] = [dict(bar) for bar in bars]
        elif context.get("project_name"):
            chart["barLabel"] = context["project_name"]
    else:
        chart = {"layout": "timeline", "steps": steps(rows)}
    return [chart, {"layout": "table", "columns": list(TIMING_COLUMNS), "rows": rows}]


def _risks(text_: str, actions: list) -> list[dict]:
    groups, current = {}, None
    for raw in str(text_).splitlines():
        line = " ".join(raw.split())
        if not line:
            continue
        heading = re.fullmatch(r"##\s*(.+)", line)
        if heading:
            name = next((h for h in RISK_HEADINGS
                         if h.casefold() == heading.group(1).strip().casefold()), None)
            if name is None or name in groups:
                raise _Unparsable(f"the risk heading {line!r}")
            current = groups[name] = []
        elif line.startswith("- ") and current is not None:
            current.append(line[2:].strip())
        else:
            _drop(actions, RISKS, line, "the risk lists")
    if list(groups) != list(RISK_HEADINGS) or not all(groups.values()):
        raise _Unparsable("both risk groups, in order, with an item each")
    return [{"layout": "panel", "heading": name, "items": items}
            for name, items in groups.items()]


def typed_from_markdown(answer: dict, section: int, context: dict) -> list[dict] | None:
    """The typed slides of one section, parsed from its answer's canonical
    markdown (CONTRACT §9), or None when the answer does not have its
    section's shape (the slide worker then plans the whole deck).

    `context` carries `customer_short` (section 7's customerAbbr, section
    5's hub fallback), `project_name` (the gantt's project bar) and `spans`
    (the section-6 phase bars, which parsing section 6 sets). Lines outside
    the shape are dropped and recorded in `context["actions"]` (only when
    the section parses). Titles are stamped by the caller. Section 1 is
    never parsed: its slide is the application's placeholder."""
    if section == OPPORTUNITY:
        return [{"layout": "opportunity"}]
    text_ = answer.get("answer") if isinstance(answer, dict) else None
    if not isinstance(text_, str) or not text_.strip():
        return None
    actions = []
    try:
        if section == DESCRIPTION:
            slides = _description(text_, actions)
        elif section == RISKS:
            slides = _risks(text_, actions)
        else:
            segments = _segments(text_)
            sentence = (_sentence_slide(segments, section)
                        if answer.get("not_found") is True
                        and section in SENTENCE_SECTIONS else None)
            if sentence is not None:
                slides = [sentence]
            elif section in TABLE_SECTIONS:
                header, rows = _one_table(segments, section, actions)
                slides = [{"layout": "table", "columns": header, "rows": rows}]
            elif section == COLLABORATION:
                slides = _collaboration(segments, context, actions)
            elif section == PHASES:
                slides = _phases(segments, context, actions)
            elif section == SCOPE:
                header, rows = _one_table(segments, section, actions)
                slides = [{"layout": "ownership",
                           "customerAbbr": context.get("customer_short") or "Customer",
                           "columns": header, "rows": rows}]
            elif section == TIMING:
                slides = _timing(segments, context, actions)
            else:
                return None
    except _Unparsable:
        return None
    context.setdefault("actions", []).extend(actions)
    return slides


def _phase_columns(slide: dict) -> list[str]:
    """The in-scope phase names section 7's header must repeat."""
    if slide["layout"] == "phases":
        return [clean_evidence_tags(phase["name"]) for phase in slide["phases"]]
    columns = [column.casefold() for column in slide["columns"]]
    if "scope" not in columns:
        return []
    scope = columns.index("scope")
    return [clean_evidence_tags(row[0]) for row in slide["rows"]
            if row[scope].casefold().startswith("in scope")]


def _typed_shapes(questions: list[dict]) -> list[int]:
    """The sections whose slides break a canonical shape or a cross-section
    fact the fast path relies on (an empty list: none)."""
    from .dates import time_pos

    failed = set()
    for question in questions:
        for slide in question["slides"]:
            co = slide.get("callout")
            if co and not _callout_fits(co["text"]):
                failed.add(question["number"])  # the 0.7-inch band cannot hold it

    by_id = {question["number"]: question["slides"] for question in questions}
    def layouts(section):
        return [slide["layout"] for slide in by_id[section]]
    # The one section-shape contract, shared with validation.check_plan so the
    # fast path and the slide worker can never be held to different rules.
    for section, shapes in SECTION_SHAPES.items():
        if tuple(layouts(section)) not in shapes:
            failed.add(section)
    if failed & {PHASES, SCOPE, RISKS, TIMING}:
        return sorted(failed)
    phase_names = _phase_columns(by_id[PHASES][0]) or [ALL_PHASES]
    ownership = by_id[SCOPE][0]
    if [clean_evidence_tags(column) for column in ownership["columns"]] \
            != ["Scope of Work", *phase_names]:
        failed.add(SCOPE)
    owners = {"AVL", "Supplier", "Customer", "Joint", "—", "-", "",
              ownership.get("customerAbbr") or "Customer"}
    if any(cell not in owners for row in ownership["rows"] for cell in row[1:]):
        failed.add(SCOPE)
    if ([slide["heading"] for slide in by_id[RISKS]] != list(RISK_HEADINGS)
            or any(not slide["items"] for slide in by_id[RISKS])):
        failed.add(RISKS)
    chart, table = by_id[TIMING]
    rows = table["rows"]
    dated = [row for row in rows if time_pos(row[1]) is not None]
    expected = None
    if table["columns"] != list(TIMING_COLUMNS):
        failed.add(TIMING)
    elif chart["layout"] == "gantt":
        bars = chart.get("bars") or []
        if (len(dated) < 2 or len(bars) > GANTT_BARS
                or (bars and chart.get("barLabel"))):
            failed.add(TIMING)  # L_gantt draws the project label only without bars
        for bar in bars:
            start = time_pos(bar["start"])
            end = time_pos(bar["end"], end=True)
            if start is None or end is None or end <= start:
                failed.add(TIMING)  # L_gantt silently excludes unsupported spans
        expected = dated[:GANTT_STEPS]
    elif len(dated) >= 2:
        failed.add(TIMING)
    else:
        expected = rows
    if expected is not None and [[step["label"], step["date"], step["desc"]]
                                 for step in chart["steps"]] != expected:
        failed.add(TIMING)
    positions = [time_pos(row[1]) for row in dated]
    if positions != sorted(positions):
        failed.add(TIMING)
    return sorted(failed)


def plan_from_answers(corpus: dict, analysis: dict) -> tuple[dict | None, dict]:
    """(plan, record): the whole canonical draft built from the answers'
    markdown (sections 2-12 through `typed_from_markdown`, section 1 the
    opportunity placeholder), or None when a section does not parse or the
    parsed deck breaks a shape check. The record is {"parsed": [ids],
    "unparsable": [ids], "actions": [the sanitizer actions of the parse]}.

    No partial plan exists: one unparsable section sends the whole deck to
    the slide worker. Section 11 is parsed without the application's
    account-risk line (rfq/delivery.py places the current one)."""
    from pydantic import ValidationError
    from .opportunity import without_account_risk
    from .schema import LoosePlanDraft, tighten_plan
    from .validation import check_plan

    record = {"parsed": [], "unparsable": [], "actions": []}
    if not isinstance(corpus, dict) or not isinstance(analysis, dict):
        return None, record
    answers = analysis.get("answers")
    if (not isinstance(answers, list)
            or any(not isinstance(answer, dict) for answer in answers)
            or any(type(answer.get("id")) is not int for answer in answers)
            or [answer["id"] for answer in answers] != list(SECTION_IDS)):
        ids = [a.get("id") for a in answers if isinstance(a, dict)] \
            if isinstance(answers, list) else []
        record["unparsable"] = sorted(set(SECTION_IDS) - set(ids))
        return None, record
    info = analysis.get("opportunity")
    info = info if isinstance(info, dict) else {}
    context = {"customer_short": str(info.get("customer_short") or "").strip(),
               "project_name": str(info.get("project_title")
                                   or corpus.get("projectName") or "").strip(),
               "spans": [], "actions": []}
    questions = []
    for answer in answers:
        number = answer["id"]
        if number == RISKS:
            answer = dict(answer, answer=without_account_risk(answer.get("answer", "")))
        slides = typed_from_markdown(answer, number, context)
        if not slides:
            record["unparsable"].append(number)
            continue
        title_en, title_de = TITLES[number]
        for index, slide in enumerate(slides):
            slide["title"] = (title_en if index == 0 or number == RISKS
                              else title_en + " — " + (
                                  "Milestone Table" if number == TIMING
                                  else f"Part {index + 1}"))
        questions.append({"number": number, "titleEn": title_en,
                          "titleDe": title_de, "slides": slides})
    if record["unparsable"]:
        return None, record
    draft = {"projectName": corpus.get("projectName", ""), "questions": questions}
    problems = check_plan(draft)
    failed = sorted({int(n) for problem in problems
                     for n in re.findall(r"Question (\d+)", problem)}
                    | set(_typed_shapes(questions)))
    if problems or failed:
        record["unparsable"] = failed
        return None, record
    try:
        plan = tighten_plan(
            LoosePlanDraft.model_validate(draft).model_dump(exclude_none=True))
    except ValidationError:
        return None, record
    record["parsed"] = [number for number in SECTION_IDS if number != OPPORTUNITY]
    record["actions"] = context["actions"]
    return plan, record


def deterministic_plan(corpus: dict, analysis: dict) -> dict | None:
    """The canonical draft from the answers' markdown, or None (use the
    slide worker for the entire plan). See `plan_from_answers`."""
    return plan_from_answers(corpus, analysis)[0]


def authoritative_risk_items(analysis: dict) -> list:
    """Section 11's parsed panel items, without the application's own
    account-risk line: these source items stay on the deck even when one
    mentions the Salesforce account for a substantive reason."""
    from .opportunity import without_account_risk

    answer = next((a for a in analysis.get("answers", [])
                   if isinstance(a, dict) and a.get("id") == RISKS), None)
    if answer is None:
        return []
    slides = typed_from_markdown(
        dict(answer, answer=without_account_risk(answer.get("answer", ""))),
        RISKS, {})
    return [item for slide in slides or [] for item in slide["items"]]


def build_plan_input(corpus: dict, analysis: dict) -> dict:
    from .opportunity import without_account_risk

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
        answer = a.get("answer", "")
        if int(a["id"]) == RISKS:
            # The account lookup's risk line is placed by rfq/delivery.py; a
            # model that sees it only paraphrases it out of reach.
            answer = without_account_risk(answer, authoritative_risk_items(analysis))
        answers.append({
            "id": a["id"],
            "title_en": title[0],
            "title_de": title[1],
            "answer": answer,
        })
    return {"projectName": corpus.get("projectName", ""), "answers": answers}


def write_plan_input(folder: str) -> dict:
    """Build .work/plan_input.json from corpus.json + analysis.json.
    Raises FileNotFoundError when either checkpoint is missing."""
    work = os.path.join(os.path.abspath(folder), "output", ".work")
    with open(os.path.join(work, "corpus.json"), encoding="utf-8") as fh:
        corpus = json.load(fh)
    with open(os.path.join(work, "analysis.json"), encoding="utf-8") as fh:
        analysis = json.load(fh)
    payload = build_plan_input(corpus, analysis)
    with open(os.path.join(work, "plan_input.json"), "w",
              encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return payload


_TAG_RE = re.compile(r"\s*\((inferred|assessment|analysis|not found|stated)\)",
                     re.IGNORECASE)

_STAGE_HEADERS = {"phase", "phases", "stage", "development stage",
                  "development phase", "dev stage", "development stages"}

# Owner-cell spellings that mean "not applicable in this phase" — normalized
# to a blank dash so the row STAYS in the matrix (a task that only exists in
# one phase is still a valid single-owner row).
_NA_VALUES = {"n/a", "na", "n.a.", "not applicable", "none", "–", "—", "-", ""}


def _norm_txt(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


# Generic words that carry no identity of their own in a phase name.
_PHASE_STOPWORDS = {"phase", "phases", "stage", "the", "of", "and", "for",
                    "to", "a", "an", "in"}


def _phase_tokens(name: str) -> list[str]:
    pre = re.split(r"[(]", str(name))[0]          # drop bracketed annotations
    return [t for t in _norm_txt(pre).split()
            if t not in _PHASE_STOPWORDS and not t.isdigit()]


def _token_hits(tok: str, words: set[str]) -> bool:
    """A name token matches a source word exactly, or as a prefix in either
    direction — so shortened forms ('temp' -> 'temperature', 'thermo' ->
    'thermodynamic', 'dev' -> 'development') still trace back."""
    if tok in words:
        return True
    if len(tok) >= 3 and any(w.startswith(tok) for w in words):
        return True
    return len(tok) >= 4 and any(tok.startswith(w) and len(w) >= 4
                                 for w in words)


def _phase_traceable(name: str, corpus_norm: str,
                     src_words: set[str] | None = None) -> bool:
    """Is a phases-diagram label traceable to the corpus (or stage-1 answer)?

    Two tiers:
      1. exact — the normalized name (or its core / sample-collapsed variant)
         is a literal substring of the source text;
      2. fuzzy — >=70% of the name's distinctive tokens appear in the source
         vocabulary (prefix-tolerant). The slide-plan stage legitimately
         shortens long phase names for the chevron diagram ("X0 Thermo-Dev
         Testing" for "X0 prototype thermodynamic development testing"), and
         dropping such phases broke the Development Phases slide (client
         feedback: 2 of 5 phases shown). Fuzzy matching keeps every phase
         that is genuinely grounded while still rejecting invented labels
         (an "A2 Sample" no source ever names shares no distinctive token).
    """
    pre = re.split(r"[(—–]", str(name))[0]
    full = _norm_txt(pre)
    core = _norm_txt(re.split(r"/", pre)[0])
    collapsed = _norm_txt(re.sub(r"[-\s]*[Ss]ample", "", pre))
    collapsed = (collapsed + " sample").strip() if collapsed else ""
    if any(v and v in corpus_norm for v in (full, core, collapsed)):
        return True
    if src_words is None:
        src_words = set(corpus_norm.split())
    toks = _phase_tokens(name)
    if not toks:
        return False
    if len(toks) == 1:
        return toks[0] in corpus_norm or _token_hits(toks[0], src_words)
    hits = sum(1 for t in toks if _token_hits(t, src_words))
    return hits / len(toks) >= 0.55


def _fixed_title(question: dict, slide: dict) -> str | None:
    """The mandated title for a slide whose title is NOT the model's to vary,
    or None. The Collaboration Approach section is one collab diagram titled
    with the section title, and BOTH risk panels carry the section title too,
    so the deck shows one "Risk Detection" title over each risk group (the
    panel heading tells Project from Document risks)."""
    layout, title_en = slide.get("layout"), question.get("titleEn")
    if layout == "collab" and title_en == TITLES[COLLABORATION][0]:
        return title_en
    if layout == "panel" and title_en == TITLES[RISKS][0]:
        return title_en
    return None


def _append_callout(slide: dict, text_: str, tag: str = "NOTE") -> None:
    co = slide.get("callout")
    if co and co.get("text"):
        co["text"] = (co["text"].rstrip(". ") + ". " + text_)[:400]
    else:
        slide["callout"] = {"tag": tag, "text": text_}


def _owner_col_idxs(columns: list) -> list[int]:
    """Which columns of an ownership table hold OWNER values (not stage info)."""
    return [i for i in range(1, len(columns))
            if _norm_txt(columns[i]) not in _STAGE_HEADERS]


def clean_evidence_tags(value: str) -> str:
    """Remove evidence annotations using the same rule as slide cleanup."""
    return re.sub(r"\s{2,}", " ", _TAG_RE.sub("", value)).strip()


# The tags that never reach a slide. "(inferred)" is drawn (amber) where
# the renderer shows it - table and ownership cells, panel and list items,
# bullet text - and stripped everywhere else: phase and party names used as
# identifiers, descriptions and roles of the diagrams, chart steps and
# bars, callouts, the Opportunity slide.
_HIDDEN_TAG_RE = re.compile(r"\s*\((assessment|analysis|not found|stated)\)",
                            re.IGNORECASE)
_INFERRED_SHOWN = frozenset({"rows", "items", "leftItems", "rightItems",
                             "pros", "cons", "bullets"})


def _tag_pattern(layout, key):
    """The tags a slide's `key` may not carry."""
    return (_HIDDEN_TAG_RE if layout != "opportunity" and key in _INFERRED_SHOWN
            else _TAG_RE)


def _clean(value: str, pattern) -> str:
    return re.sub(r"\s{2,}", " ", pattern.sub("", value)).strip()


def _walk_tagged(obj, pattern, found: list, fix: bool) -> None:
    """Every string under `obj` that `pattern` matches goes into `found`
    as (key, value); with `fix`, it is also cleaned in place."""
    items = (obj.items() if isinstance(obj, dict)
             else enumerate(obj) if isinstance(obj, list) else ())
    for key, value in list(items):
        if isinstance(value, str):
            if pattern.search(value):
                found.append((key, value))
                if fix:
                    obj[key] = _clean(value, pattern)
        else:
            _walk_tagged(value, pattern, found, fix)


def _slide_tags(slide: dict, fix: bool) -> list:
    found = []
    for key in list(slide):
        holder = {key: slide[key]}
        _walk_tagged(holder, _tag_pattern(slide.get("layout"), key), found, fix)
        slide[key] = holder[key]
    return found


def tagged_strings(plan: dict) -> list[str]:
    """The plan strings that carry a tag no slide may show (the deck
    evaluation's C3 check; the same rule as the sanitizer's)."""
    found = []
    for key, value in plan.items():
        if key != "questions":
            _walk_tagged({key: value}, _TAG_RE, found, False)
    for question in plan.get("questions", []):
        for key, value in question.items():
            if key != "slides":
                _walk_tagged({key: value}, _TAG_RE, found, False)
        for slide in question.get("slides", []):
            found += _slide_tags(slide, fix=False)
    return [value for _key, value in found]


def _scrub_tags(plan: dict) -> list[str]:
    """Strip the evidence tags a slide may not show (see _tag_pattern).
    A bullet tagged "(inferred)" keeps the tag in its text and gets the
    inferred flag (the renderer draws the tag once either way)."""
    actions = []
    for q in plan.get("questions", []):
        for sl in q.get("slides", []):
            for b in sl.get("bullets") or []:
                if re.search(r"\(inferred\)", b.get("text", ""), re.I):
                    b["inferred"] = True
            actions += [f"tag stripped from {k}: {v[:50]}" if isinstance(k, str)
                        else f"tag stripped: {v[:50]}"
                        for k, v in _slide_tags(sl, fix=True)]
    return actions


def _guard_ownership(plan: dict) -> list[str]:
    """Audit guard: warn when the ownership matrix has suspicious uniformity.
    Does NOT alter cells — only logs warnings."""
    actions: list[str] = []
    for q in plan.get("questions", []):
        for sl in q.get("slides", []):
            if sl.get("layout") != "ownership":
                continue
            owner_idxs = _owner_col_idxs(sl.get("columns", []))
            if len(owner_idxs) < 3:
                continue
            rows = sl.get("rows", [])
            uniform_count = 0
            for row in rows:
                owners = [str(row[i]).strip() for i in owner_idxs
                          if i < len(row)]
                non_blank = [o for o in owners if o not in ("", "—", "-")]
                if len(non_blank) >= 3 and len(set(non_blank)) == 1:
                    uniform_count += 1
            if uniform_count > 0:
                actions.append(
                    f"ownership-audit: {uniform_count}/{len(rows)} task rows "
                    f"have identical owner across all {len(owner_idxs)} phases")
    return actions


def sanitize_plan(plan: dict, corpus_text: str,
                  analysis_text: str = "") -> tuple[dict, list[str]]:
    """Apply all deterministic guards. Returns (plan, actions).

    `analysis_text` (the concatenated stage-1 answers) is a second trace
    source for phase names: stage 2 may only present what stage 1 extracted,
    so a phase grounded in the answers is legitimate even when the upstream
    corpus extraction garbled the wording (image-based timing charts).

    * slide titles the client fixed: the Collaboration Approach diagram is
      titled "Collaboration Approach", and BOTH Risk Detection panels are
      "Risk Detection" (Project vs Document Risks is the panel HEADING, not
      the title) — neither takes a "<titleEn> — <suffix>" variant;
    * phases diagram: a phase whose name cannot be traced to the corpus or
      the stage-1 answers — exactly or by fuzzy token match (fabricated
      chart labels like an invented "A2 Sample") — is REMOVED and disclosed
      in the slide callout;
    * ownership matrix: "n/a"-style owner cells are normalized to a blank
      dash and the row KEPT (phase-specific tasks are legitimate); rows whose
      owner cells are otherwise not AVL / customer / Supplier / blank
      (e.g. "Excluded", "TBD") are moved out of the matrix into the slide
      callout — the matrix stays a pure single-owner table;
    * literal evidence tags are stripped, except "(inferred)" where the
      renderer draws it (table cells, panel items, bullet text).
    """
    actions: list[str] = []
    corpus_norm = _norm_txt(corpus_text) if corpus_text else ""
    source_norm = " ".join(
        v for v in (corpus_norm,
                    _norm_txt(analysis_text) if analysis_text else "") if v)
    src_words = set(source_norm.split())
    for q in plan.get("questions", []):
        for sl in q.get("slides", []):
            fixed = _fixed_title(q, sl)
            if fixed is not None and sl.get("title") != fixed:
                actions.append(f"title: '{sl.get('title')}' -> '{fixed}'")
                sl["title"] = fixed
            if sl.get("layout") == "phases" and source_norm:
                keep, dropped = [], []
                for p in sl.get("phases", []):
                    (keep if _phase_traceable(p.get("name", ""), source_norm,
                                              src_words)
                     else dropped).append(p)
                if dropped and keep:          # never empty the diagram
                    all_phases = sl.get("phases", [])
                    if (len(all_phases) >= 5
                            and len(dropped) > 0.4 * len(all_phases)):
                        sl["phases"] = keep + dropped
                        names = ", ".join(p.get("name", "?") for p in dropped)
                        actions.append(
                            f"phases: kept {len(dropped)} unverifiable phases "
                            f"(>40% would be lost): {names}")
                    else:
                        sl["phases"] = keep
                        names = ", ".join(p.get("name", "?") for p in dropped)
                        _append_callout(
                            sl,
                            f"Unverifiable chart label(s) omitted "
                            f"(not literal in the corpus): {names}")
                        actions.append(
                            f"phases: dropped unverifiable {names}")
            elif sl.get("layout") == "ownership":
                abbr = str(sl.get("customerAbbr", "Customer")).lower()
                # "joint" belongs here, not just in the renderer's color map:
                # a row holding any value outside this set is MOVED OUT of the
                # matrix below, and the ownership layout has no callout band to
                # move it to - so an unlisted marker is silently dropped from
                # the deck rather than rendered uncolored.
                allowed = {"avl", "supplier", "customer", abbr, "joint",
                           "", "-", "—"}
                owner_idxs = _owner_col_idxs(sl.get("columns", []))
                # normalize "n/a"-style cells to a blank dash FIRST, so
                # phase-specific tasks keep their row in the matrix
                for row in sl.get("rows", []):
                    for i in owner_idxs:
                        if i < len(row) and \
                                str(row[i]).strip().lower() in _NA_VALUES:
                            if str(row[i]).strip() not in ("", "-", "—"):
                                actions.append(
                                    f"ownership: normalized '{row[i]}' -> — "
                                    f"in '{row[0]}'")
                                row[i] = "—"
                keep, moved = [], []
                for row in sl.get("rows", []):
                    owners = [str(row[i]).strip().lower()
                              for i in owner_idxs if i < len(row)]
                    (keep if all(o in allowed for o in owners)
                     else moved).append(row)
                if moved and keep:
                    sl["rows"] = keep
                    for row in moved:
                        _append_callout(sl, f"{row[0]}: {' / '.join(row[1:])}")
                        actions.append(f"ownership: moved '{row[0]}' "
                                       f"({'/'.join(row[1:])}) to callout")
    actions += _scrub_tags(plan)
    actions += _guard_ownership(plan)
    return plan, actions
