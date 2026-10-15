"""rfq.validation.check_faithfulness: what an extracted section copies from
the RFQ must occur in the documents (one pass and one miss per check)."""

import pytest

from helpers import CORPUS_TEXT, sample_analysis, sample_corpus
from rfq import validation as v


def _with(number, answer, extra=""):
    """(analysis, corpus): the sample with section `number` answered by
    `answer`, against the sample corpus extended by `extra`."""
    analysis = sample_analysis()
    analysis["answers"][number - 1]["answer"] = answer
    return analysis, sample_corpus(f"{CORPUS_TEXT} {extra}".strip())


def _problems(number, answer, extra=""):
    return v.check_faithfulness(*_with(number, answer, extra))


def test_the_sample_is_faithful_to_its_corpus():
    assert v.check_faithfulness(sample_analysis(), sample_corpus()) == []
    assert v.faithfulness_misses(sample_analysis(), sample_corpus()) == {}


def test_the_corpus_may_be_given_as_text():
    assert v.check_faithfulness(sample_analysis(), CORPUS_TEXT) == []


# ------------------------------------------------------------- standards
STANDARDS = "| Standard | Scope |\n|---|---|\n| {} | Functional safety |"


@pytest.mark.parametrize("cell, text", [
    ("ISO 26262:2018", "Apply ISO 26262:2018 throughout."),
    ("ISO 26262", "Apply ISO  26262-1 to the controller."),
    ("ISO 26262", "Apply ISO26262."),
    ("VDA 6.3", "Process audits per VDA 6.3."),
    ("GB/T 18488", "Motors follow GB/T 18488."),
    ("VW 80000 v2.1", "Electrical tests to VW 80000 version 2.1."),
])
def test_a_designation_the_corpus_holds_passes(cell, text):
    assert _problems(10, STANDARDS.format(cell), text) == []


def test_a_designation_the_corpus_lacks_is_named():
    problems = _problems(10, STANDARDS.format("ISO 26262:2018"),
                         "Apply ISO 26262:2011 throughout.")
    assert problems == [
        "Section 10 names 'ISO 26262:2018', which does not occur in the RFQ "
        "documents; copy the designation as written or remove it."]


def test_designations_are_case_sensitive():
    assert _problems(10, STANDARDS.format("VDA 6.3"), "process audits per vda 6.3.")


def test_a_designation_is_not_matched_inside_a_longer_number():
    assert _problems(10, STANDARDS.format("ISO 2626"), "ISO 26262 applies.")


def test_a_version_next_to_a_designation_must_occur():
    problems = _problems(10, STANDARDS.format("VW 80000 v2.2"),
                         "Electrical tests to VW 80000 version 2.1.")
    assert problems == [
        "Section 10 gives 'VW 80000' the version 'v2.2', which does not occur "
        "in the RFQ documents; copy the version as written or remove it."]


def test_a_trailing_full_stop_is_not_part_of_the_designation():
    assert _problems(10, "- ISO 26262.") == []


def test_a_trailing_hyphenated_word_is_not_part_of_the_designation():
    assert _problems(10, "- ISO 26262-compliant software") == []
    assert v.faithfulness_misses(*_with(10, "- DIN 70020-compliant")) == {10: ["DIN 70020"]}


def test_a_part_number_stays_part_of_the_designation():
    assert _problems(10, "- ISO 16750-2", "Environmental tests per ISO 16750-2.") == []
    assert v.faithfulness_misses(*_with(10, "- ISO 16750-6", "Tests per ISO 16750-2.")) \
        == {10: ["ISO 16750-6"]}


# ----------------------------------------------------------------- timing
TIMING = ("| Milestone | Target timing | Phase / Task |\n|---|---|---|\n"
          "| SOP | {} | Production |")


@pytest.mark.parametrize("cell", ["December 2028", "december  2028",
                                  "January 2027 – June 2027", "T0 + 6 weeks"])
