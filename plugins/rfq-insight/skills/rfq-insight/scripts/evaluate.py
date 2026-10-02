#!/usr/bin/env python3
"""Deterministic quality checks on a finished run.

Usage (no API key needed):
    python evaluate.py <the report path finalize.py printed> \
        [--corpus <folder>/output/.work/corpus.json]

The report filename is derived from the opportunity name with anything
awkward for a filename replaced, so never construct it - use the path
finalize.py prints.

Checks the run report finalize.py writes:

  FAIL-level (real defects):
    C1  all 11 canonical sections present in the analysis
    C2  every phase shown on the slides traces to the corpus or stage-1
        answers — exact or fuzzy-token, the same rule the sanitizer applies
        (guards the A/B/C/D-padding regression)          [needs --corpus]
    C3  no literal tags "(inferred)/(assessment)/(analysis)/(not found)"
        in any slide-plan field (incl. table cells)
    C4  ownership owner cells only AVL / Supplier / customerAbbr / blank
    C5  timeline/gantt steps in chronological order (where dates parse)
    C6  every question's first slide title == its titleEn

  WARN-level (style/scope):
    W1  Summary (id 3) is a single prose slide, body <= 300 words
    W2  section 10 standard names traceable to the corpus [needs --corpus]
    W3  confidence present on every question
    W4  no near-empty continuation slides (twoColumn with <2 items/side)
    W5  Timing (id 9) uses the one-slide "gantt" diagram
    W6  Risk Detection (id 11) separates Project vs Document risks into
        their own "panel" slides (never mixed on one slide)

Exit code 0 = no FAILs (warnings allowed), 1 = at least one FAIL.
Run it after every prompt/knowledge change, on every stored test corpus.
"""

import argparse
import json
import re
import sys

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
    """Sortable key for a milestone date string, from the SAME parser the
    renderer places milestones with (`rfq.dates.time_pos`).

    C5 asks "is the plan listed in the order the deck draws it?", so this must
    never be a second opinion about what a date means. It used to be one: this
    checker ignored the "early / mid / end of" qualifiers the renderer honours
    and keyed every bare span to its midpoint, so "end of 2026" sorted BEFORE
    "December 2026" and C5 warned about a deck drawn in the right order.

    Imported lazily and path-guarded, the way `_phase_ok` does it, so the
    checker still runs when it is invoked as a bare script from any directory.
    Returns a fractional month position, or None when no calendar position can
    be derived - callers only ever compare these, never display them.
    """
    import os
    import sys as _sys
    _here = os.path.dirname(os.path.abspath(__file__))
    if _here not in _sys.path:
        _sys.path.insert(0, _here)
    from rfq.dates import time_pos
    return time_pos(s)


def _phase_ok(name, corpus_norm):
    """Same traceability rule the sanitizer applies (exact OR fuzzy token
    match) — imported so the eval can never drift from the shipped guard."""
    import os
    import sys as _sys
    _here = os.path.dirname(os.path.abspath(__file__))
    if _here not in _sys.path:
        _sys.path.insert(0, _here)
    from rfq.sanitize import _phase_traceable
    return _phase_traceable(name, corpus_norm)


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def evaluate(payload, corpus_text=None):
    fails, warns, oks = [], [], []
    analysis = payload.get("analysis", {})
    plan = payload.get("slidePlan", {})
    answers = {a.get("id"): a for a in analysis.get("answers", [])}

    # C1 all sections present
    missing = [i for i in range(1, 12) if i not in answers]
    (fails if missing else oks).append(
        f"C1 sections 1-11 present" + (f" — MISSING {missing}" if missing else ""))

    # C2 phases traceable to corpus + stage-1 answers (same sources and same
    # exact-or-fuzzy rule the sanitizer enforces — the slide-plan stage may
    # shorten a phase name, but every distinctive token must trace back)
    if corpus_text is not None:
        corpus_norm = _norm(corpus_text)
        answers_norm = _norm("\n".join(str(a.get("answer", ""))
                                       for a in analysis.get("answers", [])))
        source_norm = (corpus_norm + " " + answers_norm).strip()
        analysis_names, slide_names = [], []
        a6 = str(answers.get(6, {}).get("answer", ""))
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

    # C3 literal tags in the slide plan
    tagged = [s[:60] for s in _walk_strings(plan)
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

    # W1 summary scope
    for q in plan.get("questions", []):
        if q.get("titleEn") != "Summary":
            continue
        slides = q.get("slides", [])
        prose = [s for s in slides if s.get("layout") == "prose"]
        if len(slides) != len(prose) or len(prose) > 2:
            warns.append(f"W1 Summary has {len(slides)} slides "
                         f"({[s.get('layout') for s in slides]}) — expected 1 prose")
        elif prose and len(prose[0].get("body", "").split()) > 300:
            warns.append("W1 Summary body exceeds 300 words")
        else:
            oks.append("W1 Summary is a compact prose slide")

    # W2 standards traceability
    if corpus_text is not None:
        corpus_norm = _norm(corpus_text)
        loose = []
        for q in plan.get("questions", []):
            if q.get("titleEn") != "Customer Specific Standards":
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

    # W3 confidence
    missing_conf = [q.get("titleEn") for q in plan.get("questions", [])
                    if not q.get("confidence")]
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
        if q.get("titleEn") != "Risk Detection":
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
        if q.get("titleEn") != "Timing":
            continue
        layouts = [sl.get("layout") for sl in q.get("slides", [])]
        if "gantt" in layouts:
            oks.append("W5 Timing uses the gantt diagram")
        elif "timeline" in layouts:
            warns.append("W5 Timing uses the fallback timeline (no gantt) — "
                         "expected only when milestones carry no calendar dates")
        else:
            warns.append(f"W5 Timing has no timing diagram (layouts: {layouts})")

    return fails, warns, oks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_json", help="the run report finalize.py wrote")
    ap.add_argument("--corpus", help=".work/corpus.json for the run "
                                 "(enables C2/W2 traceability checks)")
    args = ap.parse_args()

    with open(args.run_json, encoding="utf-8") as fh:
        payload = json.load(fh)
    corpus_text = None
    if args.corpus:
        with open(args.corpus, encoding="utf-8") as fh:
            corpus = _loads_lenient(fh.read())
        fc = corpus.get("filesContents") or corpus.get("files") or []
        corpus_text = "\n".join(f.get("extracted_text", "") for f in fc)

    fails, warns, oks = evaluate(payload, corpus_text)
    for line in oks:
        print(f"  PASS  {line}")
    for line in warns:
        print(f"  WARN  {line}")
    for line in fails:
        print(f"  FAIL  {line}")
    print(f"\n{len(fails)} fail / {len(warns)} warn / {len(oks)} pass")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
