"""rfq.sources: locator grammar, corpus checks, reference ids and the
printed source lines."""

import re

import pytest

from helpers import SOURCE_FILE, sample_analysis, sample_plan
from rfq import sources as s
from rfq.schema import TITLES

PDF_TEXT = (
    "--- Page 1 ---\n"
    "--- Section: 1 Introduction ---\n"
    "Northwind asks for a quote.\n"
    "--- Page 2 ---\n"
    "--- Section: 3.1 Timing ---\n"
    "--- Section Path: 3 Project > 3.1 Timing ---\n"
    "SOP in 2028.\n"
    "--- Page 3 ---\n"
    "--- Section: 3.2 Scope ---\n"
    "Calibration only.\n"
    "--- Page 4 ---\n"
    "Appendix.\n")
PPTX_TEXT = "--- Slide 1 ---\nTitle\n--- Slide 2 ---\nTargets\n--- Slide 3 ---\nEnd\n"
XLSX_TEXT = "--- Sheet: Plan ---\nA1\n--- Sheet: Budget ---\nB1\n"
DOCX_TEXT = "--- Section: 2 Scope ---\nScope text.\n--- Section: 4 Timing ---\nDates.\n"
PLAIN_TEXT = "No markers at all."


def _files():
    return [{"filename": "rfq.pdf", "path": "in/rfq.pdf", "sha256": "a" * 64,
             "extracted_text": PDF_TEXT},
            {"filename": "deck.pptx", "extracted_text": PPTX_TEXT},
            {"filename": "plan.xlsx", "extracted_text": XLSX_TEXT},
            {"filename": "sow.docx", "extracted_text": DOCX_TEXT},
            {"filename": "notes.txt", "extracted_text": PLAIN_TEXT}]


def _corpus():
    return {"filesContents": _files()}


# ---------------------------------------------------------- parse_locator
@pytest.mark.parametrize("locator,parsed", [
    ("p. 12", ("page", 12, 12)),
    ("P. 12", ("page", 12, 12)),
    ("page 12", ("page", 12, 12)),
    ("pp. 12-13", ("page", 12, 13)),
    ("p. 3-6", ("page", 3, 6)),
    ("p. 3 – 6", ("page", 3, 6)),
    ("p. 12 f.", ("page", 12, 13)),
    ("pp. 12, 14", ("page", 12, 12, 14, 14)),
    ("slide 3", ("slide", 3, 3)),
    ("slides 3-4", ("slide", 3, 4)),
    ("sheet 'Plan'", ("sheet", "Plan")),
    ('sheet "Plan"', ("sheet", "Plan")),
    ("sheet: Plan", ("sheet", "Plan")),
    ("Sheet1", ("sheet", "Sheet1")),
    ("section 3.1 Timing", ("section", "3.1 Timing")),
    ("chapter 3.1 Timing", ("section", "3.1 Timing")),
    ("section: Scope", ("section", "Scope")),
    ("", ("none",)),
    (None, ("none",)),
    ("   ", ("none",)),
    ("whole file (location unavailable)", ("whole",)),
    ("Whole File (Location Unavailable)", ("whole",)),
    ("p. 12; section 3.1", ("composite", ("page", 12, 12), ("section", "3.1"))),
    ("p. 2-3; section 3.1 Timing",
     ("composite", ("page", 2, 3), ("section", "3.1 Timing"))),
    ("section 3.1; p. 12", ("composite", ("page", 12, 12), ("section", "3.1"))),
])
def test_locator_grammar(locator, parsed):
    assert s.parse_locator(locator) == parsed


@pytest.mark.parametrize("locator", [
    "page twelve", "p. 0", "p. 6-3", "p. 12-", "12", "slide", "sheet ''",
    "section", "p. 12; slide 3", "p. 12; p. 13", "p. 12 section 3",
    "whole file", "see attachment",
])
def test_invalid_locators_are_none(locator):
    assert s.parse_locator(locator) is None


