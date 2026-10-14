"""Construct slide-plan input and apply deterministic plan guards."""

import json
import os
import re
import sys

from .schema import (COLLABORATION, OPPORTUNITY, PHASES, RISKS, SCOPE,
                     SECTION_IDS, SECTION_SHAPES, TIMING, TITLES)


def _answer_whitespace(text_: str) -> str:
    """Normalize horizontal whitespace, preserving paragraph/row boundaries."""
    return "\n".join(" ".join(line.split())
                     for line in text_.splitlines()).strip()


def _typed_table(columns: list[str], rows: list[list[str]]) -> str:
    if (not columns or any(len(row) != len(columns) for row in rows)
            or any("|" in cell or "\n" in cell or "\r" in cell
                   for row in [columns, *rows] for cell in row)):
        raise ValueError("Typed tables require unambiguous complete cells.")
    return "\n".join(["| " + " | ".join(columns) + " |",
                      "| " + " | ".join("---" for _ in columns) + " |"]
                     + ["| " + " | ".join(row) + " |" for row in rows])


def _typed_bool(value) -> str:
    return "" if value is None else ("true" if value else "false")


def _typed_line(text_: str) -> str:
    # Multiline values could inject extra canonical list items or metadata
    # blocks without matching their actual typed item count.
    if len(text_.splitlines()) > 1 or "\n" in text_ or "\r" in text_:
        raise ValueError("Typed list and metadata values must be single lines.")
    return text_


def _typed_answer_block(slide: dict, timing_chart: bool = False) -> str:
    """The explicitly documented lossless answer form; never parse prose.

    Layout metadata with factual content is included in the form. Titles are
    app-owned. Timing's chart repeats only the authoritative table's rows and
    is validated separately, so milestones need no duplicate answer text.
    """
    layout = slide["layout"]
    blocks = []
    if layout in ("table", "ownership"):
        if layout == "ownership" and slide.get("customerAbbr"):
            blocks.append("Customer abbreviation: " + _typed_line(slide["customerAbbr"]))
        blocks.append(_typed_table(slide["columns"], slide["rows"]))
    elif layout == "prose":
        if slide.get("caption"):
            blocks.append("Caption: " + _typed_line(slide["caption"]))
        blocks.append(slide["body"])
    elif layout == "bullets":
        blocks.append("\n".join(
            "- " + _typed_line(b["text"]) + (" (inferred)" if b.get("inferred")
                                    and not re.search(r"\(inferred\)", b["text"], re.I)
                                    else "") for b in slide["bullets"]))
    elif layout == "panel":
        blocks.append("## " + _typed_line(slide["heading"]) + "\n"
                      + "\n".join("- " + _typed_line(item) for item in slide["items"]))
    elif layout == "phases":
        blocks.append(_typed_table(
            ["Phase", "Definition", "Hardware milestone"],
            [[phase["name"], phase.get("desc", ""), _typed_bool(phase.get("hw"))]
             for phase in slide["phases"]]))
    elif layout == "collab":
        if slide.get("hub"):
            blocks.append("Hub: " + _typed_line(slide["hub"]))
        blocks.append(_typed_table(["Party", "Role", "Type", "Dashed"], [
            [party["name"], party.get("role", ""), party.get("type", ""),
             _typed_bool(party.get("dashed"))] for party in slide["parties"]]))
    elif layout in ("gantt", "timeline"):
        if slide.get("barLabel"):
            blocks.append("Project bar: " + _typed_line(slide["barLabel"]))
        if slide.get("bars"):
            blocks.append(_typed_table(["Bar", "Start", "End"], [
                [bar["name"], bar.get("start", ""), bar.get("end", "")]
                for bar in slide["bars"]]))
        if not timing_chart:
            blocks.append(_typed_table(["Milestone", "Target timing", "Phase / Task"], [
                [step["label"], step["date"], step["desc"]]
                for step in slide["steps"]]))
    else:
        raise ValueError("Unsupported typed presentation layout.")
    callout = slide.get("callout")
    if callout:
        if layout in ("table", "ownership", "bullets", "panel"):
            raise ValueError("The renderer cannot display this layout's callout.")
        blocks.append(_typed_line(callout["tag"]) + ": " + _typed_line(callout["text"]))
    return "\n\n".join(block for block in blocks if block)


