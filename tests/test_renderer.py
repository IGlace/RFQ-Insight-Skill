"""Tests for the RFQ Insight renderer and slide-plan schema.

Ported from RFQ_Container_App/tests/test_insight_renderer.py. They pin the
behaviours that were regressions before (table fill before split, fixed type
per layout family, timeline balance, chronological sort) plus the diagram
layouts (gantt, phases, collab, ownership, panel).

The slide plan is the client format of 18.09.2026: twelve canonical sections,
each present exactly once and in order (`SlidePlan` rejects anything else).
Every fixture below therefore starts from a complete baseline deck and
replaces the one section a test is about; `_section_slides` reads back the
rendered pages of that section alone.
"""

import time

import pytest
from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from helpers import sample_plan
from rfq import renderer as rdi
from rfq.schema import SECTION_IDS, SECTION_SHAPES, SlidePlan, TITLES


def _q(number, slides, **extra):
    """A question carrying its canonical titles."""
    en, de = TITLES[number]
    return {"number": number, "titleEn": en, "titleDe": de,
            "slides": slides, **extra}


# One minimal slide set per section, in that section's first canonical shape
# (schema.SECTION_SHAPES). Each renders to exactly one page, except Timing
# (gantt + table) and Risk Detection (panel + panel), which take two.
BASELINE_SLIDES = {
    1: [{"layout": "opportunity", "title": "Opportunity Info",
         "columns": ["Opportunity Info", "Definition according to RFQ"],
         "rows": [["Customer", "Lorem Ipsum JSC"],
                  ["Quotation due date", "20.06.2026"]],
         "products": [["Demo product", "100"]],
         "skills": [["Demo skill", "100"]]}],
    2: [{"layout": "prose", "title": "Description",
         "body": "A demo system.\nFor a demo customer."}],
    3: [{"layout": "table", "title": "Technical Product Definitions and Targets",
         "columns": ["Parameter", "Target"], "rows": [["Power", "150 kW"]]}],
    4: [{"layout": "table", "title": "Application Approach",
         "columns": ["Variant", "Powertrain"], "rows": [["Model A", "BEV"]]}],
    5: [{"layout": "collab", "title": "Collaboration Approach", "hub": "Demo",
         "parties": [{"name": "LI", "role": "OEM", "type": "customer"},
                     {"name": "AVL", "role": "Engineering", "type": "avl"}],
         "callout": None}],
    6: [{"layout": "phases", "title": "Development Phases",
         "phases": [{"name": "Concept", "desc": "Gate 1"}], "callout": None}],
    7: [{"layout": "ownership", "title": "Scope of Work and Responsibilities",
         "customerAbbr": "LI", "columns": ["Scope of Work", "Concept"],
         "rows": [["System engineering", "AVL"]], "callout": None}],
    8: [{"layout": "table", "title": "AVL Deliverables",
         "columns": ["Deliverable", "Phase"], "rows": [["Report", "Concept"]]}],
    9: [{"layout": "gantt", "title": "Timing", "barLabel": "Demo",
         "steps": [{"label": "Kick-off", "date": "Jul 2026", "desc": ""},
                   {"label": "SOP", "date": "Q1 2028", "desc": ""}],
         "callout": None},
        {"layout": "table", "title": "Timing — Table",
         "columns": ["Milestone", "Date"], "rows": [["Kick-off", "Jul 2026"]]}],
    10: [{"layout": "table", "title": "Customer Specific Standards",
          "columns": ["Standard", "Scope"], "rows": [["ISO 26262", "FuSa"]]}],
    11: [{"layout": "panel", "title": "Risk Detection",
          "heading": "Project Risks", "items": ["Schedule is tight."]},
         {"layout": "panel", "title": "Risk Detection — Document Risks",
          "heading": "Document Risks", "items": ["Annex X missing."]}],
    12: [{"layout": "bullets", "title": "Source Material",
          "bullets": [{"text": "RFQ.pdf"}]}],
}
BASELINE_PAGES = {9: 2, 11: 2}          # rendered pages per baseline section


def _plan_with(*questions, **plan_fields):
    """A complete 12-section plan: `questions` replace their baseline
    section, every other section is the minimal baseline above."""
    custom = {q["number"]: q for q in questions}
    plan = {"projectName": "Demo", "date": "2026-08-03",
            "questions": [custom.get(n, _q(n, BASELINE_SLIDES[n]))
                          for n in SECTION_IDS]}
    plan.update(plan_fields)
    return plan


def _render(*questions):
    return rdi.create_presentation(
        SlidePlan.model_validate(_plan_with(*questions)).model_dump())


def _section_slides(prs, number):
    """The rendered pages of section `number` in a deck built by _render with
    that single section customised: cover + toc, the baseline sections before
    it, [its pages], the baseline sections after it, end cover."""
    before = 2 + sum(BASELINE_PAGES.get(n, 1) for n in SECTION_IDS if n < number)
    after = 1 + sum(BASELINE_PAGES.get(n, 1) for n in SECTION_IDS if n > number)
    slides = list(prs.slides)
    return slides[before:len(slides) - after]


def _content_slides(question):
    """The question's rendered slides (covers and other sections stripped)."""
    return _section_slides(_render(question), question["number"])


INSIGHT_PLAN = _plan_with(
    _q(1, [{"layout": "opportunity", "title": "Opportunity Info",
            "columns": ["Opportunity Info", "Definition according to RFQ"],
            "rows": [["Customer", "Lorem Ipsum JSC"],
                     ["Quotation due date", "20.06.2026"],
                     ["Project type", "SOP Project w/o CSM"]],
            "products": [["Demo product", "60"], ["Other product", "40"]],
            "skills": [["Simulation", "50"], ["Testing", "50"]]}],
       confidence="high"),
    _q(6, [{"layout": "phases", "title": "Development Phases",
            "phases": [{"name": "Concept", "desc": "Gate 1"},
                       {"name": "A-Sample", "desc": "Mule", "hw": True}],
            "callout": {"tag": "NOTE", "text": "Demo callout."}}],
       confidence="medium"),
    _q(7, [{"layout": "ownership", "title": "Scope of Work and Responsibilities",
            "customerAbbr": "LI",
            "columns": ["Scope of Work", "Concept", "A-Sample"],
            "rows": [["System engineering", "AVL", "AVL"],
                     ["Prototype build", "LI", "LI"],
                     ["Component supply", "Supplier", "Supplier"]],
            "callout": {"tag": "GAP", "text": "Sourcing not stated."}}],
       confidence="high"),
    _q(9, [{"layout": "timeline", "title": "Timing",
            "steps": [{"label": "Quotation deadline",
                       "date": "20-Jun-2026", "desc": "Bid"},
                      {"label": "A-Sample design release",
                       "date": "15-Jul-2026", "desc": "Design"},
                      {"label": "First vehicle SOP",
                       "date": "30-Aug-2027", "desc": "Program"}],
            "callout": None},
           {"layout": "table", "title": "Timing — Table",
            "columns": ["Milestone", "Date"],
            "rows": [["Quotation deadline", "20-Jun-2026"],
                     ["First vehicle SOP", "30-Aug-2027"]]}],
       confidence="high"),
    _q(11, [{"layout": "panel", "title": "Risk Detection",
             "heading": "Project Risks", "items": ["Schedule is aggressive."]},
            {"layout": "panel", "title": "Risk Detection — Document Risks",
             "heading": "Document Risks",
             "items": ["Ownership conflict between sections."]}],
       confidence="low"),
    projectName="Lorem Ipsum JSC\nDemo System – Engineering Design Service",
    oppId="OPP_000000", date="2026-07-23",
)

