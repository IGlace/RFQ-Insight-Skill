"""The C5 chronology check reads dates with the renderer's own parser.

`renderer.py` places a milestone on the Gantt calendar axis; `evaluate.py`
decides whether the slide plan lists them in order. C5 is a CONSISTENCY check -
"is the plan in the order the deck draws it?" - so a disagreement between the
two is a false warning on a correctly drawn deck.

That happened on a real package: the renderer honoured the "early / mid / end
of" qualifiers, the checker did not, so "end of 2026" keyed to mid-year and
sorted BEFORE "December 2026". The fix was structural - one parser in
`rfq/dates.py`, imported by both - so these tests pin the property that
matters (the two agree on everything) rather than a table of expected months.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "plugins", "rfq-insight", "skills", "rfq-insight", "scripts"))

import evaluate as ev                                   # noqa: E402
from rfq.dates import time_pos                          # noqa: E402

# Every shape the parser documents, plus the qualifier forms that broke C5.
DATE_STRINGS = [
    "2026/7/15", "2026-07-15", "15.07.2026", "07/15/2026", "15-Jul-2026",
    "Jul 15, 2026", "~Oct 2026", "Okt 2026", "Dez 2026", "März 2027",
    "Mai 2026", "July 2026", "December 2026", "late September 2027",
    "Q1 2028", "Q1/2028", "Q3 2026", "early Q3 2026", "mid Q3 2026",
    "end of Q3 2026", "KW 38/2026", "CW38 2026", "H1 2027", "late H1 2027",
    "2026", "early 2027", "mid 2027", "end of 2027", "Ende 2026",
    "Anfang 2027", "Mitte 2027", "end of 2026",
]


@pytest.mark.parametrize("text", DATE_STRINGS)
def test_checker_and_renderer_never_disagree(text):
    """The property the whole fix exists to guarantee: one parser, so the
    checker's ordering key IS the renderer's placement."""
    assert ev._parse_date_key(text) == time_pos(text), text


@pytest.mark.parametrize("text", DATE_STRINGS)
def test_every_documented_shape_still_parses(text):
    assert ev._parse_date_key(text) is not None, text


def test_unparseable_timings_have_no_key():
    """Relative timings belong on the timing table, not the calendar axis."""
    for text in ("T0+2 Weeks", "+10 business days", "within 1 week of LOI",
                 "Not stated", ""):
        assert ev._parse_date_key(text) is None, text


def test_end_of_a_year_no_longer_sorts_before_december():
    """The original defect, stated as the ordering it broke."""
    assert ev._parse_date_key("end of 2026") > ev._parse_date_key("December 2026")


@pytest.mark.parametrize("earlier, later", [
    ("early 2027", "mid 2027"),
    ("mid 2027", "end of 2027"),
    ("Anfang 2027", "Mitte 2027"),
    ("Mitte 2027", "Ende 2027"),
    ("early Q3 2026", "mid Q3 2026"),
    ("mid Q3 2026", "end of Q3 2026"),
    ("end of Q3 2026", "Q4 2026"),
    ("September 11, 2026", "end of September 2026"),
])
def test_qualifiers_order_within_their_span(earlier, later):
    assert ev._parse_date_key(earlier) < ev._parse_date_key(later)


@pytest.mark.parametrize("text, month", [
    ("2026", 1),          # a bare span opens at its start, as the renderer draws it
    ("Q3 2026", 7),
    ("end of 2026", 12),
    ("early 2026", 2),
])
def test_coarse_spans_resolve_where_the_renderer_puts_them(text, month):
    pos = ev._parse_date_key(text)
    assert (int(pos) // 12, int(pos) % 12 + 1) == (2026, month), text


def test_bar_ends_still_resolve_to_the_end_of_their_span():
    """`end=True` is the renderer's Gantt-bar behaviour and must survive the
    move: a bar labelled "2026" must not start and finish in January."""
    assert time_pos("2026", end=True) > time_pos("2026")
    assert time_pos("Q3 2026", end=True) > time_pos("Q3 2026")


def test_c5_accepts_the_ordering_that_tripped_the_false_warning():
    """End to end, on the real wording: December 2026 then end of 2026."""
    report = {"slidePlan": {"projectName": "p", "questions": [{
        "number": 9, "titleEn": "Timing", "titleDe": "Terminplanung",
        "slides": [{"layout": "gantt", "title": "Timing", "bars": None,
                    "barLabel": "X", "callout": None, "steps": [
                        {"label": "Unit installed", "date": "December 2026",
                         "desc": "reference unit"},
                        {"label": "Validation done", "date": "end of 2026",
                         "desc": "validation complete"},
                    ]}]}]}}
    fails, warns, _oks = ev.evaluate(report, None)
    # Only C5 is under test here; the one-question fixture trips C1 by design.
    assert not [m for m in list(fails) + list(warns) if "C5" in m]


def test_c5_still_catches_a_genuinely_misordered_plan():
    """The check must not have been neutered by making it agree."""
    report = {"slidePlan": {"projectName": "p", "questions": [{
        "number": 9, "titleEn": "Timing", "titleDe": "Terminplanung",
        "slides": [{"layout": "gantt", "title": "Timing", "bars": None,
                    "barLabel": "X", "callout": None, "steps": [
                        {"label": "SOP", "date": "Q3 2027", "desc": "last"},
                        {"label": "Kickoff", "date": "January 2026",
                         "desc": "first"},
                    ]}]}]}}
    fails, warns, _oks = ev.evaluate(report, None)
    assert [m for m in list(fails) + list(warns) if "C5" in m]


def test_the_shared_parser_imports_without_pptx():
    """`rfq.dates` must stay stdlib-only - the checker has to run against a
    report JSON with nothing installed, which is why the logic was moved out
    of `renderer.py` in the first place."""
    import ast
    path = os.path.join(os.path.dirname(os.path.abspath(time_pos.__code__.co_filename)),
                        "dates.py")
    tree = ast.parse(open(path, encoding="utf-8").read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"re"}, imported