@pytest.mark.parametrize("locator,canonical", [
    ("P. 12", "p. 12"), ("pages 3 – 6", "p. 3-6"), ("p. 12 f.", "p. 12-13"),
    ("pp. 12, 14", "p. 12, 14"), ("Slides 3-4", "slide 3-4"),
    ('sheet "Plan"', "sheet 'Plan'"), ("chapter: 3.1 Timing", "section 3.1 Timing"),
    ("section 3.1; p. 12", "p. 12; section 3.1"),
    ("whole file (location unavailable)", "whole file (location unavailable)"),
    ("", ""),
])
def test_canonical_locator(locator, canonical):
    assert s.canonical_locator(s.parse_locator(locator)) == canonical


# --------------------------------------------------------- locator_exists
@pytest.mark.parametrize("text,locator,found", [
    (PDF_TEXT, "p. 2", True),
    (PDF_TEXT, "p. 1-4", True),
    (PDF_TEXT, "pp. 1, 4", True),
    (PDF_TEXT, "p. 5", False),
    (PDF_TEXT, "p. 3-5", False),
    (PDF_TEXT, "section 3.1 Timing", True),
    (PDF_TEXT, "section 3.1 timing", True),           # case-insensitive
    (PDF_TEXT, "section 3.1", True),                  # unique partial heading
    (PDF_TEXT, "section 3", False),                   # ambiguous partial heading
    (PDF_TEXT, "section 3 Project > 3.1 Timing", True),
    (PDF_TEXT, "section 9 Nothing", False),
    (PDF_TEXT, "p. 2; section 3.1 Timing", True),
    (PDF_TEXT, "p. 3; section 3.1 Timing", False),    # right page, wrong section
    (PDF_TEXT, "p. 9; section 3.1 Timing", False),
    (PDF_TEXT, "slide 1", False),
    (PDF_TEXT, "", True),
    (PDF_TEXT, "whole file (location unavailable)", True),
    (PPTX_TEXT, "slide 3", True),
    (PPTX_TEXT, "slides 2-3", True),
    (PPTX_TEXT, "slide 4", False),
    (PPTX_TEXT, "p. 1", False),
    (XLSX_TEXT, "sheet 'Plan'", True),
    (XLSX_TEXT, "sheet 'plan'", True),
    (XLSX_TEXT, "sheet 'Pla'", False),                # sheets match whole
    (XLSX_TEXT, "sheet 'Costs'", False),
    (DOCX_TEXT, "section 4 Timing", True),
    (DOCX_TEXT, "section Timing", True),
    (DOCX_TEXT, "section 4 – Timing", False),
    (PLAIN_TEXT, "p. 1", False),
    (PLAIN_TEXT, "", True),
    ("", "", True),
])
def test_locator_exists(text, locator, found):
    assert s.locator_exists(text, s.parse_locator(locator)) is found


def test_rendered_spans_count_as_pages():
    text = "--- Page 1 ---\n[[Table spans rendered pages 1-3]]\nA | B\n"
    assert s.locator_exists(text, s.parse_locator("p. 2")) is True
    assert s.locator_exists(text, s.parse_locator("p. 4")) is False


# ---------------------------------------------------- reference catalogue
def test_reference_catalogue_lists_every_verified_region():
    catalogue = s.reference_catalogue(_corpus())
    assert catalogue["version"] == 1
    rows = catalogue["references"]
    assert all(re.fullmatch(r"src-[0-9a-f]{24}", r["id"]) for r in rows)
    assert len({r["id"] for r in rows}) == len(rows)
    by_file = {}
    for row in rows:
        by_file.setdefault(row["filename"], []).append(row["locator"])
    assert by_file["rfq.pdf"][:3] == ["p. 1", "section 1 Introduction",
                                      "p. 1; section 1 Introduction"]
    assert "p. 2; section 3 Project > 3.1 Timing" in by_file["rfq.pdf"]
    assert by_file["deck.pptx"] == ["slide 1", "slide 2", "slide 3"]
    assert by_file["plan.xlsx"] == ["sheet 'Plan'", "sheet 'Budget'"]
    assert by_file["notes.txt"] == [""]
    assert all(s.locator_exists(next(f["extracted_text"] for f in _files()
                                     if f["filename"] == r["filename"]),
                                s.parse_locator(r["locator"])) for r in rows)
    pdf = next(r for r in rows if r["filename"] == "rfq.pdf")
    assert pdf["path"] == "in/rfq.pdf"