def test_a_timing_cell_the_corpus_holds_passes(cell):
    assert _problems(9, TIMING.format(cell)) == []


def test_a_timing_cell_the_corpus_lacks_is_named():
    problems = _problems(9, TIMING.format("Dec 2028"))
    assert problems == [
        "Section 9 gives the target timing 'Dec 2028', which does not occur "
        "in the RFQ documents; copy the date as written, or tag the row "
        "(inferred) if you derived it."]


@pytest.mark.parametrize("cell, extra", [("KW 38/2026", "Freeze in KW38/2026."),
                                         ("KW38/2026", "Freeze in KW 38/2026.")])
def test_a_calendar_week_matches_with_or_without_the_space(cell, extra):
    assert _problems(9, TIMING.format(cell), extra) == []
    assert _problems(9, TIMING.format(cell), "Freeze in KW39/2026.")


def test_a_range_names_only_the_end_the_corpus_lacks():
    problems = _problems(9, TIMING.format("January 2027 – March 2027"))
    assert len(problems) == 1 and "'March 2027'" in problems[0]


# ---------------------------------------------------------- number + unit
TARGETS = "| Item | Target |\n|---|---|\n| {} |"


@pytest.mark.parametrize("row", ["Power | 220 kW", "Power | 220kW",
                                 "Emissions | Euro 7", "Duration | 20 hours"])
def test_a_value_the_corpus_holds_passes(row):
    assert _problems(3, TARGETS.format(row)) == []


def test_a_value_the_corpus_lacks_is_named():
    problems = _problems(3, TARGETS.format("Torque | 450 Nm"))
    assert problems == [
        "Section 3 states '450 Nm', which does not occur in the RFQ documents; "
        "copy the value and unit as written, tag the row (inferred) if you "
        "derived it, or remove it."]


def test_a_value_is_not_matched_inside_a_longer_number():
    assert _problems(3, TARGETS.format("Power | 20 kW"))


@pytest.mark.parametrize("row, extra", [
    ("Displacement | 3.5 l", "Displacement 3,5 l."),
    ("Displacement | 3,5 l", "Displacement 3.5 l."),
    ("Idle | 1,500 rpm", "Idle speed 1.500 rpm."),
    ("Idle | 1.500 rpm", "Idle speed 1,500 rpm."),
    ("Idle | 1500 rpm", "Idle speed 1,500 rpm."),
    ("Idle | 1,500 rpm", "Idle speed 1500 rpm."),
])
def test_decimal_and_thousands_separators_may_differ(row, extra):
    assert _problems(3, TARGETS.format(row), extra) == []


def test_a_different_number_with_swapped_separators_is_still_a_miss():
    assert _problems(3, TARGETS.format("Displacement | 3.5 l"), "Displacement 3,6 l.")


def test_a_single_letter_unit_before_a_hyphen_is_a_word():
    assert _problems(3, TARGETS.format("Builds | 2 A-Samples")) == []
    assert _problems(3, TARGETS.format("Current | 2 A")), "a real 2 A is still checked"


@pytest.mark.parametrize("extra", [
    "\n| Displacement | 2.996 | L |",
    "\n| 排量 Displacement | L | 2.996 |",        # the replay's corpus row
    "\n| Displacement | 2,996 | l |",
])
def test_a_number_and_its_unit_in_separate_cells_pass(extra):
    assert _problems(3, TARGETS.format("Displacement | 2.996 L"), extra) == []


@pytest.mark.parametrize("extra", [
    "\n| Power | 220 kW |",                       # 20 only inside 220
    "\n| Power | 20 | 220 kW |",                  # kW belongs to 220
    "\n| Power | 20 | kWh |",                     # a longer unit word
])
def test_a_unit_on_the_row_counts_only_for_its_own_number(extra):
    assert _problems(3, TARGETS.format("Power | 20 kW"), extra)


