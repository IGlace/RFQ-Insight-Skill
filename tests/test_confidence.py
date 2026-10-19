"""The per-section deduction catalogue and the 1-10 confidence score.

The model only names rule codes, counts and the items they rest on; the
points, the cap per code, the score, the band and the notes text are all
computed here (rfq/schema.py holds the catalogue, rfq/confidence.py the
arithmetic and wording)."""

import pytest

from rfq import confidence as cf
from rfq.schema import (ADDITIONAL_INFO_ID, EXTRACTED_SECTIONS, RULES,
                        SECTION_IDS, SECTION_MODES, SOURCES as SOURCE_MATERIAL,
                        AnswerItem, Question, rule_points, rule_sections,
                        rules_for)

SOURCES = "Sources:\nFile: 01_statement_of_work.txt"
CHECK = ("Check: 6 statements reviewed by a separate reviewer: 6 confirmed. "
         "3 values matched in the corpus.")


def _entry(rule, count=1, items="", basis=""):
    return {"rule": rule, "count": count, "items": items, "basis": basis}


# ------------------------------------------------------------- the catalogue
# code -> (points, cap, source); None cap = once-rule. Only content not
# taken from the RFQ costs points (client decision): no rule prices a
# contradiction, an evidence limit, an unnamed contractor (section 5's
# inferred AVL row is an ordinary G3 item) or the section 1 splits, and
# Source Material has no rules at all.
CATALOGUE = {
    "G3": (1, 4, "model"),
    "V1": (4, 8, "python"), "V3": (3, 6, "python"),
    "S2.1": (2, 6, "model"),
    "S3.1": (2, 6, "model"),
    "S5.2": (1, 3, "model"),
    "S6.1": (3, None, "model"), "S6.2": (1, None, "model"),
    "S6.3": (2, None, "model"),
    "S7.1": (None, 4, "model"), "S7.2": (1, 3, "model"),
    "S7.3": (2, None, "model"),
    "S8.1": (1, 3, "model"), "S8.2": (1, None, "model"),
    "S9.1": (2, 4, "model"), "S9.2": (1, None, "model"),
    "S10.1": (2, 4, "model"), "S10.2": (1, 2, "model"),
    "S11.1": (2, 6, "model"), "S11.2": (3, None, "model"),
    # Section 1's percentage split, rated on its own slide.
    "P1": (4, None, "model"), "P2": (2, None, "model"),
}
REMOVED = ("G1", "G2", "G4", "G5", "V2", "P12.1", "P12.2", "S1.1", "S1.2",
           "S1.3", "S1.4", "S2.2", "S2.3", "S3.3", "S5.1", "S11.3", "S11.4")


def test_catalogue_has_exactly_the_contract_codes():
    assert set(RULES) == set(CATALOGUE)
    for code, (points, cap, source) in CATALOGUE.items():
        rule = RULES[code]
        assert rule.code == code
        assert rule.cap == cap and rule.source == source
        assert rule.once is (cap is None)
        if points is not None:
            assert rule.points == points and rule.tiers is None
    assert RULES["S7.1"].tiers
    assert not set(REMOVED) & set(RULES)


def test_rule_sections():
    assert rule_sections(RULES["G3"]) == (1, 3, 4, 5, 6, 7, 8, 9, 10, 13)
    assert rule_sections(RULES["V3"]) == (1, 3, 4, 5, 6, 7, 8, 9, 10, 13)
    assert rule_sections(RULES["V1"]) == (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11,
                                          13)


def test_section_modes():
    assert SECTION_MODES == {1: "mixed", 2: "analysed", 3: "extracted",
                             4: "extracted", 5: "extracted", 6: "extracted",
                             7: "extracted", 8: "extracted", 9: "extracted",
                             10: "extracted", 11: "analysed", 12: "python"}
    assert EXTRACTED_SECTIONS == (3, 4, 5, 6, 7, 8, 9, 10)


def test_every_section_but_source_material_has_a_model_rule():
    for section in SECTION_IDS:
        assert bool(rules_for(section)) is (section != SOURCE_MATERIAL)
    assert not any(SOURCE_MATERIAL in rule_sections(rule)
                   for rule in RULES.values())
    for mode in ("extracted", "analysed"):
        assert rules_for(ADDITIONAL_INFO_ID, mode)


