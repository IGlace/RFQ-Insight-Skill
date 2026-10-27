"""Tests for the RFQ Insight renderer's deterministic helpers.

Ported from RFQ_Container_App/tests/test_insight_renderer.py and kept to the
behaviours that do not depend on a complete slide plan: table pagination at
a fixed type size, row-height simulation, chronological sorting and the one
date parser. Whole-deck rendering is exercised by the runner on real
packages; `rfq_run.py render` replays a stored run report.
"""

import pytest

from rfq import renderer as rdi
from rfq.schema import SlidePlan, TITLES


def test_canonical_titles_cover_all_twelve_sections():
    assert sorted(TITLES) == list(range(1, 13))
    assert TITLES[12][0] == "Source Material"
    assert all(len(pair) == 2 and all(pair) for pair in TITLES.values())


def test_schema_rejects_unknown_layout():
    bad = {
        "projectName": "Demo", "date": "2026-07-23",
        "questions": [{"number": 1, "titleEn": "T", "titleDe": "T",
                       "slides": [{"layout": "nope", "title": "x"}]}],
    }
    with pytest.raises(Exception):
        SlidePlan.model_validate(bad)


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
    assert len(chunks) == 1


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
    assert len(chunks[-1]) + 2 > len(chunks[-2])


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
    assert rdi.MIN_ROW_H < h_long < 3 * h_short


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
    assert keys == sorted(keys)


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


from rfq import branding