def _typed_shapes(questions: list[dict]) -> bool:
    """Canonical shapes and cross-section facts required for the fast path."""
    from .dates import time_pos
    from .renderer import _wrap_count, PAGE_W, M

    for question in questions:
        for slide in question["slides"]:
            co = slide.get("callout")
            if co and _wrap_count(co["text"], PAGE_W - 2 * M - 1.85, 11) > 3:
                return False  # The fixed 0.7-inch callout band cannot fit it.

    by_id = {question["number"]: question["slides"] for question in questions}
    def layouts(section):
        return [slide["layout"] for slide in by_id[section]]
    # The one section-shape contract, shared with validation.check_plan so the
    # fast path and the slide worker can never be held to different rules.
    for section, shapes in SECTION_SHAPES.items():
        if tuple(layouts(section)) not in shapes:
            return False
    phase_slide = by_id[PHASES][0]
    phase_names = ([phase["name"] for phase in phase_slide["phases"]]
                   if phase_slide["layout"] == "phases"
                   else [row[0] for row in phase_slide["rows"]])
    if not phase_names or by_id[SCOPE][0]["columns"] != ["Scope of Work", *phase_names]:
        return False
    ownership = by_id[SCOPE][0]
    owners = {"AVL", "Supplier", "Customer", "Joint", "—", "-", "",
              ownership.get("customerAbbr") or "Customer"}
    if any(cell not in owners for row in ownership["rows"] for cell in row[1:]):
        return False
    if ([slide["heading"] for slide in by_id[RISKS]]
            != ["Project Risks", "Document Risks"]
            or any(not slide["items"] for slide in by_id[RISKS])):
        return False
    chart, table = by_id[TIMING]
    if table["columns"] != ["Milestone", "Target timing", "Phase / Task"]:
        return False
    rows = table["rows"]
    dated = [row for row in rows if time_pos(row[1]) is not None]
    if chart["layout"] == "gantt":
        if len(dated) < 2 or len(chart.get("bars") or []) > 8:
            return False
        if chart.get("bars") and chart.get("barLabel"):
            return False  # L_gantt draws the project label only without bars.
        for bar in chart.get("bars") or []:
            start = time_pos(bar["start"])
            end = time_pos(bar["end"], end=True)
            if start is None or end is None or end <= start:
                return False  # L_gantt silently excludes unsupported spans.
        expected = dated[:14]  # later dates still appear in the complete table
    else:
        if len(dated) >= 2:
            return False
        expected = rows
    if [[step["label"], step["date"], step["desc"]]
            for step in chart["steps"]] != expected:
        return False
    positions = [time_pos(row[1]) for row in dated]
    return positions == sorted(positions)


def deterministic_plan(corpus: dict, analysis: dict, account: dict | None = None) -> dict | None:
    """Build the whole canonical draft only from complete lossless typed data.

    None means use the existing slide worker for the entire plan. No partial
    slides or heuristic answer parsing are allowed. The caller has already
    verified the mandatory analysis fields and source references.
    """
    from pydantic import ValidationError
    from .opportunity import account_risk_line
    from .schema import PresentationContent, LoosePlanDraft, tighten_plan
    from .validation import check_plan

    if not isinstance(corpus, dict) or not isinstance(analysis, dict):
        return None
    answers = analysis.get("answers")
    if (not isinstance(answers, list)
            or any(not isinstance(answer, dict) for answer in answers)
            or any(type(answer.get("id")) is not int for answer in answers)
            or [answer["id"] for answer in answers] != list(SECTION_IDS)):
        return None
    questions = []
    try:
        for answer in answers:
            number = answer["id"]
            title_en, title_de = TITLES[number]
            if number == OPPORTUNITY:
                slides = [{"layout": "opportunity", "title": title_en}]
            else:
                presentation = PresentationContent.model_validate(answer.get("presentation"))
                slides = [slide.model_dump(exclude_none=True)
                          for slide in presentation.slides]
                if not slides:
                    return None
                for index, slide in enumerate(slides):
                    slide["title"] = (title_en if index == 0 or number == RISKS
                                      else title_en + " — " + (
                                          "Milestone Table" if number == TIMING
                                          else f"Part {index + 1}"))
                rendered = "\n\n".join(
                    block for slide in slides
                    if (block := _typed_answer_block(
                        slide, timing_chart=number == TIMING
                        and slide["layout"] in ("gantt", "timeline"))))
                original = answer.get("answer")
                if not isinstance(original, str):
                    return None
                if number == RISKS and isinstance(account, dict):
                    app_line = account_risk_line(account)
                    # add_account_risk appends exactly one final line. Exclude
                    # only the caller's current lookup sentence, never broad
                    # prefixes that could also be real source-document prose.
                    suffix = "\n- " + app_line if app_line else ""
                    if suffix and original.endswith(suffix):
                        original = original[:-len(suffix)]
                if _answer_whitespace(rendered) != _answer_whitespace(original):
                    return None
            questions.append({"number": number, "titleEn": title_en,
                              "titleDe": title_de, "slides": slides})
        draft = {"projectName": corpus.get("projectName", ""), "questions": questions}
        if check_plan(draft) or not _typed_shapes(questions):
            return None
        return tighten_plan(
            LoosePlanDraft.model_validate(draft).model_dump(exclude_none=True))
    except (ValidationError, ValueError, TypeError, KeyError, IndexError):
        return None


def authoritative_risk_items(analysis: dict) -> list:
    """Exact typed source items remain protected even when other sections fall back."""
    answer = next((a for a in analysis.get("answers", []) if a.get("id") == RISKS), {})
    lines = {line.strip()[2:] for line in str(answer.get("answer", "")).splitlines()
             if line.strip().startswith("- ")}
    return [item for slide in (answer.get("presentation") or {}).get("slides", [])
            for item in slide.get("items", []) if isinstance(item, str) and item in lines]


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
            "confidence": a.get("confidence", ""),
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


def _scrub_tags(plan: dict) -> list[str]:
    """Deterministically strip literal evidence tags from every plan string.
    For bullets, '(inferred)' also sets the bullet's inferred flag."""
    actions = []

    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, str):
                    if _TAG_RE.search(v):
                        obj[k] = clean_evidence_tags(v)
                        actions.append(f"tag stripped from {k}: {v[:50]}")
                else:
                    walk(v)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                if isinstance(v, str):
                    if _TAG_RE.search(v):
                        actions.append(f"tag stripped: {v[:50]}")
                        obj[i] = clean_evidence_tags(v)
                else:
                    walk(v)

    for q in plan.get("questions", []):
        for sl in q.get("slides", []):
            for b in sl.get("bullets") or []:
                if re.search(r"\(inferred\)", b.get("text", ""), re.I):
                    b["inferred"] = True
            walk(sl)
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
    * literal evidence tags ("(inferred)" etc.) are stripped everywhere.
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