# The 7 layouts of the legacy /render contract. The insight renderer must keep
# rendering these unchanged — production asserts the same thing against
# render_deck.SAMPLE_PLAN, which the fork cannot import. They sit in section 2
# of an otherwise baseline deck (the schema pins section ids, not layouts).
LEGACY_QUESTION = {
    "number": 2, "titleEn": "Legacy Layouts", "titleDe": "Alte Layouts",
    "slides": [
        {"layout": "bullets", "title": "Bullets",
         "bullets": [{"text": "First point"},
                     {"text": "Second point", "inferred": True}],
         "callout": {"tag": "NOTE", "text": "A callout."}},
        {"layout": "table", "title": "Table",
         "columns": ["Key", "Value"], "rows": [["Customer", "Lorem Ipsum"]]},
        {"layout": "twoColumn", "title": "Two Column",
         "leftHeading": "Left", "leftItems": ["a", "b"],
         "rightHeading": "Right", "rightItems": ["c", "d"]},
        {"layout": "prosCons", "title": "Pros and Cons",
         "pros": ["Fast"], "cons": ["Costly"]},
        {"layout": "kpi", "title": "KPIs",
         "kpis": [{"value": "16", "unit": "months", "label": "Duration"},
                  {"value": "3", "unit": "", "label": "Programs"}]},
        {"layout": "prose", "title": "Prose",
         "caption": "A caption", "body": "One.\nTwo.\nThree."},
    ],
}
LEGACY_PLAN = _plan_with(LEGACY_QUESTION, projectName="Legacy Contract Demo",
                         date="2026-07-23")


def test_baseline_deck_renders_one_page_per_section_as_declared():
    """Every other test's index arithmetic rests on this page map."""
    prs = _render()
    expected = 2 + sum(BASELINE_PAGES.get(n, 1) for n in SECTION_IDS) + 1
    assert len(list(prs.slides)) == expected
    for number in SECTION_IDS:
        pages = _section_slides(prs, number)
        assert len(pages) == BASELINE_PAGES.get(number, 1), number
        assert _boxes(pages[0], [BASELINE_SLIDES[number][0]["title"]]), number


def test_baseline_fixtures_use_the_canonical_section_shapes():
    for number, slides in BASELINE_SLIDES.items():
        shape = tuple(sl["layout"] for sl in slides)
        assert shape in SECTION_SHAPES[number], (number, shape)


def test_insight_plan_renders_to_pptx_bytes():
    deck = rdi.render_to_bytes(SlidePlan.model_validate(INSIGHT_PLAN).model_dump())
    assert deck.startswith(b"PK")
    assert len(deck) > 10_000


def test_legacy_contract_plan_renders_in_insight_style():
    """Plans following the legacy production contract render unchanged."""
    deck = rdi.render_to_bytes(SlidePlan.model_validate(LEGACY_PLAN).model_dump())
    assert deck.startswith(b"PK")


def test_schema_validates_diagram_layouts():
    plan = _plan_with(_q(6, [
        {"layout": "phases", "title": "Phases",
         "phases": [{"name": "A-Sample", "desc": "No definition"}],
         "callout": None},
        {"layout": "collab", "title": "Collaboration model",
         "hub": "Project",
         "parties": [{"name": "VF", "role": "OEM", "type": "customer"},
                     {"name": "AVL", "role": "Engineering", "type": "avl"}],
         "callout": None},
        {"layout": "ownership", "title": "Scope of Work",
         "customerAbbr": "VF",
         "columns": ["Scope of Work", "A-Sample"],
         "rows": [["System specification", "AVL"], ["Testing", "VF"]],
         "callout": None},
    ]), oppId="OPP_000", date="2026-07-23")
    validated = SlidePlan.model_validate(plan).model_dump()
    deck = rdi.render_to_bytes(validated)
    assert deck.startswith(b"PK")


def test_schema_rejects_unknown_layout():
    bad = _plan_with(_q(2, [{"layout": "nope", "title": "x"}]))
    with pytest.raises(Exception):
        SlidePlan.model_validate(bad)


def test_schema_accepts_the_opportunity_layout_for_section_one():
    plan = _plan_with(_q(1, [{"layout": "opportunity",
                              "title": "Opportunity Info"}]))
    validated = SlidePlan.model_validate(plan).model_dump()
    first = validated["questions"][0]["slides"][0]
    # the app layer fills these later; the model emits layout + title only
    assert (first["columns"], first["rows"], first["products"],
            first["skills"]) == ([], [], [], [])
    assert rdi.render_to_bytes(validated).startswith(b"PK")


def test_schema_requires_all_twelve_sections_once_in_order():
    """The SlidePlan validator: every canonical section exactly once, in
    deck order. A missing, repeated or shuffled section is rejected."""
    good = _plan_with()
    SlidePlan.model_validate(good)

    missing = dict(good, questions=good["questions"][:-1])
    with pytest.raises(ValueError, match="canonical order"):
        SlidePlan.model_validate(missing)

    repeated = dict(good, questions=good["questions"] + [good["questions"][2]])
    with pytest.raises(ValueError, match="Duplicate"):
        SlidePlan.model_validate(repeated)

    shuffled = dict(good, questions=list(reversed(good["questions"])))
    with pytest.raises(ValueError, match="canonical order"):
        SlidePlan.model_validate(shuffled)

    # a single-section plan is exactly what the old fixtures used to build
    with pytest.raises(ValueError):
        SlidePlan.model_validate({"projectName": "Demo", "date": "2026-07-23",
                                  "questions": [good["questions"][8]]})


def test_schema_allows_additional_information_before_source_material():
    """Follow-up answers (section 13) slot in before Source Material, and
    nowhere else."""
    from rfq.schema import ADDITIONAL_INFO_ID, ADDITIONAL_INFO_TITLE
    extra = {"number": ADDITIONAL_INFO_ID,
             "titleEn": ADDITIONAL_INFO_TITLE[0],
             "titleDe": ADDITIONAL_INFO_TITLE[1],
             "slides": [{"layout": "panel", "title": ADDITIONAL_INFO_TITLE[0],
                         "heading": "What is the warranty?",
                         "items": ["Two years."]}]}
    good = _plan_with()
    questions = good["questions"][:-1] + [extra] + good["questions"][-1:]
    plan = SlidePlan.model_validate(dict(good, questions=questions)).model_dump()
    assert rdi.render_to_bytes(plan).startswith(b"PK")
    with pytest.raises(ValueError):
        SlidePlan.model_validate(dict(good, questions=good["questions"] + [extra]))


def test_canonical_titles_cover_all_12_sections():
    assert sorted(TITLES) == list(range(1, 13))
    assert [en for en, _ in TITLES.values()] == [
        "Opportunity Info", "Description",
        "Technical Product Definitions and Targets", "Application Approach",
        "Collaboration Approach", "Development Phases",
        "Scope of Work and Responsibilities", "AVL Deliverables", "Timing",
        "Customer Specific Standards", "Risk Detection", "Source Material"]
    assert set(SECTION_SHAPES) == set(TITLES)


def test_confidence_attach_and_render():
    plan = _plan_with(_q(10, [{"layout": "bullets",
                               "title": "Customer Specific Standards",
                               "bullets": [{"text": "x", "inferred": False}],
                               "callout": None}]), date="2026-07-23")
    validated = SlidePlan.model_validate(plan).model_dump()
    validated["questions"][9]["confidence"] = "high"
    deck = rdi.render_to_bytes(validated)
    assert deck.startswith(b"PK")


def test_timeline_chrono_sort():
    steps = [
        {"label": "SOP", "date": "From Q1 2030", "desc": ""},
        {"label": "Start", "date": "June 2026", "desc": ""},
        {"label": "KO", "date": "Q4 2026", "desc": ""},
        {"label": "M1", "date": "July 2026", "desc": ""},
        {"label": "M1 deliverables", "date": "+10 business days", "desc": ""},
        {"label": "M2", "date": "~Oct 2026", "desc": ""},
    ]
    ordered = [s["label"] for s in rdi._chrono_sort(steps)]
    assert ordered == ["Start", "M1", "M1 deliverables", "M2", "KO", "SOP"]


def test_date_key_month_beats_quarter():
    assert rdi._date_key("~ Sep 2027 / Q1 2028") == 202709   # month wins
    assert rdi._date_key("~ Jun 2027 / Q4 2027") == 202706
    assert rdi._date_key("Q1 2028") == 202802
    assert rdi._date_key("+10 business days") is None


def test_tables_fill_the_slide_before_splitting():
    """Client feedback: a table must use the WHOLE slide before a
    continuation slide is added. ~20 short rows are one full slide, never
    split across two half-empty ones (the old width heuristic split at ~10)."""
    rows = [[f"Deliverable pack {i:02d} with full acceptance criteria",
             "A/B/C-Sample"]
            for i in range(1, 19)]
    widths = [6.06, 6.06]
    budget = rdi.PAGE_H - rdi.FOOT_H - 0.25 - 1.55
    chunks = rdi._paginate_rows(rows, widths, rdi.TABLE_PT, budget,
                                header=["Deliverable", "Phase"])
    assert len(chunks) == 1                   # one full slide, no split