def test_reference_ids_change_with_the_evidence():
    before = {r["locator"]: r["id"] for r in s.reference_catalogue(_corpus())["references"]
              if r["filename"] == "rfq.pdf"}
    corpus = _corpus()
    corpus["filesContents"][0]["extracted_text"] += "More.\n"
    after = {r["locator"]: r["id"] for r in s.reference_catalogue(corpus)["references"]
             if r["filename"] == "rfq.pdf"}
    assert set(before) == set(after)
    assert all(before[k] != after[k] for k in before)


def test_duplicate_basenames_get_no_reference_ids():
    corpus = _corpus()
    corpus["filesContents"].append({"filename": "rfq.pdf", "extracted_text": "--- Page 1 ---\nx"})
    rows = s.reference_catalogue(corpus)["references"]
    assert not any(r["filename"] == "rfq.pdf" for r in rows)
    assert any(r["filename"] == "deck.pptx" for r in rows)


def test_expand_reference_ids_resolves_current_ids():
    corpus = _corpus()
    rows = s.reference_catalogue(corpus)["references"]
    row = next(r for r in rows if r["locator"] == "slide 2")
    refs = [{"ref_id": row["id"]}, {"filename": "notes.txt", "locator": ""}]
    assert s.expand_reference_ids(refs, corpus) == [
        {"filename": "deck.pptx", "locator": "slide 2"},
        {"filename": "notes.txt", "locator": ""}]
    legacy = [{"filename": "notes.txt", "locator": ""}]
    assert s.expand_reference_ids(legacy, corpus) is legacy
    assert s.expand_reference_ids("nope", corpus) == "nope"


def test_expand_reference_ids_raises_on_unknown_or_stale_ids():
    corpus = _corpus()
    with pytest.raises(ValueError, match="Unknown or stale"):
        s.expand_reference_ids([{"ref_id": "src-" + "0" * 24}], corpus)
    with pytest.raises(ValueError, match="Unknown or stale"):
        s.expand_reference_ids([{"ref_id": 7}], corpus)
    row = s.reference_catalogue(corpus)["references"][0]
    with pytest.raises(ValueError, match="only ref_id"):
        s.expand_reference_ids([{"ref_id": row["id"], "locator": "p. 1"}], corpus)
    changed = _corpus()
    changed["filesContents"][0]["extracted_text"] += "changed"
    with pytest.raises(ValueError, match="Unknown or stale"):
        s.expand_reference_ids([{"ref_id": row["id"]}], changed)


# ---------------------------------------------------------- check_sources
def test_valid_sources_pass():
    cited = [{"filename": "rfq.pdf", "locator": "p. 2; section 3.1 Timing"},
             {"filename": "deck.pptx", "locator": "slide 2"},
             {"filename": "plan.xlsx", "locator": "sheet 'Plan'"},
             {"filename": "sow.docx", "locator": "section 2 Scope"},
             {"filename": "notes.txt", "locator": ""},
             {"filename": "rfq.pdf", "locator": "whole file (location unavailable)"}]
    assert s.check_sources(cited, _files(), "Section 2", require=True) == []


def test_unknown_file_is_rejected():
    problems = s.check_sources([{"filename": "missing.pdf", "locator": "p. 1"}],
                               _files(), "Section 2")
    assert problems == ["Section 2 source #1: 'missing.pdf' is not a corpus file; copy "
                        "the name exactly from a === FILE: === header."]