@pytest.mark.parametrize("extra", [
    "\n| Displacement | 2.996 | kW |",            # a different unit
    "\n| Displacement | 2.996 |\n| Unit | L |",   # the unit on another line
    "\n| Displacement | 2.996 | " + "x" * 61 + " L |",   # too far away
])
def test_a_bare_number_without_its_unit_nearby_is_still_a_miss(extra):
    assert _problems(3, TARGETS.format("Displacement | 2.996 L"), extra)


# ----------------------------------------------------------------- phases
PHASES = ("| Phase | Definition | Scope | Hardware milestone | Span |\n"
          "|---|---|---|---|---|\n| {} | First build | in scope | yes | |")


def test_a_phase_the_corpus_names_passes():
    assert _problems(6, PHASES.format("A-Sample")) == []
    assert _problems(6, PHASES.format("**A Sample**")) == []


def test_a_phase_the_corpus_does_not_name_is_refused():
    problems = _problems(6, PHASES.format("Zeta Omega Rollout"))
    assert problems == [
        "Section 6 names the phase 'Zeta Omega Rollout', which does not occur "
        "in the RFQ documents; use the phase name the RFQ gives, or tag the "
        "phase name (inferred) if the RFQ names no phases."]


# ------------------------------------------------------------ owner cells
SCOPE = ("| Scope of Work | Concept | A-Sample |\n|---|---|---|\n"
         "| Design | {} | {} |")


@pytest.mark.parametrize("cells", [("AVL", "Northwind"), ("Supplier", "Joint"),
                                   ("customer", "—"), ("-", ""), ("joint", "avl")])
def test_owner_cells_in_the_owner_set_pass(cells):
    assert _problems(7, SCOPE.format(*cells)) == []


def test_an_owner_cell_outside_the_owner_set_is_refused():
    problems = _problems(7, SCOPE.format("AVL", "Northwind + AVL"))
    assert problems == [
        "Section 7 row 'Design' has the owner 'Northwind + AVL'; every owner "
        "cell must be one of AVL, Supplier, Northwind, Customer, Joint, —."]


def test_an_inferred_tag_does_not_exempt_an_owner_cell():
    problems = _problems(7, SCOPE.format("TBD (inferred)", "AVL"))
    assert len(problems) == 1 and "'TBD (inferred)'" in problems[0]


def test_owner_cells_are_never_corpus_misses():
    analysis, corpus = _with(7, SCOPE.format("TBD", "AVL"))
    analysis["answers"][9]["answer"] = STANDARDS.format("ISO 9999")
    assert v.faithfulness_misses(analysis, corpus) == {10: ["ISO 9999"]}
    assert len(v.check_faithfulness(analysis, corpus)) == 2
    assert v.check_owner_cells(analysis) == [
        "Section 7 row 'Design' has the owner 'TBD'; every owner cell must be "
        "one of AVL, Supplier, Northwind, Customer, Joint, —."]


def test_owner_cells_follow_the_analysis_customer_short():
    analysis, corpus = _with(7, SCOPE.format("Aurobay", "AVL"))
    assert v.check_faithfulness(analysis, corpus)
    analysis["opportunity"]["customer_short"] = "Aurobay"
    assert v.check_faithfulness(analysis, corpus) == []


def test_the_owner_set_is_the_one_the_deck_evaluation_uses():
    assert v.OWNER_VALUES == {"avl", "supplier", "joint", "customer", "", "—", "-"}
    assert v.owner_allowed(" AVL ") and v.owner_allowed("Northwind", "Northwind")
    assert not v.owner_allowed("TBD", "Northwind")
    assert v.owner_columns(["Scope of Work", "Phase", "Concept"]) == [2]


# --------------------------------------------------------- deliverable ids
DELIVERABLES = "| Deliverable | Format |\n|---|---|\n| {} | PDF |"