def test_long_table_paginates_at_the_fixed_size():
    """Type is FIXED: a table never rescales to dodge a page break.

    The deleted `_fit_pages` picked the largest font fitting within max_pages=2
    and broke on the first match — so it accepted 2 pages at 10.5pt for a table
    that fits ONE at 9.5pt (a real deck's slides 6-7, overflowing by 1.7%). A table
    that is genuinely too long now simply pages out at TABLE_PT."""
    assert not hasattr(rdi, "_fit_pages")     # the font ladder is gone for good
    rows = [["Deliverable pack with complete acceptance criteria and raw "
             "simulation data set", "A/B/C-Sample"]
            for _ in range(30)]
    widths = [6.06, 6.06]
    budget = rdi.PAGE_H - rdi.FOOT_H - 0.25 - 1.55
    chunks = rdi._paginate_rows(rows, widths, rdi.TABLE_PT, budget,
                                header=["Deliverable", "Phase"])
    assert len(chunks) >= 2                   # 30 long rows really don't fit
    assert sum(len(c) for c in chunks) == 30  # nothing dropped
    assert len(chunks[-1]) + 2 > len(chunks[-2])   # no thin orphan page


def test_row_height_wrap_simulation():
    """Row heights come from a word-wrap simulation, not raw char counts."""
    widths = [6.06, 6.06]
    short = ["Concept Release Report (D-01)", "Concept"]
    long_ = ["Cooling-system analysis report and simulation model covering "
             "water pump selection, thermostat performance, layout "
             "optimization and flow-target definition", "Concept"]
    h_short = rdi._row_height(short, widths, 10.5)
    h_long = rdi._row_height(long_, widths, 10.5)
    assert h_short == rdi.MIN_ROW_H           # one line -> declared minimum
    assert rdi.MIN_ROW_H < h_long < 3 * h_short   # wraps, but no blow-up


def test_timeline_pages_are_balanced():
    """8 milestones must paginate 4+4, never 7+1 with an orphan page."""
    q = _q(9, [{"layout": "timeline", "title": "Timing",
                "steps": [{"label": f"M{i}", "date": f"{i:02d}/2027",
                           "desc": ""} for i in range(1, 9)],
                "callout": None}])
    # the Timing section is 2 timeline pages, nothing else
    pages = _content_slides(q)
    assert len(pages) == 2
    labels = [f"M{i}" for i in range(1, 9)]
    assert len(_boxes(pages[0], labels)) == 4
    assert len(_boxes(pages[1], labels)) == 4


# ------------------------------------------------------------------- gantt
GANTT_QUESTION = _q(9, [{"layout": "gantt", "title": "Timing",
                "barLabel": "VHE30TD",
                "steps": [
                    {"label": "Kick-off", "date": "2026/7/15", "desc": ""},
                    {"label": "Technology Route Freeze", "date": "2026/9/15",
                     "desc": ""},
                    {"label": "CAE Complete", "date": "2026/11/15", "desc": ""},
                    {"label": "X0 Prototype Delivery", "date": "2026/12/15",
                     "desc": ""},
                    {"label": "JOB1 (SOP)", "date": "2027/12/30", "desc": ""},
                    {"label": "Kick-off trigger",
                     "date": "within 1 week of Letter of Intent", "desc": ""}],
                "callout": None}])


def test_gantt_renders_single_slide():
    """The gantt diagram is always ONE slide, whatever the milestone count."""
    assert len(_content_slides(GANTT_QUESTION)) == 1


def test_gantt_with_phase_bars_renders():
    q = {**GANTT_QUESTION,
         "slides": [{**GANTT_QUESTION["slides"][0],
                     "bars": [{"name": "Concept", "start": "Jul 2026",
                               "end": "Oct 2026"},
                              {"name": "A-Sample", "start": "Oct 2026",
                               "end": "Q1 2028"}]}]}
    assert len(_content_slides(q)) == 1


def test_gantt_falls_back_to_timeline_without_dates():
    """With <2 datable milestones there is no time axis — the classic
    milestone timeline is drawn instead of an empty grid."""
    q = _q(9, [{"layout": "gantt", "title": "Timing",
                "steps": [{"label": "Kick-off", "date": "TBD", "desc": ""},
                          {"label": "Deliverables",
                           "date": "+10 business days", "desc": ""}],
                "callout": None}])
    pages = _content_slides(q)               # must not raise
    assert len(pages) == 1
    assert _boxes(pages[0], ["Kick-off", "Deliverables"])


def test_time_pos_parses_common_date_forms():
    P = rdi._time_pos
    assert P("2026/7/15") == 2026 * 12 + 6 + 14 / 31
    assert P("2026-07-15") == P("2026/7/15") == P("15.07.2026")
    assert P("Jul 2026") == 2026 * 12 + 6
    assert P("15-Jul-2026") == P("2026/7/15")
    assert P("Q1 2028") == 2028 * 12
    assert P("Q1 2028", end=True) > P("Q1 2028")
    assert P("within 1 week of Letter of Intent") is None
    assert P("TBD") is None
    # chronological ordering is preserved across mixed formats
    seq = ["June 2026", "2026/9/15", "Q4 2026", "Jan 2027", "Q1 2028"]
    keys = [P(s) for s in seq]
    assert keys == sorted(keys)


def test_panel_layout_one_risk_group_per_slide():
    """Client format: Project Risks and Document Risks each on their own
    full-width panel slide."""
    q = _q(11, [
        {"layout": "panel", "title": "Risk Detection",
         "heading": "Project Risks",
         "items": ["Schedule: aggressive but plausible for the CAE "
                   "scope; little float in P1.",
                   "Result-owed performance obligation without "
                   "hardware control.",
                   "Open-ended test-support commitment."],
         "callout": None},
        {"layout": "panel", "title": "Risk Detection — Document Risks",
         "heading": "Document Risks",
         "items": ["Missing referenced documents (Annex X, Main "
                   "Contract).",
                   "Prototype naming inconsistency (X0 vs XD)."],
         "callout": {"tag": "NOTE", "text": "See section 9 for the "
                                            "timing reconstruction."}},
    ])
    slides = _content_slides(q)
    assert len(slides) == 2                   # one panel page per group
    assert _boxes(slides[0], ["Project Risks"])
    assert _boxes(slides[1], ["Document Risks"])
    # the Document Risks slide carries a callout in the plan; it is dead data —
    # the renderer draws no note block on a panel slide any more.
    assert "NOTE" not in {sh.text_frame.text for sh in slides[1].shapes
                          if sh.has_text_frame}


# ---------------------------------------------------------- geometry helpers
#
# The gantt tests above assert slide COUNT only, which is exactly why the
# crowded-milestone regression survived them. These helpers read back the
# rectangles the renderer actually declared (all derived from _text_w /
# _wrap_count, so they are deterministic) and let a test say "nothing
# overlaps" instead of "it didn't crash".

EMU = 914400.0
# Where a diagram's callout band starts (renderer.callout's default y):
# the content area ends at CONTENT_BOTTOM and the band is 0.7" tall.
CALLOUT_TOP = rdi.CONTENT_BOTTOM - 0.7


def _boxes(slide, texts=None):
    """[(text, left, top, width, height)] in inches, text-bearing shapes only.

    `texts` — an iterable of strings — keeps only boxes whose text matches.
    """
    keep = set(texts) if texts is not None else None
    out = []
    for sh in slide.shapes:
        if not sh.has_text_frame:
            continue
        t = sh.text_frame.text
        if not t or (keep is not None and t not in keep):
            continue
        out.append((t, sh.left / EMU, sh.top / EMU,
                    sh.width / EMU, sh.height / EMU))
    return out


def _autoshapes(slide, kind):
    """Shapes of one MSO_SHAPE type as (left, top, width, height) in inches."""
    out = []
    for sh in slide.shapes:
        try:
            if sh.auto_shape_type != kind:
                continue
        except (ValueError, AttributeError):
            continue          # pictures, connectors, textboxes: not autoshapes
        out.append((sh.left / EMU, sh.top / EMU,
                    sh.width / EMU, sh.height / EMU))
    return out