def test_unparseable_locator_is_rejected():
    [problem] = s.check_sources([{"filename": "rfq.pdf", "locator": "page twelve"}],
                                _files(), "Section 2")
    assert problem.startswith("Section 2 source #1: locator 'page twelve' is not one of:")
    assert "'p. 12'" in problem


def test_locator_the_file_lacks_is_rejected_with_the_known_names():
    [problem] = s.check_sources([{"filename": "plan.xlsx", "locator": "sheet 'Costs'"}],
                                _files(), "Section 2")
    assert "plan.xlsx has no sheet 'Costs'" in problem
    assert "Its sheets: sheet 'Plan'; sheet 'Budget'." in problem
    [problem] = s.check_sources([{"filename": "rfq.pdf", "locator": "p. 9"}],
                                _files(), "Section 2")
    assert "rfq.pdf has no page 9" in problem
    [problem] = s.check_sources([{"filename": "sow.docx", "locator": "section 9 Costs"}],
                                _files(), "Section 2")
    assert "section heading matching '9 Costs'" in problem
    assert "Its sections: section 2 Scope; section 4 Timing." in problem


def test_an_empty_locator_needs_markers_except_for_source_material():
    cited = [{"filename": "rfq.pdf", "locator": ""}]
    [problem] = s.check_sources(cited, _files(), "Section 2")
    assert "rfq.pdf requires a specific location" in problem
    assert s.WHOLE_FILE_LIMITATION in problem
    assert s.check_sources(cited, _files(), "Section 12") == []
    assert s.check_sources([{"filename": "notes.txt", "locator": ""}],
                           _files(), "Section 2") == []


def test_required_sources_may_not_be_empty():
    assert s.check_sources([], _files(), "Section 2") == []
    [problem] = s.check_sources([], _files(), "Section 2", require=True)
    assert "Section 2 has no sources" in problem
    assert s.check_sources("nope", _files(), "Section 2") == ["Section 2: 'sources' must be a list."]
    assert s.check_sources(["nope"], _files(), "Section 2") == ["Section 2 source #1 is not an object."]


def test_a_duplicate_basename_is_valid_when_any_copy_has_the_marker():
    files = _files() + [{"filename": "rfq.pdf", "extracted_text": "--- Page 9 ---\nLate."}]
    assert s.check_sources([{"filename": "rfq.pdf", "locator": "p. 9"}], files, "Section 2") == []


# ----------------------------------------------------- downgrade_locators
def test_downgrade_locators_marks_unverifiable_citations():
    cited = [{"filename": "rfq.pdf", "locator": "p. 9"},
             {"filename": "rfq.pdf", "locator": ""},
             {"filename": "rfq.pdf", "locator": "p. 2"},
             {"filename": "notes.txt", "locator": ""},
             {"filename": "missing.pdf", "locator": "p. 1"},
             "oops"]
    changed = s.downgrade_locators(cited, _files(), "Section 4")
    assert changed == ["Section 4: rfq.pdf p. 9", "Section 4: rfq.pdf (no specific location)"]
    assert [c["locator"] for c in cited if isinstance(c, dict)] == [
        s.WHOLE_FILE_LIMITATION, s.WHOLE_FILE_LIMITATION, "p. 2", "", "p. 1"]
    problems = s.check_sources(cited[:5], _files(), "Section 4")
    assert len(problems) == 1 and "missing.pdf" in problems[0]
    assert s.downgrade_locators("nope", _files(), "Section 4") == []


# ------------------------------------------------------ printed source line
def test_source_line_merges_locations_per_file():
    cited = [{"filename": "rfq.pdf", "locator": "p. 2"},
             {"filename": "deck.pptx", "locator": "slide 3"},
             {"filename": "rfq.pdf", "locator": "p. 3-4; section 3.2 Scope"},
             {"filename": "rfq.pdf", "locator": "p. 1"},
             {"filename": "plan.xlsx", "locator": "sheet 'Plan'"},
             {"filename": "notes.txt", "locator": ""}]
    assert s.format_source_line(cited, False) == (
        "Source: rfq.pdf p. 1-4, section 3.2 Scope; deck.pptx slide 3; "
        "plan.xlsx sheet 'Plan'; notes.txt")


