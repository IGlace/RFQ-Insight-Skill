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
        "row (inferred) if the RFQ names no phases."]


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


def test_avl_is_not_looked_up():
    assert _problems(5, PARTIES.format("AVL List GmbH", "avl", "Calibration")) == []
    assert _problems(5, PARTIES.format("AVL", "third", "Calibration")) == []


def test_a_party_the_corpus_does_not_name_is_refused():
    problems = _problems(5, PARTIES.format("Globex", "supplier", "Sensors"))
    assert problems == [
        "Section 5 names the party 'Globex', which does not occur in the RFQ "
        "documents; copy the name as written, or tag the row (inferred)."]


def test_only_the_party_table_is_read():
    answer = ("| Item | Note |\n|---|---|\n| Globex | not a party table |")
    assert _problems(5, answer) == []


# --------------------------------------------------------------- exemptions
@pytest.mark.parametrize("number, answer", [
    (10, STANDARDS.format("ISO 9999 (inferred)")),
    (9, TIMING.format("Dec 2028 (inferred)")),
    (3, TARGETS.format("Torque (inferred) | 450 Nm")),
    (6, PHASES.format("Zeta Omega Rollout (Inferred)")),
    (7, SCOPE.format("TBD (inferred)", "AVL")),
    (8, DELIVERABLES.format("D1 Test report (inferred)")),
    (5, PARTIES.format("Globex", "supplier", "Sensors (inferred)")),
])
def test_inferred_rows_are_exempt(number, answer):
    assert _problems(number, answer) == []


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