def _overlap(a, b):
    """Intersection area of two (.., left, top, w, h) rectangles."""
    ax, ay, aw, ah = a[-4:]
    bx, by, bw, bh = b[-4:]
    dx = min(ax + aw, bx + bw) - max(ax, bx)
    dy = min(ay + ah, by + bh) - max(ay, by)
    return dx * dy if dx > 0 and dy > 0 else 0.0


def _assert_no_overlap(boxes, tol=1e-4):
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            assert _overlap(a, b) <= tol, (
                f"{a[0]!r} @({a[-4]:.2f},{a[-3]:.2f} {a[-2]:.2f}x{a[-1]:.2f}) "
                f"overlaps {b[0]!r} @({b[-4]:.2f},{b[-3]:.2f} "
                f"{b[-2]:.2f}x{b[-1]:.2f})")


# The real 12 milestones from a real deck whose slide 15 was unreadable:
# five of them land inside a 0.78" span on a 12" axis. Bar names are chosen
# NOT to collide with any milestone label so the text filter stays exact.
CROWDED_STEPS = [
    ("RFQ / SOR release", "10-June-2026"),
    ("Quotation deadline", "20-June-2026"),
    ("Supplier tech clarification", "23-June-2026"),
    ("Concept release", "1-July-2026"),
    ("A-Sample design release", "15-July-2026"),
    ("A-Sample MRD", "15-Sept-2026"),
    ("B-Sample design release", "1-Nov-2026"),
    ("B-Sample MRD", "1-Jan-2027"),
    ("C-Sample design freeze", "1-Feb-2027"),
    ("C-Sample MRD", "15-May-2027"),
    ("First vehicle program SOP", "30-Aug-2027"),
    ("Project closure", "Sep-2027"),
]

CROWDED_GANTT = _q(9, [{
        "layout": "gantt", "title": "Timing",
        "steps": [{"label": lab, "date": dt, "desc": ""}
                  for lab, dt in CROWDED_STEPS],
        "bars": [{"name": "Alpha build", "start": "15-July-2026",
                  "end": "15-Sept-2026"},
                 {"name": "Beta build", "start": "1-Nov-2026",
                  "end": "1-Jan-2027"},
                 {"name": "Gamma build", "start": "1-Feb-2027",
                  "end": "15-May-2027"}],
        "callout": {"tag": "GAP", "text": "Kick-off is TBD, so the whole "
                                          "schedule clock is unanchored."}}],
                     confidence="high")


def _gantt_slide(question):
    pages = _content_slides(question)
    assert len(pages) == 1                    # the gantt is always one page
    return pages[0]


def test_time_pos_parses_hyphenated_month_year():
    """Regression: "Sep-2027" parsed as January 2027 because the month-year
    regex demanded whitespace. "Project closure" was then drawn on top of
    "B-Sample MRD / 1-Jan-2027", eight months out of place."""
    P = rdi._time_pos
    assert P("Sep-2027") == 2027 * 12 + 8
    assert P("Sep-2027") != P("1-Jan-2027")
    assert P("Sept/2027") == P("Sep-2027") == P("Sep 2027")
    assert P("Nov.2026") == 2026 * 12 + 10
    assert P("Sep-2027", end=True) > P("Sep-2027")
    assert rdi._date_key("Sep-2027") == 202709
    keys = [P(dt) for _, dt in CROWDED_STEPS]
    assert keys == sorted(keys)               # the deck's own order is correct


def test_gantt_milestone_labels_never_overlap():
    """The reported defect: 12 milestones, five of them inside 0.78", used to
    be stacked on top of each other by the "least-bad lane" fallback."""
    s = _gantt_slide(CROWDED_GANTT)
    labels = [lab for lab, _ in CROWDED_STEPS]
    boxes = _boxes(s, labels)
    assert sorted(b[0] for b in boxes) == sorted(labels)   # each exactly once
    _assert_no_overlap(boxes)
    _assert_no_overlap(_boxes(s, labels + [dt for _, dt in CROWDED_STEPS]))


def test_gantt_uses_legend_even_when_labels_would_fit():
    """Client-confirmed: the numbered-badge + legend format is unconditional,
    so four milestones a year apart — which the inline packer would have
    labelled directly — still get badges and a legend, not axis labels."""
    assert rdi.GANTT_ALWAYS_LEGEND
    q = _q(9, [{"layout": "gantt", "title": "Timing",
                "steps": [{"label": "Kick-off", "date": "Jan 2026",
                           "desc": ""},
                          {"label": "Concept gate", "date": "Jan 2027",
                           "desc": ""},
                          {"label": "Design freeze", "date": "Jan 2028",
                           "desc": ""},
                          {"label": "Start of production",
                           "date": "Jan 2029", "desc": ""}],
                "callout": None}])
    s = _gantt_slide(q)
    labels = ["Kick-off", "Concept gate", "Design freeze",
              "Start of production"]
    boxes = _boxes(s, labels)
    assert sorted(b[0] for b in boxes) == sorted(labels)   # each exactly once
    _assert_no_overlap(boxes)
    nums = [str(i) for i in range(1, 5)]
    assert {b[0] for b in _boxes(s, nums)} == set(nums)     # badges + legend
    assert len(_autoshapes(s, rdi.MSO_SHAPE.OVAL)) >= 4
    assert not (_autoshapes(s, rdi.MSO_SHAPE.DOWN_ARROW)
                + _autoshapes(s, rdi.MSO_SHAPE.UP_ARROW))


def test_gantt_switches_to_legend_when_crowded():
    """When direct labels provably cannot be packed without overlap, the axis
    carries numbered markers and the names move to a legend."""
    s = _gantt_slide(CROWDED_GANTT)
    nums = [str(i) for i in range(1, 13)]
    found = _boxes(s, nums)
    assert {b[0] for b in found} == set(nums)
    badges = _autoshapes(s, rdi.MSO_SHAPE.OVAL)
    assert len(badges) >= 12                  # 12 on the axis + 12 in legend
    _assert_no_overlap([("badge",) + b for b in badges])


def test_gantt_legend_lists_every_milestone():
    """24 milestones crammed into six months: every name still appears, once,
    inside the slide, and nothing overlaps."""
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]
    steps = [{"label": f"Milestone {i:02d}",
              "date": f"{1 + (i - 1) % 28}-{months[(i - 1) % 6]}-2027",
              "desc": ""} for i in range(1, 25)]
    q = _q(9, [{"layout": "gantt", "title": "Timing", "steps": steps,
                "callout": None}])
    s = _gantt_slide(q)
    names = [st["label"] for st in steps]
    boxes = _boxes(s, names)
    assert sorted(b[0] for b in boxes) == sorted(names)
    _assert_no_overlap(boxes)
    for _, lx, _, lw, _ in boxes:
        assert rdi.M - 0.1 <= lx and lx + lw <= rdi.PAGE_W - rdi.M + 0.1


def test_gantt_content_stays_above_the_callout():
    """Nothing the chart draws may run into the callout band — the old bar
    stack ran past it at high milestone counts."""
    s = _gantt_slide(CROWDED_GANTT)
    for sh in s.shapes:
        top, bot = sh.top / EMU, (sh.top + sh.height) / EMU
        if top < CALLOUT_TOP - 0.01:
            assert bot <= CALLOUT_TOP + 0.01, (
                f"a shape at {top:.2f} runs to {bot:.2f}, past the callout "
                f"band at {CALLOUT_TOP:.2f}")


def test_gantt_bars_fit_the_body_at_ten_bars():
    """Bar height had a 0.24" floor, so ten phase bars grew past the body and
    the baseline landed inside the stack. They now share the budget."""
    q = {**CROWDED_GANTT,
         "slides": [{**CROWDED_GANTT["slides"][0],
                     "bars": [{"name": f"Phase {i}", "start": "Jan 2027",
                               "end": "Jun 2027"} for i in range(10)]}]}
    s = _gantt_slide(q)
    bars = _autoshapes(s, rdi.MSO_SHAPE.PENTAGON)
    assert len(bars) == 10
    _assert_no_overlap([("bar",) + b for b in bars])
    assert max(t + h for _, t, _, h in bars) <= CALLOUT_TOP


PHASE_NAMES = ["Concept", "A-Sample", "B-Sample", "C-Sample", "D-Sample",
               "Validation", "Homologation", "Pre-series", "Ramp-up", "SOP",
               "Field support", "Closure"]