def test_source_line_for_nothing_found():
    assert s.format_source_line([], False) == s.NOT_FOUND_LINE
    assert s.format_source_line([{"filename": "rfq.pdf", "locator": "p. 1"}], True) == s.NOT_FOUND_LINE
    assert s.format_source_line([{"filename": "", "locator": "p. 1"}], False) == s.NOT_FOUND_LINE


def test_source_line_is_cut_to_one_line():
    cited = [{"filename": f"annex_{n:02d}_specification.pdf", "locator": "p. 1"}
             for n in range(12)]
    line = s.format_source_line(cited, False)
    assert len(line) <= s.LINE_CHARS
    assert re.search(r"; \+\d+ more$", line)
    assert line.startswith("Source: annex_00_specification.pdf p. 1")


def test_source_details_group_locations_per_file():
    cited = [{"filename": "rfq.pdf", "locator": "p. 2; section 3.1 Timing"},
             {"filename": "rfq.pdf", "locator": "p. 3-4"},
             {"filename": "rfq.pdf", "locator": "p. 2; section 3.1 Timing"},
             {"filename": "deck.pptx", "locator": "slides 2-3"},
             {"filename": "plan.xlsx", "locator": "sheet 'Plan'"}]
    details = s.format_source_details(cited, files=_files())
    assert details == (
        "Sources:\n\n"
        "File: rfq.pdf\n"
        "  Section: 3.1 Timing\n"
        "  Page: 2\n"
        "  Chapter hierarchy: 3 Project > 3.1 Timing\n\n"
        "  Pages: 3-4\n\n"
        "File: deck.pptx\n"
        "  Slides: 2-3\n\n"
        "File: plan.xlsx\n"
        "  Sheet: Plan")


def test_source_details_disclose_unverifiable_and_whole_file_locations():
    cited = [{"filename": "rfq.pdf", "locator": "p. 9"},
             {"filename": "rfq.pdf", "locator": s.WHOLE_FILE_LIMITATION},
             {"filename": "rfq.pdf", "locator": ""},
             {"filename": "notes.txt", "locator": ""}]
    details = s.format_source_details(cited, files=_files())
    assert details == (
        "Sources:\n\n"
        "File: rfq.pdf\n"
        "  Location: unavailable; check the whole file.\n\n"
        "  Location: whole file (specific location not supplied)\n\n"
        "File: notes.txt\n"
        "  Location: whole file (no stable page or section available)")
    assert s.format_source_details(cited, not_found=True, files=_files()) == s.NOT_FOUND_LINE
    assert s.format_source_details([], files=_files()) == s.NOT_FOUND_LINE


def test_source_details_without_corpus_trust_the_citation():
    details = s.format_source_details([{"filename": "x.pdf", "locator": "p. 7"}])
    assert details == "Sources:\n\nFile: x.pdf\n  Page: 7"


def test_source_details_say_when_a_word_file_has_no_page():
    details = s.format_source_details([{"filename": "sow.docx", "locator": "section 4 Timing"}],
                                      files=_files())
    assert details == ("Sources:\n\nFile: sow.docx\n  Section: 4 Timing\n"
                       "  Page: unavailable; find the section named above.")
    paged = [{"filename": "paged.docx",
              "extracted_text": "--- Page 1 ---\n--- Section: 4 Timing ---\nx"}]
    details = s.format_source_details([{"filename": "paged.docx", "locator": "section 4 Timing"}],
                                      files=paged)
    assert "Page: unavailable" not in details


def test_source_details_print_the_corpus_spelling():
    files = [{"filename": "sow.docx",
              "extracted_text": "--- Section: 3.2 – Timing ---\nx"}]
    cited = [{"filename": "sow.docx", "locator": "section 3.2 - timing"}]
    assert "Section: 3.2 – Timing" in s.format_source_details(cited, files=files)
    assert s.corpus_spelling(cited, files) == [
        {"filename": "sow.docx", "locator": "section 3.2 – Timing"}]