@pytest.mark.parametrize("cell", ["D12 Test report", "WP3 Calibration", "D-4 Data sets"])
def test_a_deliverable_id_the_corpus_holds_passes(cell):
    extra = "Deliverables D12, D-4 and work package WP3."
    assert _problems(8, DELIVERABLES.format(cell), extra) == []


def test_a_deliverable_id_the_corpus_lacks_is_named():
    problems = _problems(8, DELIVERABLES.format("D1 Test report"),
                         "Deliverable D12.")
    assert problems == [
        "Section 8 names the deliverable 'D1', which does not occur in the RFQ "
        "documents; copy the deliverable id as written or remove it."]


# ------------------------------------------------------------ party names
PARTIES = "| Party | Type | Role |\n|---|---|---|\n| {} | {} | {} |"


def test_a_party_the_corpus_names_passes():
    assert _problems(5, PARTIES.format("Northwind Motors GmbH", "customer", "Lead")) == []
    assert _problems(5, PARTIES.format("acme", "supplier", "Injectors")) == []


def _section_5(analysis, corpus):
    return [p for p in v.check_faithfulness(analysis, corpus) if p.startswith("Section 5")]


def test_the_customer_row_may_carry_the_customer_short_form():
    analysis, corpus = _with(5, PARTIES.format("NWM", "customer", "Programme lead"))
    analysis["opportunity"]["customer_short"] = "NWM"
    assert "Northwind Motors GmbH" in corpus["filesContents"][0]["extracted_text"]
    assert _section_5(analysis, corpus) == []
    analysis, corpus = _with(5, PARTIES.format("nwm", "third", "Lead"))
    analysis["opportunity"]["customer_short"] = "NWM"
    assert _section_5(analysis, corpus) == [], "matched on the short form"
    analysis, corpus = _with(5, PARTIES.format("NWM", "customer", "Lead"))
    assert _section_5(analysis, corpus) == [], "matched on the type"
    analysis, corpus = _with(5, PARTIES.format("NWM", "third", "Lead"))
    assert _section_5(analysis, corpus), "neither: the name must occur"


def test_avl_is_not_looked_up():
    assert _problems(5, PARTIES.format("AVL List GmbH", "avl", "Calibration")) == []
    assert _problems(5, PARTIES.format("AVL", "third", "Calibration")) == []


def test_a_party_the_corpus_does_not_name_is_refused():
    problems = _problems(5, PARTIES.format("Globex", "supplier", "Sensors"))
    assert problems == [
        "Section 5 names the party 'Globex', which does not occur in the RFQ "
        "documents; copy the name as written, or tag the party name (inferred)."]


def test_only_the_party_table_is_read():
    answer = ("| Item | Note |\n|---|---|\n| Globex | not a party table |")
    assert _problems(5, answer) == []


# --------------------------------------------------------------- exemptions
@pytest.mark.parametrize("number, answer", [
    (10, STANDARDS.format("ISO 9999 (inferred)")),
    (9, TIMING.format("Dec 2028 (inferred)")),
    (3, TARGETS.format("Torque (inferred) | 450 Nm")),
    (6, PHASES.format("Zeta Omega Rollout (Inferred)")),
    (8, DELIVERABLES.format("D1 Test report (inferred)")),
    (5, PARTIES.format("Globex (inferred)", "supplier", "Sensors")),
])
def test_inferred_rows_are_exempt(number, answer):
    assert _problems(number, answer) == []


def test_in_sections_5_and_6_only_a_tagged_name_cell_is_exempt():
    """A derived Span or an inferred Role does not excuse an invented
    phase or party name (CONTRACT section 7, gate exemption precision)."""
    span = ("| Phase | Definition | Scope | Hardware milestone | Span |\n"
            "|---|---|---|---|---|\n"
            "| Zeta Omega Rollout | First build | in scope | yes | "
            "June 2027 – December 2028 (inferred) |")
    (problem,) = _problems(6, span)
    assert "'Zeta Omega Rollout'" in problem and "tag the phase name" in problem
    assert _problems(6, PHASES.format("Zeta Omega Rollout (inferred)")) == []
    (problem,) = _problems(5, PARTIES.format("Globex", "supplier", "Sensors (inferred)"))
    assert "'Globex'" in problem