def _phases_slide(names, co=None):
    q = _q(6, [{"layout": "phases", "title": "Development Phases",
                "phases": [{"name": n, "desc": f"{n} gate review"}
                           for n in names],
                "callout": co}])
    pages = _content_slides(q)
    assert len(pages) == 1
    return pages[0]


def test_phases_renders_all_twelve():
    """The diagram used to be truncated to the first six phases, silently."""
    s = _phases_slide(PHASE_NAMES)
    chevrons = _autoshapes(s, rdi.MSO_SHAPE.CHEVRON)
    assert len(chevrons) == 12
    boxes = _boxes(s, PHASE_NAMES)
    assert sorted(b[0] for b in boxes) == sorted(PHASE_NAMES)
    assert len({round(t, 2) for _, t, _, _ in chevrons}) >= 2   # it wrapped
    assert max(t + h for _, t, _, h in chevrons) <= CALLOUT_TOP


def test_phases_six_stay_on_one_row():
    """Golden guard: the common six-phase deck keeps its exact geometry."""
    s = _phases_slide(PHASE_NAMES[:6])
    chevrons = _autoshapes(s, rdi.MSO_SHAPE.CHEVRON)
    assert len(chevrons) == 6
    assert {round(t, 3) for _, t, _, _ in chevrons} == {2.2}
    assert {round(h, 3) for _, _, _, h in chevrons} == {1.15}


# ------------------------------------------- fixed type + no note block
#
# Client requirements behind this block:
#   1. type is FIXED per layout family — the layout paginates, never the font;
#   2. table / ownership / bullets / panel slides carry NO note block, because
#      notes and gaps belong in id 11 Risk Detection.
# The two regressions they fix are one real deck's slides 6-7 (a 13-row
# table split in two) and 17-20 (8 risks per group split 6+2, twice).

# A 13-row Technical Product Definitions table taken from a real deck that
# rendered it across TWO slides. The content below is fictional; the row count
# and the text lengths are what the regression needs.
SAMPLE_TECH_ROWS = [
    ["System architecture",
     "Series hybrid front axle: S1 generator (ISG) + S3 front traction motor + "
     "single-speed gearbox + integrated housing + PCU"],
    ["PCU / control units",
     "One PCU box with 3 ECUs - RCU (range-extender coordinator + CAN gateway), "
     "GCU (S1 inverter/control), FMCU (S3 inverter/control + active discharge)"],
    ["S1 motor (generator)",
     "3-phase synchronous machine; peak 100 kW@30s, cont. 80 kW; 400 VDC "
     "(230-480); insulation class H; oil cooled; efficiency >=97.5%; NVH <=75 dBA"],
    ["S3 motor (traction)",
     "3-phase synchronous machine; peak 200 kW@30s, cont. 85 kW; max 18000 rpm; "
     "peak torque 4020 Nm@30s; cycle efficiency >=90%; regen + active discharge"],
    ["Transmission",
     "Single-speed / two-stage helical; gear ratio ref ~10.4; avg efficiency "
     ">=96%, max >=98%; integrated with S1/S3 motors"],
    ["HV / LV", "HV 400 VDC nominal; LV 12 V control supply"],
    ["IP rating", "IP67 target at PCU box level"],
    ["Functional safety",
     "ISO 26262; PCU/ECU target ASIL C; safety goals span ASIL B-C"],
    ["Software scope",
     "23 control functions (CF-01...CF-23); AUTOSAR 'must have'; UDS/OBD; "
     "FOTA/OTA calibration; 25+ calibration parameters"],
    ["Communication",
     "Dual CAN - vehicle bus (vehicle/PCU) and range bus (PCU/engine bay/EMS); "
     "RCU gateway, E2E protection"],
    ["Safety protections",
     "8 range-extender protection functions (crash, insulation, comm fault, "
     "over-temp, low oil, over-voltage, etc.)"],
    ["Applicable programs", "Model A, Model B, Model C, Model D hybrid variants"],
    ["Explicit scope boundary",
     "ICE engine and EMS NOT in scope - treated as external ECUs interfaced "
     "via the range bus"],
]


# The 8 Project Risks from the same deck, which the old renderer split 6 + 2.
# Fictional content, real shape.
SAMPLE_PROJECT_RISKS = [
    "Schedule not feasible as stated: clean-sheet series-hybrid axle needs "
    "concept to C-sample in ~7 months vs typical 18-36; renegotiate before quoting.",
    "Undefined start / floating anchor: kick-off and nomination TBD while "
    "downstream sample dates fixed - all schedule risk sits with the supplier.",
    "Pervasive TBD targets: all 7.1 vehicle parameters, S1 peak torque, ratio, "
    "oil spec, weights and safety level TBD - effort cannot be firmly priced.",
    "Unbounded quantities: test-unit counts, simulation loops, 23+ control "
    "functions and 25+ calibration parameters open-ended.",
    "Dependency on customer inputs & external EMS: key inputs due 'Kick-off'/"
    "TBD; AVL must integrate against an EMS/ICE it neither develops nor owns.",
    "IP / know-how transfer: D-51 requires transfer of IP and know-how incl. "
    "source code; potential full foreground-IP assignment to be negotiated.",
    "Functional safety without agreed DIA: ASIL C work products owed 'as "
    "agreed in DIA', but no DIA attached - safety-work-product split undefined.",
    "Optional/undefined commercial scope: prototype procurement 'optional'; "
    "10 leaves procurement and test execution TBD; no rate card provided.",
]


def _table_run_sizes(slide, body_only=True):
    """Point sizes of the runs inside every table on a slide."""
    out = []
    for sh in slide.shapes:
        if not getattr(sh, "has_table", False):
            continue
        for ri, row in enumerate(sh.table.rows):
            if body_only and ri == 0:
                continue                      # header renders at cell_size+0.5
            for cell in row.cells:
                for p in cell.text_frame.paragraphs:
                    out += [r.font.size.pt for r in p.runs if r.font.size]
    return out


def _textbox_run_sizes(slide):
    """Point sizes of the runs inside plain textboxes (bullets, panel items)."""
    out = []
    for sh in slide.shapes:
        if not sh.has_text_frame or getattr(sh, "has_table", False):
            continue
        for p in sh.text_frame.paragraphs:
            out += [r.font.size.pt for r in p.runs if r.font.size]
    return out


def test_thirteen_row_table_fits_one_slide():
    """Regression, a real deck's slides 6-7: the 13 Technical Definitions rows fit
    ONE slide at TABLE_PT. They were split because the font ladder stopped at
    the first size fitting <=2 pages, 1.7% over budget at 10.5pt."""
    q = _q(3, [{"layout": "table",
                "title": "Technical Product Definitions and Targets",
                "columns": ["Parameter", "Definition / Target"],
                "rows": SAMPLE_TECH_ROWS}])
    slides = _content_slides(q)
    assert len(slides) == 1
    assert not _boxes(slides[0], ["Technical Product Definitions and Targets "
                                  "(cont.)"])
    assert len(_table_run_sizes(slides[0])) == 2 * len(SAMPLE_TECH_ROWS)


def test_eight_risk_items_fit_one_panel():
    """Regression, a real deck's slides 17-20: a risk group is never pre-split, and
    8 substantial risks measure 3.76" against a 4.19" panel — one slide."""
    q = _q(11, [{"layout": "panel", "title": "Risk Detection",
                 "heading": "Project Risks", "items": SAMPLE_PROJECT_RISKS}])
    slides = _content_slides(q)
    assert len(slides) == 1
    texts = {sh.text_frame.text for sh in slides[0].shapes if sh.has_text_frame}
    assert "Project Risks" in texts            # heading, with no "(cont.)"
    assert not any("(cont.)" in t for t in texts)


def test_panel_paginates_on_real_overflow():
    """Fixed type means overflow is handled by ADDING a slide. Both the title
    and the panel heading get the "(cont.)" suffix, and no item is dropped."""
    items = [f"Risk {i:02d}: " + "a genuinely long risk statement that wraps "
             "onto two full lines of the panel " * 2 for i in range(1, 21)]
    q = _q(11, [{"layout": "panel", "title": "Risk Detection",
                 "heading": "Project Risks", "items": items}])
    slides = _content_slides(q)
    assert len(slides) >= 2
    texts = [{sh.text_frame.text for sh in s.shapes if sh.has_text_frame}
             for s in slides]
    assert "Risk Detection" in texts[0] and "Project Risks" in texts[0]
    assert "Risk Detection (cont.)" in texts[1]
    assert "Project Risks (cont.)" in texts[1]
    rendered = " ".join(t for page in texts for t in page)
    for i in range(1, 21):
        assert f"Risk {i:02d}:" in rendered    # nothing fell off the deck