def test_rules_for_offers_only_model_rules_of_that_section():
    codes = {rule.code for rule in rules_for(7)}
    assert codes == {"G3", "S7.1", "S7.2", "S7.3"}
    assert {rule.code for rule in rules_for(1)} == {"G3", "P1", "P2"}
    assert {rule.code for rule in rules_for(2)} == {"S2.1"}
    assert {rule.code for rule in rules_for(5)} == {"G3", "S5.2"}
    assert {rule.code for rule in rules_for(11)} == {"S11.1", "S11.2"}


def test_rules_for_additional_information_follows_the_answer_mode():
    extracted = {rule.code for rule in rules_for(ADDITIONAL_INFO_ID, "extracted")}
    analysed = {rule.code for rule in rules_for(ADDITIONAL_INFO_ID, "analysed")}
    assert extracted == {"G3"}
    assert analysed == {"S2.1"}


# ------------------------------------------------------------------- points
@pytest.mark.parametrize("count, points", [(1, 1), (3, 1), (4, 2), (8, 2),
                                           (9, 4), (30, 4)])
def test_tiered_points(count, points):
    assert rule_points(RULES["S7.1"], count) == points


def test_points_per_count_up_to_the_cap():
    assert rule_points(RULES["G3"], 1) == 1
    assert rule_points(RULES["G3"], 6) == 4
    assert rule_points(RULES["S3.1"], 2) == 4


def test_once_rules_ignore_the_count():
    assert rule_points(RULES["S6.1"], 1) == 3
    assert rule_points(RULES["S6.1"], 5) == 3


def test_cap_applies_across_entries_of_one_code():
    resolved = cf.resolve([_entry("S3.1", 2, "power"), _entry("S3.1", 1, "torque"),
                           _entry("S3.1", 1, "mass")], 3)
    assert [entry["points"] for entry in resolved] == [4, 2, 0]
    tiers = cf.resolve([_entry("S7.1", 9, "a"), _entry("S7.1", 2, "b")], 7)
    assert [entry["points"] for entry in tiers] == [4, 0]


def test_once_rule_counts_once_per_section():
    resolved = cf.resolve([_entry("S6.1"), _entry("S6.1")], 6)
    assert [entry["points"] for entry in resolved] == [3, 0]


def test_resolve_keeps_the_entry_and_adds_points_and_line():
    entry = _entry("S3.1", 2, "power, torque", "SOR 4.1")
    resolved = cf.resolve([entry], 3)
    assert resolved == [{**entry, "points": 4, "line":
                         "S3.1  2 values estimated or converted: "
                         "power, torque (SOR 4.1)"}]
    assert "points" not in entry


# -------------------------------------------------------------- score, band
def test_score_is_ten_minus_the_deductions_with_a_floor_of_one():
    assert cf.score([], 7) == 10
    # 10 - 2 = 8, held at 6 (the top of Medium): the cells were inferred.
    assert cf.score(cf.resolve([_entry("S7.1", 4)], 7), 7) == 6
    assert cf.score(cf.resolve([_entry("V3", 1)], 7, allow_python=True),
                    7) == 7
    heavy = cf.resolve([_entry("S3.1", 3), _entry("G3", 4), _entry("V1", 2)],
                       3, allow_python=True)
    assert sum(entry["points"] for entry in heavy) == 18
    assert cf.score(heavy, 3) == 1


@pytest.mark.parametrize("value, word", [(10, "high"), (7, "high"),
                                         (6, "medium"), (4, "medium"),
                                         (3, "low"), (1, "low")])
def test_band_thresholds(value, word):
    assert cf.band(value) == word


def test_band_words():
    assert cf.BAND_WORD == {"high": "High", "medium": "Medium", "low": "Low"}


