"""The C5 chronology check reads dates with the renderer's own parser.

`renderer.py` places a milestone on the Gantt calendar axis; the evaluation
gate in `rfq/validation.py` decides whether the slide plan lists them in
order. C5 is a CONSISTENCY check - "is the plan in the order the deck draws
it?" - so a disagreement between the two is a false warning on a correctly
drawn deck.

That happened on a real package: the renderer honoured the "early / mid / end
of" qualifiers, the checker did not, so "end of 2026" keyed to mid-year and
sorted BEFORE "December 2026". The fix was structural - one parser in
`rfq/dates.py`, imported by both - so these tests pin the property that
matters (the two agree on everything) rather than a table of expected months.

`rfq/dates.py` also carries the small date helpers the delivery layer needs
(exact calendar days for the chronology repair, the client's cover and file
name date formats); they are pinned at the end.
"""

import datetime
import os
import sys

import pytest

from rfq import validation as ev
from rfq.dates import (compact_date, display_date, exact_calendar_date,
                       numeric_exact_date, time_pos)

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


def test_the_renderer_draws_with_the_very_same_function():
    """Not a copy that happens to agree today: renderer._time_pos IS
    rfq.dates.time_pos."""
    from rfq import renderer
    assert renderer._time_pos is time_pos


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


def _timing_report(steps):
    """A report whose plan carries ONE Timing gantt. It is deliberately not a
    complete deck: C1/C1b/C9 trip by design, C5 is what is under test."""
    return {"slidePlan": {"projectName": "p", "questions": [{
        "number": 9, "titleEn": "Timing", "titleDe": "Terminplanung",
        "slides": [{"layout": "gantt", "title": "Timing", "bars": None,
                    "barLabel": "X", "callout": None, "steps": steps}]}]}}


def _c5(report):
    fails, warns, _oks = ev.evaluate(report, None)
    return [m for m in list(fails) + list(warns) if m.startswith("C5")]


def test_c5_accepts_the_ordering_that_tripped_the_false_warning():
    """End to end, on the real wording: December 2026 then end of 2026."""
    report = _timing_report([
        {"label": "Unit installed", "date": "December 2026",
         "desc": "reference unit"},
        {"label": "Validation done", "date": "end of 2026",
         "desc": "validation complete"},
    ])
    assert _c5(report) == []
    _fails, _warns, oks = ev.evaluate(report, None)
    assert "C5 timeline chronological" in oks


def test_c5_still_catches_a_genuinely_misordered_plan():
    """The check must not have been neutered by making it agree."""
    report = _timing_report([
        {"label": "SOP", "date": "Q3 2027", "desc": "last"},
        {"label": "Kickoff", "date": "January 2026", "desc": "first"},
    ])
    found = _c5(report)
    assert found and "Kickoff" in found[0]
    # chronology is a warning (the renderer sorts on the deck), not a fail
    fails, warns, _oks = ev.evaluate(report, None)
    assert found[0] in warns and found[0] not in fails


def test_c5_skips_undatable_steps_instead_of_flagging_them():
    """A relative timing between two dated ones is not a disorder."""
    report = _timing_report([
        {"label": "Kick-off", "date": "Jan 2026", "desc": ""},
        {"label": "Deliverables", "date": "+10 business days", "desc": ""},
        {"label": "SOP", "date": "Q3 2027", "desc": ""},
    ])
    assert _c5(report) == []


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
    assert imported <= set(sys.stdlib_module_names), imported
    assert not imported & {"pptx", "PIL", "pydantic", "rfq"}


# ------------------------------------------------------- the date helpers
@pytest.mark.parametrize("text, expected", [
    ("2026/7/15", datetime.date(2026, 7, 15)),
    ("2026-07-15", datetime.date(2026, 7, 15)),
    ("15.07.2026", datetime.date(2026, 7, 15)),     # European day-first
    ("07/15/2026", datetime.date(2026, 7, 15)),     # US, month 15 impossible
    ("03/04/2026", datetime.date(2026, 4, 3)),      # ambiguous -> day-first
    ("2026-02-30", None),                           # not a calendar day
    ("Jul 2026", None), ("Q3 2026", None), ("2026", None), ("", None),
])
def test_numeric_exact_date(text, expected):
    assert numeric_exact_date(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("15-Jul-2026", datetime.date(2026, 7, 15)),
    ("15. Okt 2026", datetime.date(2026, 10, 15)),
    ("Jul 15, 2026", datetime.date(2026, 7, 15)),
    ("September 11th, 2026", datetime.date(2026, 9, 11)),
    ("1 March 2027", datetime.date(2027, 3, 1)),
    ("2026/7/15", datetime.date(2026, 7, 15)),      # numeric forms too
    ("31 Feb 2026", None),                          # invalid day
    ("late September 2027", None),                  # qualified -> inexact
    ("Q1 2028", None), ("mid 2027", None), ("TBD", None),
])
def test_exact_calendar_date(text, expected):
    assert exact_calendar_date(text) == expected


def test_exact_calendar_dates_agree_with_the_axis_position():
    """An exact day keys to the same month the axis draws it in."""
    for text in ("15-Jul-2026", "2026-07-15", "Jul 15, 2026", "15.07.2026"):
        day = exact_calendar_date(text)
        assert day is not None, text
        assert int(time_pos(text)) == day.year * 12 + day.month - 1, text


def test_display_date_is_the_client_cover_format():
    assert display_date("2026-10-06") == "06.10.2026"
    assert display_date("2026-10-06T09:30:00") == "06.10.2026"   # ISO datetime
    assert display_date("06.10.2026") == "06.10.2026"            # left as is
    assert display_date("") == ""
    assert display_date(None) == ""


def test_compact_date_is_the_client_file_name_format():
    assert compact_date("2026-10-06") == "06102026"
    assert compact_date("2026-10-06T09:30:00") == "06102026"
    assert compact_date("06.10.2026") == "06102026"   # digits only, in order
    assert compact_date("") == ""
    assert compact_date(None) == ""