def test_type_size_is_fixed_across_content_volume():
    """A 5-row table and a 25-row table render at the SAME size — the client's
    core requirement: type is constant, the layout adapts."""
    def sizes(n):
        q = _q(8, [{"layout": "table", "title": "AVL Deliverables",
                    "columns": ["Deliverable", "Phase / Task"],
                    "rows": [[f"Deliverable pack {i:02d} with the full "
                              f"report, raw data and scripts",
                              "A/B/C-Sample"] for i in range(n)]}])
        return {sz for s in _content_slides(q) for sz in _table_run_sizes(s)}

    assert sizes(5) == sizes(25) == {rdi.TABLE_PT}


def test_panel_and_bullet_sizes_are_the_declared_constants():
    q_panel = _q(11, [{"layout": "panel", "title": "Risk Detection",
                       "heading": "Project Risks",
                       "items": SAMPLE_PROJECT_RISKS[:4]}])
    q_bul = _q(12, [{"layout": "bullets", "title": "Source Material",
                     "bullets": [{"text": f"RFQ_Annex_{i}.pdf"}
                                 for i in range(6)]}])
    panel = _textbox_run_sizes(_content_slides(q_panel)[0])
    bul = _textbox_run_sizes(_content_slides(q_bul)[0])
    # the 14pt panel heading and the auto-sized slide title live in the same
    # shape list, so assert the constants are PRESENT and the item sizes are
    # the only ones in the body range.
    assert rdi.PANEL_PT in panel and rdi.BULLET_PT in bul
    assert rdi.PANEL_PT != rdi.BULLET_PT       # families differ, on purpose


def test_data_slides_have_no_note_block():
    """table / ownership / bullets / panel reserve NO callout band: a plan that
    still carries one renders zero note shapes and the content uses the space."""
    q = _q(10, [
        {"layout": "table", "title": "Demo",
         "columns": ["Key", "Value"],
         "rows": [[f"Row {i:02d}", "Value"] for i in range(16)],
         "callout": {"tag": "GAP", "text": "This must not be drawn."}},
        {"layout": "bullets", "title": "Demo — Bullets",
         "bullets": [{"text": f"Point {i}"} for i in range(6)],
         "callout": {"tag": "NOTE", "text": "This must not be drawn."}},
        {"layout": "panel", "title": "Demo — Panel", "heading": "Project Risks",
         "items": SAMPLE_PROJECT_RISKS[:4],
         "callout": {"tag": "NOTE", "text": "This must not be drawn."}},
        {"layout": "ownership", "title": "Demo — Ownership", "customerAbbr": "VF",
         "columns": ["Scope of Work", "Concept", "A-Sample"],
         "rows": [[f"Task {i:02d}", "AVL", "VF"] for i in range(16)],
         "callout": {"tag": "GAP", "text": "This must not be drawn."}},
    ])
    slides = _content_slides(q)
    assert len(slides) == 4
    for s in slides:
        assert not _boxes(s, ["GAP", "NOTE", "This must not be drawn."])
    # The reclaimed band is actually USED, not just left blank. The panel body
    # rect is measurable directly; a table's frame height is only a declared
    # minimum (PowerPoint grows rows at render time), so prove it on the
    # paginator instead: rows that need the full height stay on one slide but
    # would have spilled to a second under the old note-band budget.
    panel_bottom = max(t + h for _, t, _, h
                       in _autoshapes(slides[2], rdi.MSO_SHAPE.RECTANGLE))
    assert panel_bottom > CALLOUT_TOP

    widths = [6.06, 6.06]
    full = rdi.PAGE_H - rdi.FOOT_H - 0.25 - 1.55        # today: no note band
    with_note = full - 0.70                             # old: note band cost
    rows = [[f"Deliverable pack {i:02d} with the full report and raw data",
             "A/B/C-Sample"] for i in range(18)]
    assert len(rdi._paginate_rows(rows, widths, rdi.TABLE_PT, full,
                                  header=["Deliverable", "Phase"])) == 1
    assert len(rdi._paginate_rows(rows, widths, rdi.TABLE_PT, with_note,
                                  header=["Deliverable", "Phase"])) == 2


def _notes(slide):
    """The speaker notes of a slide, or None when it has none."""
    if not slide.has_notes_slide:
        return None
    return slide.notes_slide.notes_text_frame.text


def test_speaker_notes_carry_the_confidence_reason_and_the_sources():
    """A data slide shows no note band, but it DOES carry speaker notes:
    the section's first page gets the confidence reason (its "Why this
    rating:" lead-in rewritten, the generic "How the rating works" tail
    dropped) plus the complete source references; every later page of the
    section repeats the references only."""
    q = _q(8, [{"layout": "table", "title": "AVL Deliverables",
                "columns": ["Deliverable", "Phase"],
                "rows": [[f"Deliverable pack {i:02d} with the full report, "
                          "raw data and the scripts", "A/B/C-Sample"]
                         for i in range(40)]}],
           confidence="medium",
           confidenceNotes="Why this rating: the deliverable list is explicit "
                           "but the acceptance criteria are not."
                           "\n\nHow the rating works: high means ...",
           sourceDetails="Sources: RFQ_Main.pdf p. 12-14; Annex_B.xlsx "
                         "sheet 'Deliverables'")
    pages = _content_slides(q)
    assert len(pages) >= 2                     # 40 long rows paginate
    first = _notes(pages[0])
    assert first.startswith("Reason: the deliverable list is explicit")
    assert "Why this rating" not in first
    assert "How the rating works" not in first
    assert "Sources: RFQ_Main.pdf p. 12-14" in first
    for later in pages[1:]:
        assert _notes(later) == q["sourceDetails"]


def test_speaker_notes_fall_back_to_the_sources_and_honour_slide_overrides():
    """Without a rating the first page's notes are the references alone; a
    slide-level sourceDetails (a follow-up's own references) replaces the
    section's on that slide only."""
    q = _q(11, [{"layout": "panel", "title": "Risk Detection",
                 "heading": "Project Risks", "items": ["Schedule is tight."]},
                {"layout": "panel", "title": "Risk Detection — Document Risks",
                 "heading": "Document Risks", "items": ["Annex X missing."],
                 "sourceDetails": "Sources: Annex_X.pdf (referenced, not "
                                  "supplied)"}],
           sourceDetails="Sources: RFQ_Main.pdf p. 3")
    pages = _content_slides(q)
    assert len(pages) == 2
    assert _notes(pages[0]) == "Sources: RFQ_Main.pdf p. 3"
    assert _notes(pages[1]) == "Sources: Annex_X.pdf (referenced, not supplied)"


def test_slides_without_notes_or_sources_get_no_speaker_notes():
    """Nothing attached (neither confidenceNotes nor sourceDetails nor a
    sourceLine) -> the renderer writes no notes slide at all, on data and
    diagram layouts alike."""
    q_data = _q(10, [{"layout": "table", "title": "Customer Specific Standards",
                      "columns": ["Standard", "Scope"],
                      "rows": [["ISO 26262", "FuSa"]]}])
    q_diag = _q(6, [{"layout": "phases", "title": "Development Phases",
                     "phases": [{"name": "Concept", "desc": "Gate 1"}],
                     "callout": {"tag": "NOTE", "text": "A visible callout."}}])
    for q in (q_data, q_diag):
        for page in _content_slides(q):
            assert _notes(page) is None
    # ... and a callout is never promoted into the notes: it is drawn
    diag = _content_slides(q_diag)[0]
    assert _boxes(diag, ["A visible callout."])


def test_diagram_slides_keep_their_callout():
    """The note block is removed from DATA slides only — on a diagram it
    annotates the picture, so collab/phases/gantt/timeline keep it."""
    s = _phases_slide(PHASE_NAMES[:4],
                      co={"tag": "NOTE", "text": "Referenced only: D-Sample."})
    assert _boxes(s, ["NOTE"])
    assert _boxes(s, ["Referenced only: D-Sample."])
    assert _boxes(_gantt_slide(CROWDED_GANTT), ["GAP"])


