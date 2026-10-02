"""Deterministic plan guards applied AFTER the slide-plan call.

Model-variance insurance: the prompts ask for these properties, the sanitizer
guarantees them. Every action is returned (and stored in the run payload) so
each intervention is auditable.
"""

import re

from .schema import TITLES

_TAG_RE = re.compile(r"\s*\((inferred|assessment|analysis|not found|stated)\)",
                     re.IGNORECASE)

# Client-confirmed slide titles that do NOT follow the "<titleEn> — <suffix>"
# format: the id-5 collaboration diagram carries its own name, and BOTH id-11
# risk panels carry the plain section title (their heading is the difference).
COLLAB_TITLE = "Collaboration Approach"

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
    or None. Both risk panels are titled with the section title itself, so the
    deck shows one "Risk Detection" title over each risk group."""
    layout, title_en = slide.get("layout"), question.get("titleEn")
    if layout == "collab" and title_en == TITLES[5][0]:
        return COLLAB_TITLE
    if layout == "panel" and title_en == TITLES[11][0]:
        return TITLES[11][0]
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


def _scrub_tags(plan: dict) -> list[str]:
    """Deterministically strip literal evidence tags from every plan string.
    For bullets, '(inferred)' also sets the bullet's inferred flag."""
    actions = []

    def clean(s):
        out = _TAG_RE.sub("", s)
        return re.sub(r"\s{2,}", " ", out).strip()

    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, str):
                    if _TAG_RE.search(v):
                        obj[k] = clean(v)
                        actions.append(f"tag stripped from {k}: {v[:50]}")
                else:
                    walk(v)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                if isinstance(v, str):
                    if _TAG_RE.search(v):
                        actions.append(f"tag stripped: {v[:50]}")
                        obj[i] = clean(v)
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

    * slide titles the client fixed: the id-5 collaboration diagram is
      "Collaboration Approach", and BOTH id-11 risk panels are "Risk
      Detection" (Project vs Document Risks is the panel HEADING, not the
      title) — neither follows the "<titleEn> — <suffix>" format;
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