def test_only_the_inferred_row_is_exempt():
    answer = ("| Item | Target |\n|---|---|\n| Torque (inferred) | 450 Nm |\n"
              "| Speed | 6500 rpm |")
    problems = _problems(3, answer)
    assert len(problems) == 1 and "'6500 rpm'" in problems[0]


def test_sections_outside_the_gate_are_not_checked():
    analysis, corpus = _with(2, "Apply ISO 9999 at 450 Nm from Dec 2028.")
    analysis["answers"][10]["answer"] = "## Project Risks\n- ISO 9999 is missing."
    assert v.check_faithfulness(analysis, corpus) == []


def test_a_malformed_analysis_has_no_misses():
    assert v.check_faithfulness("nope", sample_corpus()) == []
    assert v.check_faithfulness({"answers": ["oops", {"id": [3]}]}, None) == []


# ------------------------------------------------------------------ misses
def test_faithfulness_misses_groups_tokens_by_section_in_order():
    analysis = sample_analysis()
    analysis["answers"][9]["answer"] = (
        "| Standard | Scope |\n|---|---|\n| ISO 9999 | A |\n| ISO 26262 | B |\n"
        "| DIN 70020 | C |\n| ISO 9999 | again |")
    analysis["answers"][2]["answer"] = TARGETS.format("Torque | 450 Nm")
    misses = v.faithfulness_misses(analysis, sample_corpus())
    assert misses == {3: ["450 Nm"], 10: ["ISO 9999", "DIN 70020"]}
    assert len(v.check_faithfulness(analysis, sample_corpus())) == 3, "one problem per token"


# ------------------------------------------------- free text (follow-ups)
FREE_CORPUS = ("The review is on 19 December 2026 and SOP in Q3 2027. "
               "Apply ISO 26262:2018 and VW 80000 v2.1. Supply 9 to 16 V, "
               "peak 150 kW. Freeze 15.07.2026, gate KW 38/2026.")


@pytest.mark.parametrize("text", [
    "The review is on 19 December 2026.",
    "SOP is planned for Q3 2027.",
    "The freeze is 15.07.2026 and the gate KW38/2026.",
    "Apply ISO 26262:2018 and VW 80000 v2.1.",
    "The motor peaks at 150 kW on a 16 V supply.",
    "Nothing here is a date, a standard or a quantity.",
    "- A 48 V supply (inferred)",
])
def test_text_that_copies_the_documents_passes(text):
    assert v.check_text_faithfulness(text, FREE_CORPUS, "Follow-up") == []


@pytest.mark.parametrize("text, token", [
    ("The review is on 20 December 2026.", "20 December 2026"),
    ("SOP is planned for Q4 2027.", "Q4 2027"),
    ("The freeze is 16.07.2026.", "16.07.2026"),
    ("Start in March 2027.", "March 2027"),
    ("Apply ISO 21434.", "ISO 21434"),
    ("Apply VW 80000 v2.2.", "v2.2"),
    ("A 48 V supply.", "48 V"),
])
def test_text_that_does_not_copy_the_documents_is_named(text, token):
    (problem,) = v.check_text_faithfulness(text, FREE_CORPUS, "Follow-up")
    assert problem.startswith("Follow-up ") and f"'{token}'" in problem
    assert v.text_faithfulness_misses(text, FREE_CORPUS) == [token]


def test_free_text_accepts_a_corpus_dict_and_reports_each_token_once():
    corpus = sample_corpus(FREE_CORPUS)
    text = "ISO 21434 applies. ISO 21434 again, by 20 December 2026."
    assert v.text_faithfulness_misses(text, corpus) == [
        "ISO 21434", "20 December 2026"]