def test_source_details_note_a_table_spanning_pages():
    files = [{"filename": "t.pdf", "extracted_text":
              "--- Page 1 ---\n[[Table spans rendered pages 1-3]]\nA | B\n"}]
    details = s.format_source_details([{"filename": "t.pdf", "locator": "p. 2"}], files=files)
    assert "Note: the table spans these pages" in details


# --------------------------------------------------------- attach_sources
def test_attach_sources_sets_both_lines_on_every_question():
    plan, analysis = sample_plan(), sample_analysis()
    analysis["answers"][3]["not_found"] = True
    s.attach_sources(plan, analysis)
    for question in plan["questions"]:
        if question["number"] == 4:
            assert question["sourceLine"] == s.NOT_FOUND_LINE
            assert question["sourceDetails"] == s.NOT_FOUND_LINE
        else:
            assert question["sourceLine"] == f"Source: {SOURCE_FILE}"
            assert question["sourceDetails"] == (
                f"Sources:\n\nFile: {SOURCE_FILE}\n  Page: unavailable" if False else
                f"Sources:\n\nFile: {SOURCE_FILE}\n  Location: whole file (no stable page or section available)")


def test_attach_sources_names_the_account_list_once_an_account_is_applied():
    plan, analysis = sample_plan(), sample_analysis()
    analysis["opportunity"]["account_name"] = "Northwind Motors (Hamburg)"
    s.attach_sources(plan, analysis)
    first = plan["questions"][0]
    assert first["sourceLine"] == f"Source: {SOURCE_FILE}; {s.ACCOUNT_LIST_SOURCE}"
    assert first["sourceDetails"].endswith("\n\nReference: " + s.ACCOUNT_LIST_SOURCE)
    assert plan["questions"][1]["sourceLine"] == f"Source: {SOURCE_FILE}"
    analysis["answers"][0]["not_found"] = True
    s.attach_sources(plan, analysis)
    assert first["sourceLine"] == "Source: " + s.ACCOUNT_LIST_SOURCE
    assert first["sourceDetails"] == "Sources:\n\nReference: " + s.ACCOUNT_LIST_SOURCE


def test_attach_sources_cites_the_follow_ups_in_the_deck():
    plan = sample_plan()
    plan["questions"].insert(11, {"number": 13, "titleEn": "Additional Information",
                                  "titleDe": "Zusätzliche Informationen", "slides": []})
    followups = {"followups": [
        {"in_deck": True, "sources": [{"filename": "rfq.pdf", "locator": "p. 2"}]},
        {"in_deck": False, "sources": [{"filename": "deck.pptx", "locator": "slide 1"}]}]}
    s.attach_sources(plan, sample_analysis(), followups, files=_files())
    extra = next(q for q in plan["questions"] if q["number"] == 13)
    assert extra["sourceLine"] == "Source: rfq.pdf p. 2"
    assert extra["sourceDetails"] == "Sources:\n\nFile: rfq.pdf\n  Page: 2"
    s.attach_sources(plan, sample_analysis(), {"followups": []}, files=_files())
    assert extra["sourceLine"] == s.NOT_FOUND_LINE


def test_attach_sources_uses_the_corpus_spelling():
    plan, analysis = sample_plan(), sample_analysis()
    files = [{"filename": SOURCE_FILE,
              "extracted_text": "--- Sheet: Project Plan ---\nx"}]
    analysis["answers"][1]["sources"] = [{"filename": SOURCE_FILE, "locator": "sheet 'project plan'"}]
    s.attach_sources(plan, analysis, files=files)
    assert plan["questions"][1]["sourceLine"] == f"Source: {SOURCE_FILE} sheet 'Project Plan'"
    assert TITLES[2][0] == plan["questions"][1]["titleEn"]