@pytest.fixture(autouse=True)
def no_identity(monkeypatch, tmp_path):
    """Every deck in this module resolves its footer identity; keep that
    independent of the machine (no env variables, an empty toolbox home)."""
    monkeypatch.setenv("RFQ_INSIGHT_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("RFQ_INSIGHT_AUTHOR", raising=False)
    monkeypatch.delenv("RFQ_INSIGHT_DEPARTMENT", raising=False)


def _plan(**extra):
    return {"projectName": "Demo", "date": "2026-10-23", "questions": [], **extra}


def _full_plan(section_slides):
    """A schema-valid plan with all twelve sections: each gets one bullets
    slide titled like the section unless `section_slides` overrides it
    ({section number: [slide dicts]})."""
    default = lambda n: [{"layout": "bullets", "title": TITLES[n][0],
                          "bullets": [{"text": "x"}]}]
    questions = [{"number": n, "titleEn": TITLES[n][0], "titleDe": TITLES[n][1],
                  "slides": section_slides.get(n) or default(n)}
                 for n in sorted(TITLES)]
    plan = {"projectName": "Demo", "date": "2026-10-23", "questions": questions}
    return SlidePlan.model_validate(plan).model_dump()


def test_split_slide_is_a_continuation_of_opportunity_info():
    plan = _full_plan({1: [{"layout": "opportunity", "title": "Opportunity Info",
                            "columns": ["Opportunity Info", "Definition according to RFQ"],
                            "rows": [["Customer", "Northwind"]]},
                           {"layout": "split", "title": "Products & Skills (%)",
                            "products": [["Battery", "60%"]], "skills": [["Design", "100%"]]}]})
    prs = rdi.create_presentation(plan)
    titles = [s.shapes.title.text for s in list(prs.slides)[1:] if s.shapes.title]
    assert titles[:3] == ["Table of Contents", "Opportunity Info", "Opportunity Info (cont.)"]
    split = list(prs.slides)[3]
    assert any(sh.has_text_frame and sh.text_frame.text == "Products & Skills (%)" for sh in split.shapes)
    toc = list(prs.slides)[1]
    assert not any(sh.has_text_frame and "Products" in sh.text_frame.text for sh in toc.shapes)

def test_deck_is_built_on_the_avl_master():
    prs = rdi.create_presentation(_plan(author="K. Petinger", department="LBP"))
    slides = list(prs.slides)
    assert slides[0].slide_layout.name == branding.LAYOUT_COVER
    assert slides[1].slide_layout.name == branding.LAYOUT_CONTENT       # TOC
    assert slides[1].shapes.title.text == "Table of Contents"
    assert slides[-2].slide_layout.name == branding.LAYOUT_END
    box = next(s for s in prs.slide_masters[0].shapes if s.name == "footer_ProjectInfo")
    assert box.text_frame.text == "K. Petinger | LBP | 23 October 2026 |"

def test_page_size_matches_the_template():
    prs = branding.load_template()
    assert abs(prs.slide_width / 914400 - rdi.PAGE_W) < 0.01
    assert abs(prs.slide_height / 914400 - rdi.PAGE_H) < 0.01

def test_title_placeholder_sits_above_the_content_origin():
    prs = rdi.create_presentation(_plan())
    toc = list(prs.slides)[1]
    bottom = (toc.shapes.title.top + toc.shapes.title.height) / 914400
    assert bottom <= rdi.CONTENT_TOP

def test_missing_identity_falls_back_without_error(no_identity):
    prs = rdi.create_presentation(_plan())
    box = next(s for s in prs.slide_masters[0].shapes if s.name == "footer_ProjectInfo")
    assert box.text_frame.text.endswith("| RFQ Insight | 23 October 2026 |")

def test_title_clears_the_confidence_chip():
    """Ruling: a rated slide's title placeholder stops before the chip; its
    left and top stay the layout's."""
    plan = _plan(questions=[{
        "number": 1, "titleEn": "Opportunity Info", "titleDe": "x",
        "confidence": "medium",
        "slides": [{"layout": "bullets", "title": "Rated",
                    "bullets": [{"text": "x"}]}]}])
    prs = rdi.create_presentation(plan)
    toc, rated = list(prs.slides)[1:3]
    guard = rdi.PAGE_W - 2 * rdi.M - rdi.TITLE_RIGHT_GUARD
    assert abs(rated.shapes.title.width / 914400 - guard) < 0.01
    assert rated.shapes.title.left == toc.shapes.title.left
    assert rated.shapes.title.top == toc.shapes.title.top
    assert toc.shapes.title.width / 914400 > guard           # no chip, no cut

def test_comparison_deck_uses_the_avl_master():
    from rfq import comparison
    comp = {"a": {"label": "RFQ A", "column": "A"},
            "b": {"label": "RFQ B", "column": "B"}, "date": "2026-10-23",
            "sections": [{"title": "Timing", "confidence": None,
                          "counts": {"unchanged": 0, "changed": 1,
                                     "added": 0, "removed": 0},
                          "items": [{"item": "SOP", "a": "Q1 2028",
                                     "b": "Q2 2028", "change": "Changed"}]}]}
    slides = list(comparison.create_comparison(comp).slides)
    assert slides[0].slide_layout.name == branding.LAYOUT_COVER
    assert [s.slide_layout.name for s in slides[1:]] == [branding.LAYOUT_CONTENT] * 2


def test_prose_text_rewrites_missing_facts_inside_sentences():
    assert rdi.prose_text("The quotation due date is Info not available.") == "The quotation due date is not available."
    assert rdi.prose_text("Info not available") == "Info not available"
    assert rdi.prose_text("  info not available ") == "  info not available "


def _deck_text(plan):
    prs = rdi.create_presentation(plan)
    return " ".join(sh.text_frame.text for s in prs.slides for sh in s.shapes if sh.has_text_frame)


def test_prose_slide_and_callout_use_prose_wording():
    # ProseSlide carries no callout in the schema; callouts are drawn by the
    # diagram layouts (here: phases), which share rdi.callout.
    plan = _full_plan({2: [
        {"layout": "prose", "title": "Description", "caption": "Scope is Info not available.",
         "body": "Duration is Info not available."},
        {"layout": "phases", "title": "Phases", "phases": [{"name": "A"}],
         "callout": {"tag": "NOTE", "text": "Volume is Info not available."}}]})
    texts = _deck_text(plan)
    assert "Duration is not available." in texts and "Scope is not available." in texts
    assert "Volume is not available." in texts
    assert "is Info not available" not in texts


def test_bullets_and_panels_use_prose_wording_but_tables_keep_the_literal():
    plan = _full_plan({
        2: [{"layout": "bullets", "title": "B",
             "bullets": [{"text": "Start is Info not available.", "inferred": True}]}],
        3: [{"layout": "panel", "title": "P", "heading": "Project Risks",
             "items": ["Budget is Info not available."]}],
        4: [{"layout": "table", "title": "T", "columns": ["Item", "Value"],
             "rows": [["Due date", "Info not available"]]}]})
    texts = _deck_text(plan)
    assert "Start is not available." in texts and "Budget is not available." in texts
    assert "is Info not available" not in texts
    prs = rdi.create_presentation(plan)
    cells = [c.text for s in prs.slides for sh in s.shapes if sh.has_table
             for r in sh.table.rows for c in r.cells]
    assert "Info not available" in cells