# -------------------------------------------------------------------- notes
def test_notes_reproduce_the_contract_example():
    resolved = cf.resolve([
        _entry("S7.1", 4, "PM, design review, cooling jacket, failure handling",
               "Technical Agreement 3.3.2 gives no phase for them"),
        _entry("S7.2", 1, "test bench setup",
               "Table 2 lists Aurobay and Party B as R"),
    ], 7)
    value = cf.score(resolved, 7)
    shown = cf.shown_line(10, {"found": 16, "shown": 13})
    text = cf.notes(value, cf.band(value), [e["line"] for e in resolved],
                    CHECK, shown, SOURCES, deductions=resolved)
    # The points add up to 7 (High); the inferred cells hold it at Medium,
    # and the notes say so - without printing a score or the points.
    assert text == (
        "Confidence: Medium\n"
        "Basis: partly inferred - some content is not stated in the RFQ.\n"
        "S7.1  4 cells placed by inference: PM, design review, cooling "
        "jacket, failure handling (Technical Agreement 3.3.2 gives no phase "
        "for them)\n"
        "S7.2  1 RASIC conflict resolved to one executing party: test "
        "bench setup (Table 2 lists Aurobay and Party B as R)\n"
        "Not rated High: some of this is not stated in the RFQ.\n"
        "Contradictions: the documents were unclear or disagreed; the "
        "deductions above say how it was settled.\n"
        f"{CHECK}\n"
        "Shown: 13 of 16 standards.\n"
        "\n"
        f"{SOURCES}")
    assert "/10" not in text


def test_notes_without_deductions():
    assert cf.notes(10, "high", [], CHECK, "", SOURCES) == (
        "Confidence: High\n"
        "Basis: extracted from the RFQ documents, no interpretation.\n"
        "No deductions: every item is stated in the documents.\n"
        "Contradictions: none detected.\n"
        f"{CHECK}\n\n{SOURCES}")


def test_notes_for_a_section_not_found():
    assert cf.notes(10, "high", [], CHECK, "", SOURCES, not_found=True) == (
        "Confidence: High\n"
        "Basis: extracted from the RFQ documents, no interpretation.\n"
        "No deductions: confirmed absent after a full sweep.\n"
        "Contradictions: none detected.\n"
        f"{CHECK}\n\n{SOURCES}")


def test_no_cap_line_when_the_reasons_alone_set_the_band():
    resolved = cf.resolve([_entry("S3.1", 3, "power, torque, mass")], 3)
    value = cf.score(resolved, 3)
    assert value == 4
    assert cf.cap_line(value, resolved) == ""


@pytest.mark.parametrize("rule, line", [
    ("S3.1", "Not rated High: the documents were unclear here and the "
             "analysis settled it."),
    ("S8.1", "Not rated High: some of this is not stated in the RFQ."),
    ("S6.1", "Not rated above Low: this is an AI estimate."),
])
def test_cap_line_explains_a_band_held_down_without_a_number(rule, line):
    section = int(rule[1:].split(".")[0])
    resolved = cf.resolve([_entry(rule)], section)
    assert cf.cap_line(cf.score(resolved, section), resolved) == line


def test_unscored_removes_numbers_from_saved_notes():
    saved = ("Confidence 6/10 (Medium)\n"
             "-2  S7.1  4 cells placed by inference: PM (SOR 3)\n"
             "Capped at 6/10: some of this is not stated in the RFQ, so it "
             "cannot be rated High.\n"
             'Follow-up 1 "Who ships?": 3/10\n\n'
             "Sources:\nFile: a.pdf, p. 10")
    assert cf.unscored(saved) == (
        "Confidence: Medium\n"
        "S7.1  4 cells placed by inference: PM (SOR 3)\n"
        "Not rated higher: some of this is not stated in the RFQ, so it "
        "cannot be rated High.\n"
        'Follow-up 1 "Who ships?": Low\n\n'
        "Sources:\nFile: a.pdf, p. 10")
    assert cf.unscored(cf.notes(10, "high", [], CHECK, "", SOURCES)) == \
        cf.notes(10, "high", [], CHECK, "", SOURCES)


def test_shown_line_only_when_trimmed():
    assert cf.SHOWN_NOUNS == {2: "paragraphs", 3: "targets", 7: "rows",
                              10: "standards", 11: "risks"}
    assert cf.shown_line(7, None) == ""
    assert cf.shown_line(7, {"found": 5, "shown": 5}) == ""
    assert cf.shown_line(7, {"found": 9, "shown": 6}) == "Shown: 6 of 9 rows."
    model = AnswerItem(id=11, answer="x", shown={"found": 4, "shown": 3}).shown
    assert cf.shown_line(11, model) == "Shown: 3 of 4 risks."