def test_time_pos_parses_german_and_extended_forms():
    """Client feedback: Gantt positions must be time-accurate. German month
    names, calendar weeks, half-years and US-ordered dates all place
    correctly instead of falling through to a wrong year-level guess."""
    P = rdi._time_pos
    # German month names (bilingual corpora)
    assert P("Okt 2026") == P("Oct 2026") == 2026 * 12 + 9
    assert P("Dez. 2026") == P("Dec 2026")
    assert P("März 2027") == P("Maerz 2027") == P("Mrz 2027") == P("Mar 2027")
    assert P("Mai 2027") == P("May 2027")
    assert P("15. Okt 2026") == P("15-Oct-2026")
    # calendar weeks and half-years
    from rfq.dates import WEEK_MONTHS   # the parser lives in dates.py now
    assert P("KW 38/2026") == 2026 * 12 + 37 * WEEK_MONTHS
    assert P("CW38 2026") == P("KW 38/2026")
    assert abs(P("KW 27/2026") - (2026 * 12 + 6)) < 0.15   # ~ start of July
    assert P("H1 2027") == 2027 * 12
    assert P("H2 2027") == 2027 * 12 + 6
    assert P("H1 2027", end=True) < P("H2 2027")
    # deterministic anchors for fuzzy year qualifiers (10% / 50% / 92%)
    assert P("early 2027") == 2027 * 12 + 0.10 * 12
    assert P("mid 2027") == 2027 * 12 + 0.50 * 12
    assert P("end of 2027") == P("Ende 2027") == P("late 2027") \
        == 2027 * 12 + 0.92 * 12


def test_time_pos_qualifiers_apply_to_any_span():
    """Client feedback: early/mid/late (and Anfang/Mitte/Ende) must order
    correctly at EVERY granularity — the same word anchors at the same
    fraction of whatever span it qualifies (month, quarter, half-year,
    year), so qualified dates sort correctly against day-level dates."""
    P = rdi._time_pos
    # month-level qualifiers vs a day-level date in the same month
    assert P("early September 2027") < P("2027/9/15") < P("mid September 2027") \
        < P("late September 2027") < P("Oct 2027")
    assert P("Ende September 2027") == P("late September 2027")
    assert P("Anfang Okt 2026") < P("2026/10/20") < P("Ende Okt 2026")
    # quarter-level qualifiers stay inside their quarter, in order
    assert P("Q2 2027") < P("early Q2 2027") < P("mid Q2 2027") \
        < P("late Q2 2027") < P("Q3 2027")
    assert P("mid Q2 2027") == 2027 * 12 + 3 + 1.5
    assert P("end of Q1 2028") < P("Q2 2028")
    # half-year qualifiers
    assert P("H1 2027") < P("mid H1 2027") < P("H2 2027")
    # a qualified span still beats the end=True bar convention only via end
    assert P("Sep 2027", end=True) > P("late September 2027")
    # full ordering across mixed granularities and languages
    seq = ["Anfang 2026", "early Q2 2026", "2026/5/10", "mid 2026",
           "late Q3 2026", "Anfang Okt 2026", "2026/10/20", "Ende Okt 2026",
           "Ende 2026", "early January 2027"]
    keys = [P(x) for x in seq]
    assert None not in keys
    assert keys == sorted(keys)


def test_time_pos_rejects_invalid_dates_instead_of_clamping():
    """Regression guard: '07/15/2026' is US month-first (month 15 does not
    exist) — the old parser clamped it to December, eight months out of
    place. Truly invalid parts now return None (disclosed, never mis-drawn)."""
    P = rdi._time_pos
    assert P("07/15/2026") == P("15.07.2026")     # US order disambiguated
    assert P("2026/7/15") == P("07/15/2026")
    assert P("2026/15/07") == P("2026/7/15")      # yyyy/dd/mm salvaged
    # both fields impossible as a month -> falls back to the year, start-of
    assert P("45/45/2026") == 2026 * 12
    # chronological ordering across ALL supported forms (spans key on their
    # start: H2 2026 anchors at July, just before the 2026/7/15 milestone)
    seq = ["KW 5/2026", "März 2026", "May 2026", "H2 2026", "2026/7/15",
           "KW 38/2026", "Okt 2026", "Dez 2026", "Q1 2027", "early 2027",
           "mid 2027", "H2 2027", "Ende 2027"]
    keys = [P(x) for x in seq]
    assert None not in keys
    assert keys == sorted(keys)


def _slide_texts(slide):
    return [sh.text_frame.text for sh in slide.shapes if sh.has_text_frame]


def test_gantt_separates_phases_and_milestones_zones():
    """Client feedback: milestones and phases are visually separated — the
    Gantt carries a PHASES swimlane caption over the bar block and a
    MILESTONES caption over the badge/legend zone."""
    q = {**GANTT_QUESTION,
         "slides": [{**GANTT_QUESTION["slides"][0],
                     "bars": [{"name": "Concept", "start": "Jul 2026",
                               "end": "Oct 2026"},
                              {"name": "A-Sample", "start": "Oct 2026",
                               "end": "Q1 2028"}]}]}
    texts = _slide_texts(_gantt_slide(q))
    assert any(t == "PHASES" for t in texts)
    assert any(t == "MILESTONES" for t in texts)
    # single project bar -> PROJECT caption instead of PHASES
    texts2 = _slide_texts(_gantt_slide(GANTT_QUESTION))
    assert any(t == "PROJECT" for t in texts2)
    assert any(t == "MILESTONES" for t in texts2)


# ------------------------------------------------- confidence chip (score)
def _chip_shapes(slide):
    """The chip's text and its fill colour(s) on a slide holding only it."""
    texts = [sh.text_frame.text for sh in slide.shapes
             if sh.has_text_frame and sh.text_frame.text]
    fills = [str(sh.fill.fore_color.rgb) for sh in slide.shapes
             if sh.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE]
    return texts, fills


@pytest.mark.parametrize("conf, score, expected", [
    ("high", 10, "High · 10/10"),
    ("medium", 7, "Medium · 7/10"),
    ("low", 2, "Low · 2/10"),
    ("medium", None, "Medium"),
    ("HIGH", 8, "High · 8/10"),
])
def test_confidence_chip_shows_band_word_and_score(conf, score, expected):
    s = rdi.slide(Presentation())
    rdi._confidence_chip(s, conf, score)
    texts, fills = _chip_shapes(s)
    assert texts == [expected]
    assert fills == [rdi.CONF_COLORS[conf.lower()]]       # colours unchanged
    assert rdi._text_w(expected, 9, bold=True) < rdi.CHIP_W - 0.1


def test_confidence_chip_without_a_known_band_draws_nothing():
    s = rdi.slide(Presentation())
    rdi._confidence_chip(s, "", 7)
    assert list(s.shapes) == []


def test_confidence_chip_reads_the_question_score_on_every_page():
    rows = [[f"Parameter {i}", "x " * 40] for i in range(40)]
    pages = _content_slides(_q(3, [{"layout": "table", "title": TITLES[3][0],
                                    "columns": ["Parameter", "Target"],
                                    "rows": rows}],
                               confidence="medium", score=6))
    assert len(pages) > 1
    for page in pages:
        assert "Medium · 6/10" in _slide_texts(page)


# ------------------------------------------------------ gradient memoisation
def _old_gradient_pixel(stops, t):
    """The per-pixel formula of the original loop implementation."""
    n = len(stops) - 1
    seg = min(int(t * n), n - 1)
    lt = t * n - seg
    c0, c1 = stops[seg], stops[seg + 1]
    return tuple(int(c0[i] + (c1[i] - c0[i]) * lt) for i in range(3))


def _old_gradient(stops, w, h, vertical):
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            t = (y / (h - 1)) if vertical else (x / (w - 1))
            px[x, y] = _old_gradient_pixel(stops, t)
    return img


@pytest.mark.parametrize("w, h, vertical", [(97, 5, False), (6, 83, True),
                                            (1600, 40, False)])
def test_gradient_matches_the_per_pixel_reference(w, h, vertical):
    new = Image.open(rdi._gradient_png(rdi.BRAND_STOPS, w, h, vertical))
    assert new.size == (w, h)
    old = _old_gradient(rdi.BRAND_STOPS, w, h, vertical)
    new_px, old_px = new.convert("RGB").load(), old.load()
    for y in range(h):
        for x in range(w):
            assert all(abs(a - b) <= 1
                       for a, b in zip(new_px[x, y], old_px[x, y])), (x, y)