def test_line_without_items_or_basis():
    assert cf.deduction_line(3, "S6.1") == (
        "S6.1  phase names assigned by the analysis (RFQ names none)")
    assert cf.deduction_line(2, "G3", 2, "Fig. 4, Table 7") == (
        "G3  2 inferred items: Fig. 4, Table 7")


def test_every_rule_renders_a_line():
    for code, rule in RULES.items():
        assert rule.label.format(count=2)
        line = cf.deduction_line(rule_points(rule, 2), code, 2, "item", "file")
        assert line.startswith(f"{code}  ")
        assert "{" not in line and "(s)" not in line


# ------------------------------------------------------------------ resolve
@pytest.mark.parametrize("section, entry, message", [
    (7, _entry("S3.1"), "Section 7 uses rule S3.1, which belongs to section 3"),
    (7, _entry("V1"), "Section 7 uses rule V1, which only the runner may write"),
    (7, _entry("X"), "unknown rule X"),
    (2, _entry("G3"), "Section 2 uses rule G3, which belongs to sections "
                      "1, 3-10 and 13"),
])
def test_resolve_names_the_bad_code(section, entry, message):
    with pytest.raises(ValueError, match=message):
        cf.resolve([entry], section)


def test_resolve_applies_the_section_13_mode():
    assert cf.resolve([_entry("G3")], ADDITIONAL_INFO_ID, "extracted")
    assert cf.resolve([_entry("S2.1")], ADDITIONAL_INFO_ID, "analysed")
    with pytest.raises(ValueError, match="Section 13 uses rule G3"):
        cf.resolve([_entry("G3")], ADDITIONAL_INFO_ID, "analysed")
    with pytest.raises(ValueError, match="Section 13 uses rule S2.1"):
        cf.resolve([_entry("S2.1")], ADDITIONAL_INFO_ID, "extracted")


def test_resolve_accepts_runner_rules_when_the_runner_writes_them():
    resolved = cf.resolve([_entry("V1", 1, '"SOP 2027"', 'quote: "SOP 2028"')],
                          9, allow_python=True)
    assert resolved[0]["line"] == (
        'V1  refuted by the reviewer: "SOP 2027" (quote: "SOP 2028")')
    with pytest.raises(ValueError, match="Section 2 uses rule V3"):
        cf.resolve([_entry("V3")], 2, allow_python=True)
    with pytest.raises(ValueError, match="Section 12 uses rule V1, which "
                                         "belongs to sections 1-11 and 13"):
        cf.resolve([_entry("V1")], 12, allow_python=True)


def test_resolve_rejects_a_count_below_one():
    with pytest.raises(ValueError, match="count"):
        cf.resolve([_entry("G3", 0)], 3)


# ---------------------------------------------------------- merge (resume)
def test_merge_python_deductions_is_idempotent():
    answer = {"id": 9, "deductions": [_entry("S9.1", 1, "SOP"),
                                      _entry("V1", 1, "old")]}
    fresh = [_entry("V1", 1, '"SOP 2027"'), _entry("V3", 1, '"A-Sample"')]
    cf.merge_python_deductions(answer, {"V1", "V3"}, fresh)
    once = [dict(entry) for entry in answer["deductions"]]
    cf.merge_python_deductions(answer, {"V1", "V3"}, fresh)
    assert answer["deductions"] == once == [_entry("S9.1", 1, "SOP"), *fresh]


def test_merge_python_deductions_without_existing_entries():
    answer = {"id": 9}
    cf.merge_python_deductions(answer, {"V3"}, [_entry("V3", 2)])
    assert answer["deductions"] == [_entry("V3", 2)]


# ------------------------------------------------------------ schema fields
def test_answer_and_question_carry_the_new_fields():
    answer = AnswerItem(id=7, answer="x",
                        deductions=[{"rule": "S7.1", "count": 4, "items": "PM"}],
                        shown={"found": 16, "shown": 13})
    assert answer.deductions[0].basis == "" and answer.shown.found == 16
    assert AnswerItem(id=2, answer="x").deductions == []
    question = Question(number=7, titleEn="t", titleDe="t", slides=[], score=7,
                        deductions=[{"rule": "S7.1", "points": 2}])
    assert question.score == 7