def test_cover_gradient_corners_and_midpoint_match_the_reference():
    img = Image.open(rdi.GRAD_COVER()).convert("RGB")
    w, h = img.size
    assert (w, h) == (1920, 1080)
    for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1),
                 (w // 2, h // 2)):
        expected = _old_gradient_pixel(rdi.BRAND_STOPS, x / (w - 1))
        assert all(abs(a - b) <= 1
                   for a, b in zip(img.getpixel((x, y)), expected)), (x, y)


def test_gradient_is_painted_once_per_size_and_streams_are_fresh():
    rdi._gradient_bytes.cache_clear()
    first, second = rdi.GRAD_BAR(), rdi.GRAD_BAR()
    assert first is not second
    assert first.tell() == 0 and second.tell() == 0
    assert first.getvalue() == second.getvalue()
    info = rdi._gradient_bytes.cache_info()
    assert (info.misses, info.hits) == (1, 1)
    # list stops and tuple stops share one cache entry and one bytes object
    key = tuple(tuple(c) for c in rdi.BRAND_STOPS)
    assert rdi._gradient_bytes(key, 1600, 40, False) is \
        rdi._gradient_bytes(key, 1600, 40, False)
    rdi._gradient_png([list(c) for c in rdi.BRAND_STOPS], w=1600, h=40)
    assert rdi._gradient_bytes.cache_info().misses == 1
    rdi.GRAD_COVER(); rdi.GRAD_COVER()
    assert rdi._gradient_bytes.cache_info().misses == 2


def test_twelve_section_sample_deck_renders_quickly():
    plan = sample_plan()
    plan["date"] = "2026-10-14"
    for q in plan["questions"]:
        q.update(confidence="medium", score=6)
    plan = SlidePlan.model_validate(plan).model_dump()
    rdi._gradient_bytes.cache_clear()           # cold: paints every gradient
    start = time.perf_counter()
    deck = rdi.render_to_bytes(plan)
    elapsed = time.perf_counter() - start
    assert deck.startswith(b"PK")
    assert elapsed < 4.0, f"render took {elapsed:.2f} s"


# ---------------------------------------------------- visible (inferred) tag
def _runs(paragraph):
    return [(r.text, str(r.font.color.rgb)) for r in paragraph.runs]


def _table_cell(slide, row, col):
    table = next(sh.table for sh in slide.shapes
                 if getattr(sh, "has_table", False))
    return table.cell(row, col).text_frame.paragraphs[0]


def _paragraph_with(slide, needle):
    return next(p for sh in slide.shapes
                if sh.has_text_frame and not getattr(sh, "has_table", False)
                for p in sh.text_frame.paragraphs if needle in p.text)


def test_table_cell_inferred_tag_is_an_amber_run():
    [page] = _content_slides(_q(3, [{
        "layout": "table", "title": TITLES[3][0],
        "columns": ["Parameter", "Target"],
        "rows": [["Power", "220 kW (inferred)"], ["Torque", "400 Nm"]]}]))
    assert _runs(_table_cell(page, 1, 1)) == [("220 kW ", rdi.INK),
                                              ("(inferred)", rdi.AMBER)]
    assert _runs(_table_cell(page, 2, 1)) == [("400 Nm", rdi.INK)]
    assert _table_cell(page, 1, 1).runs[1].font.size.pt == rdi.TABLE_PT


def test_inferred_tag_mid_cell_keeps_the_text_around_it():
    [page] = _content_slides(_q(4, [{
        "layout": "table", "title": TITLES[4][0],
        "columns": ["Variant", "Powertrain"],
        "rows": [["Model A", "BEV (Inferred) and PHEV"]]}]))
    assert _runs(_table_cell(page, 1, 1)) == [
        ("BEV ", rdi.INK), ("(Inferred)", rdi.AMBER), (" and PHEV", rdi.INK)]


def test_owner_cells_stay_one_white_run():
    [page] = _content_slides(_q(7, [{
        "layout": "ownership", "title": TITLES[7][0], "customerAbbr": "LI",
        "columns": ["Scope of Work", "Concept"],
        "rows": [["Cooling jacket (inferred)", "AVL"]], "callout": None}]))
    assert _runs(_table_cell(page, 1, 1)) == [("AVL", rdi.WHITE)]
    assert _runs(_table_cell(page, 1, 0)) == [("Cooling jacket ", rdi.INK),
                                              ("(inferred)", rdi.AMBER)]


def test_panel_item_inferred_tag_is_an_amber_run():
    pages = _content_slides(_q(11, [
        {"layout": "panel", "title": "Risk Detection",
         "heading": "Project Risks",
         "items": ["Bench capacity is short (inferred)"]},
        BASELINE_SLIDES[11][1]]))
    p = _paragraph_with(pages[0], "Bench capacity")
    assert _runs(p)[1:] == [("Bench capacity is short ", rdi.INK),
                            ("(inferred)", rdi.AMBER)]


@pytest.mark.parametrize("bullet", [
    {"text": "RFQ.pdf", "inferred": True},
    {"text": "RFQ.pdf (inferred)", "inferred": True},
    {"text": "RFQ.pdf (inferred)"},
])
def test_bullet_inferred_tag_is_one_amber_run(bullet):
    [page] = _content_slides(_q(12, [{"layout": "bullets",
                                      "title": "Source Material",
                                      "bullets": [bullet]}]))
    p = _paragraph_with(page, "RFQ.pdf")
    runs = _runs(p)
    assert runs[1][0].rstrip() == "RFQ.pdf"
    assert runs[1][1] == rdi.INK
    assert runs[2:] == [("(inferred)", rdi.AMBER)]


def test_additional_information_notes_keep_the_confidence_block():
    """Section 13: the first page of each follow-up carries the question's
    confidence block followed by that follow-up's own sources (the
    question-level sources are not repeated); a continuation page of a
    follow-up keeps its sources only."""
    from rfq.schema import ADDITIONAL_INFO_ID, ADDITIONAL_INFO_TITLE
    head = ("Confidence 8/10 (High)\n"
            'Follow-up 1 "Warranty?": 9/10\n'
            "-1  G3  1 inferred item: the term (SOR 4)\n"
            'Follow-up 2 "Tooling?": 8/10\n'
            "-2  G5  evidence sits in a partly readable file: annex\n"
            "Check: no statements were selected for a second review.")
    first = "Sources:\n\nFile: SOR.pdf\n  Page: 4"
    second = "Sources:\n\nFile: Annex.pdf\n  Page: 2"
    extra = {"number": ADDITIONAL_INFO_ID,
             "titleEn": ADDITIONAL_INFO_TITLE[0],
             "titleDe": ADDITIONAL_INFO_TITLE[1],
             "confidence": "high", "score": 8,
             "confidenceNotes": head + "\n\nSources:\n\nFile: SOR.pdf\n  Page: 4"
                                "\n\nFile: Annex.pdf\n  Page: 2",
             "sourceDetails": "Sources:\n\nFile: SOR.pdf\n  Page: 4\n\n"
                              "File: Annex.pdf\n  Page: 2",
             "slides": [
                 {"layout": "panel", "title": ADDITIONAL_INFO_TITLE[0],
                  "heading": "Warranty?", "items": ["Two years."],
                  "sourceLine": "Source: SOR.pdf p. 4", "sourceDetails": first},
                 {"layout": "panel", "title": ADDITIONAL_INFO_TITLE[0],
                  "heading": "Tooling?",
                  "items": [f"Tooling item {i:02d} is supplied by the customer "
                            "and stays at the supplier plant until SOP."
                            for i in range(40)],
                  "sourceLine": "Source: Annex.pdf p. 2",
                  "sourceDetails": second}]}
    good = _plan_with()
    questions = good["questions"][:-1] + [extra] + good["questions"][-1:]
    plan = SlidePlan.model_validate(dict(good, questions=questions)).model_dump()
    slides = list(rdi.create_presentation(plan).slides)
    before = 2 + sum(BASELINE_PAGES.get(n, 1) for n in SECTION_IDS if n < 12)
    pages = slides[before:len(slides) - 1 - BASELINE_PAGES.get(12, 1)]
    assert len(pages) >= 3                     # 40 items paginate
    assert _notes(pages[0]) == head + "\n\n" + first
    assert _notes(pages[1]) == head + "\n\n" + second
    for later in pages[2:]:
        assert _notes(later) == second
