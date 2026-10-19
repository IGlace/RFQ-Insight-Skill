"""rfq.validation: corpus, analysis and slide-plan gates, and the evaluation
run on a finalized report."""

import copy
import json

import pytest

from helpers import SOURCE_FILE, sample_analysis, sample_corpus, sample_plan
from rfq import confidence
from rfq import validation as v
from rfq.schema import TITLES

MARKED_TEXT = "--- Page 1 ---\nScope.\n--- Page 2 ---\nTiming."


def _deduction(rule, count=1, items="two cells", basis="SOR 3.2"):
    return {"rule": rule, "count": count, "items": items, "basis": basis}


# ----------------------------------------------------------------- corpus
def test_good_corpus_passes():
    assert v.check_corpus(sample_corpus()) == []


def test_empty_corpus_is_refused():
    problems = v.check_corpus({"projectName": "Demo", "filesContents": []})
    assert problems and "no files" in problems[0].lower()


def test_oversize_corpus_names_the_five_largest_files():
    files = [{"filename": f"f{n}.pdf", "extracted_text": "x" * 150_000}
             for n in range(6)] + [{"filename": "small.txt", "extracted_text": "x"}]
    problems = v.check_corpus({"projectName": "Demo", "filesContents": files})
    assert len(problems) == 1
    message = problems[0]
    assert "900,001 characters" in message
    assert "600,000" in message
    assert message.count("150,000 chars") == 5      # five largest, not six
    assert "small.txt" not in message


def test_corpus_at_the_limit_passes():
    files = [{"filename": "f.pdf", "extracted_text": "x" * v.MAX_CORPUS_CHARS}]
    assert v.check_corpus({"filesContents": files}) == []


def test_corpus_entry_missing_text_is_reported():
    corpus = {"projectName": "Demo", "filesContents": [{"filename": "SOR.docx"}]}
    assert any("extracted_text" in p for p in v.check_corpus(corpus))


def test_a_non_object_corpus_is_reported_not_crashed():
    assert v.check_corpus(["not", "a", "dict"]) != []
    assert v.check_corpus({"filesContents": "not a list"}) != []


def test_a_non_object_corpus_entry_is_reported_and_the_rest_still_checked():
    corpus = {"projectName": "Demo", "filesContents": ["oops", {"filename": "SOR.docx"}]}
    problems = v.check_corpus(corpus)
    assert any("not objects" in p for p in problems)
    assert any("extracted_text" in p for p in problems)


# --------------------------------------------------------------- analysis
def test_good_analysis_passes_with_and_without_the_corpus():
    assert v.check_analysis(sample_analysis()) == []
    assert v.check_analysis(sample_analysis(), sample_corpus()) == []


def test_missing_section_is_named():
    analysis = sample_analysis()
    analysis["answers"] = [a for a in analysis["answers"] if a["id"] != 7]
    assert any("Missing section(s): 7" in p for p in v.check_analysis(analysis))


def test_section_13_is_not_an_analysis_section():
    analysis = sample_analysis()
    extra = dict(analysis["answers"][-1], id=13)
    analysis["answers"].append(extra)
    assert any("Unknown section id(s): 13" in p for p in v.check_analysis(analysis))


def test_section_12_is_optional_and_ignored():
    analysis = sample_analysis()
    assert analysis["answers"][-1]["id"] == 12
    analysis["answers"][-1].update(answer="", deductions="not a list",
                                   sources=[{"filename": "gone.pdf"}])
    assert v.check_analysis(analysis, sample_corpus()) == []
    analysis["answers"].pop()
    assert v.check_analysis(analysis, sample_corpus()) == []


def test_strip_python_sections_drops_source_material_only():
    analysis = sample_analysis()
    assert v.strip_python_sections(analysis) is analysis
    assert [a["id"] for a in analysis["answers"]] == list(range(1, 12))
    assert v.strip_python_sections({"answers": "no"}) == {"answers": "no"}


def test_check_analysis_does_not_strip_the_callers_analysis():
    analysis = sample_analysis()
    v.check_analysis(analysis)
    assert analysis["answers"][-1]["id"] == 12


def test_sections_out_of_order_are_refused():
    analysis = sample_analysis()
    answers = analysis["answers"]
    answers[0], answers[1] = answers[1], answers[0]
    assert any("ascending" in p.lower() for p in v.check_analysis(analysis))


def test_a_repeated_section_id_is_refused():
    analysis = sample_analysis()
    analysis["answers"][3]["id"] = 3
    assert any("more than once" in p for p in v.check_analysis(analysis))


def test_the_answer_fields():
    assert v.ANSWER_FIELDS == ("id", "answer", "not_found", "deductions", "sources")


@pytest.mark.parametrize("field", v.ANSWER_FIELDS)
def test_every_answer_field_is_required(field):
    analysis = sample_analysis()
    del analysis["answers"][3][field]
    assert any(f"'{field}'" in p and "Section" in p for p in v.check_analysis(analysis))


def test_empty_answer_text_is_refused():
    analysis = sample_analysis()
    analysis["answers"][1]["answer"] = "  "
    assert any("Section 2 has an empty answer" in p for p in v.check_analysis(analysis))


@pytest.mark.parametrize("field", ["tldr", "confidence", "confidence_reason",
                                   "presentation"])
def test_the_retired_answer_fields_are_refused(field):
    analysis = sample_analysis()
    analysis["answers"][4][field] = "x"
    (problem,) = v.check_analysis(analysis)
    assert "does not match the required shape" in problem and field in problem


def test_allowed_deductions_pass():
    analysis = sample_analysis()
    analysis["answers"][6]["deductions"] = [_deduction("S7.1", 4), _deduction("G3")]
    analysis["answers"][1]["deductions"] = [_deduction("S2.1", 2)]
    assert v.check_analysis(analysis) == []


def test_deductions_must_be_a_list_of_objects():
    analysis = sample_analysis()
    analysis["answers"][6]["deductions"] = ["S7.1"]
    analysis["answers"][7]["deductions"] = {"rule": "G1"}
    problems = v.check_analysis(analysis)
    assert any("Section 7 'deductions' must be a list of objects" in p for p in problems)
    assert any("Section 8 'deductions' must be a list of objects" in p for p in problems)


def test_an_unknown_code_is_refused_with_the_codes_the_section_allows():
    analysis = sample_analysis()
    analysis["answers"][6]["deductions"] = [_deduction("S7.9")]
    (problem,) = [p for p in v.check_analysis(analysis) if "S7.9" in p]
    assert problem.startswith("Section 7 uses unknown rule S7.9.")
    assert "Use one of: G3, S7.1, S7.2, S7.3." in problem


@pytest.mark.parametrize("number, code", [
    (1, "S1.2"), (2, "S2.2"), (3, "G1"), (3, "S3.3"), (5, "G2"), (5, "S5.1"),
    (9, "G4"),
    (10, "G5"), (11, "S11.3"), (11, "S11.4")])
def test_a_removed_code_is_refused_as_unknown(number, code):
    """Only content not taken from the RFQ costs points: the rules that
    priced contradictions, evidence limits, an unnamed contractor or the
    section 1 splits are gone."""
    analysis = sample_analysis()
    analysis["answers"][number - 1]["deductions"] = [_deduction(code)]
    assert any(p.startswith(f"Section {number} uses unknown rule {code}.")
               for p in v.check_analysis(analysis))


def test_section_1_accepts_g3_for_an_inferred_identity_field():
    analysis = sample_analysis()
    analysis["answers"][0]["deductions"] = [
        _deduction("G3", items="Customer site", basis="letterhead only")]
    assert v.check_analysis(analysis) == []
    problem, = [p for p in v.check_analysis(
        {**analysis, "answers": [{**analysis["answers"][0],
                                  "deductions": [_deduction("S7.1")]},
                                 *analysis["answers"][1:]]})
        if p.startswith("Section 1 ")]
    assert problem.endswith("Use one of: G3, P1, P2.")


def test_the_faithfulness_gate_never_checks_section_1():
    analysis = sample_analysis()
    analysis["answers"][0]["answer"] = (
        "| Field | Value |\n|---|---|\n"
        "| Customer site | Invented Road 99, 12345 Nowhere (inferred) |\n"
        "| Quotation due date | 2031-01-01 |")
    assert not [p for p in v.check_faithfulness(analysis, "unrelated text")
                if p.startswith("Section 1 ")]
    assert 1 not in v.faithfulness_misses(analysis, "unrelated text")


def test_a_code_of_another_section_is_refused():
    analysis = sample_analysis()
    analysis["answers"][1]["deductions"] = [_deduction("G3"), _deduction("S7.1")]
    problems = v.check_analysis(analysis)
    assert any(p.startswith("Section 2 uses rule G3, which belongs to sections 1, 3-10 and 13.")
               for p in problems)
    assert any(p.startswith("Section 2 uses rule S7.1, which belongs to section 7.")
               for p in problems), "every bad entry is reported, not only the first"


@pytest.mark.parametrize("code", ["V1", "V3"])
def test_a_v_code_from_the_model_is_refused(code):
    analysis = sample_analysis()
    analysis["answers"][9]["deductions"] = [_deduction(code)]
    assert any(f"Section 10 uses rule {code}, which only the runner may write." in p
               for p in v.check_analysis(analysis))


def test_runner_codes_are_accepted_in_a_stored_analysis():
    analysis = sample_analysis()
    analysis["answers"][9]["deductions"] = [_deduction("S10.1"), _deduction("V3"),
                                            _deduction("V1")]
    assert v.check_analysis(analysis, runner_codes=v.RUNNER_CODES) == []
    problems = v.check_analysis(analysis, runner_codes=("V3",))
    assert [p for p in problems if "V1" in p] and not [p for p in problems if "V3" in p]
    assert set(v.RUNNER_CODES) == {"V1", "V3"}


def test_a_runner_entry_may_list_more_than_25_words():
    analysis = sample_analysis()
    analysis["answers"][9]["deductions"] = [_deduction("V3", 30, items="ISO 1, " * 30)]
    assert v.check_analysis(analysis, runner_codes=("V3",)) == []


def test_a_count_below_one_is_refused():
    analysis = sample_analysis()
    analysis["answers"][2]["deductions"] = [_deduction("S3.1", 0)]
    assert any("Section 3 rule S3.1 needs a count of at least 1" in p
               for p in v.check_analysis(analysis))


def test_the_deduction_schema_refuses_a_count_below_one():
    from pydantic import ValidationError
    from rfq.schema import Deduction
    assert Deduction.model_validate({"rule": "G3"}).count == 1
    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        Deduction.model_validate({"rule": "G3", "count": 0})
    analysis = sample_analysis()
    analysis["answers"][2]["deductions"] = [_deduction("S3.1", 0)]
    assert any("does not match the required shape" in p and "count" in p
               for p in v.check_analysis(analysis))


def test_a_model_code_listed_twice_in_a_section_is_a_repair_problem():
    analysis = sample_analysis()
    analysis["answers"][6]["deductions"] = [_deduction("S7.1", 2), _deduction("G3"),
                                            _deduction("S7.1", 3)]
    assert ("Section 7 lists rule S7.1 twice; merge the entries into one with "
            "the total count.") in v.check_analysis(analysis)
    analysis["answers"][6]["deductions"].append(_deduction("S7.1"))
    assert any(p.startswith("Section 7 lists rule S7.1 3 times")
               for p in v.check_analysis(analysis))
    # The runner writes one entry per refuted claim or missing token.
    analysis = sample_analysis()
    analysis["answers"][9]["deductions"] = [_deduction("V1"), _deduction("V1")]
    assert v.check_analysis(analysis, runner_codes=v.RUNNER_CODES) == []


def test_deduction_items_are_at_most_25_words():
    analysis = sample_analysis()
    analysis["answers"][6]["deductions"] = [_deduction("S7.1", items="word " * 25)]
    assert v.check_analysis(analysis) == []
    analysis["answers"][6]["deductions"] = [_deduction("S7.1", items="word " * 26)]
    assert "Section 7 deduction S7.1: items must be at most 25 words" in v.check_analysis(analysis)


@pytest.mark.parametrize("number", [2, 3, 7, 10, 11])
def test_shown_is_allowed_on_trimmed_sections(number):
    analysis = sample_analysis()
    analysis["answers"][number - 1]["shown"] = {"found": 16, "shown": 13}
    assert v.check_analysis(analysis) == []


@pytest.mark.parametrize("number", [1, 4, 5, 6, 8, 9])
def test_shown_on_another_section_is_refused(number):
    analysis = sample_analysis()
    analysis["answers"][number - 1]["shown"] = {"found": 5, "shown": 4}
    assert any(p.startswith(f"Section {number} has 'shown', which only sections "
                            "2, 3, 7, 10 and 11 may carry")
               for p in v.check_analysis(analysis))


@pytest.mark.parametrize("shown", [{"found": 3, "shown": 4}, {"found": 3, "shown": 0},
                                   {"found": "3", "shown": 2}, {"found": 3},
                                   {"found": True, "shown": 1}, [16, 13]])
def test_shown_needs_whole_numbers_with_found_at_least_shown(shown):
    analysis = sample_analysis()
    analysis["answers"][9]["shown"] = shown
    assert any("Section 10 'shown' must be" in p for p in v.check_analysis(analysis))


def test_sources_are_checked_against_the_corpus_when_given():
    analysis = sample_analysis()
    analysis["answers"][1]["sources"] = [{"filename": "missing.pdf", "locator": ""}]
    assert v.check_analysis(analysis) == []
    problems = v.check_analysis(analysis, sample_corpus())
    assert any("Section 2 source #1: 'missing.pdf' is not a corpus file" in p
               for p in problems)


def test_an_answered_section_without_sources_is_refused_with_the_corpus():
    analysis = sample_analysis()
    analysis["answers"][1]["sources"] = []
    assert any("Section 2 has no sources" in p
               for p in v.check_analysis(analysis, sample_corpus()))
    analysis["answers"][1]["not_found"] = True
    assert v.check_analysis(analysis, sample_corpus()) == []


def test_a_marked_file_needs_a_location_except_in_source_material():
    analysis = sample_analysis()
    problems = v.check_analysis(analysis, sample_corpus(MARKED_TEXT))
    assert any("Section 2 source #1" in p and "requires a specific location" in p
               for p in problems)
    assert not any("Section 12" in p for p in problems)
    for answer in analysis["answers"]:
        answer["sources"] = [{"filename": SOURCE_FILE, "locator": "p. 2"}]
    assert v.check_analysis(analysis, sample_corpus(MARKED_TEXT)) == []


def test_a_location_the_file_does_not_have_is_refused():
    analysis = sample_analysis()
    analysis["answers"][8]["sources"] = [{"filename": SOURCE_FILE, "locator": "p. 9"}]
    problems = v.check_analysis(analysis, sample_corpus(MARKED_TEXT))
    assert any("Section 9 source #1" in p and "has no page 9" in p for p in problems)


def test_a_shape_failure_does_not_hide_the_other_problems():
    analysis = sample_analysis()
    del analysis["answers"][0]["id"]
    analysis["answers"][4]["deductions"] = [_deduction("V1")]
    problems = v.check_analysis(analysis)
    assert any("required shape" in p for p in problems)
    assert any("Section 5 uses rule V1" in p for p in problems)


def test_a_non_object_answer_is_reported_and_the_rest_still_checked():
    analysis = sample_analysis()
    analysis["answers"][2] = "oops"
    analysis["answers"][5]["deductions"] = [_deduction("X1")]
    problems = v.check_analysis(analysis)
    assert any("not objects" in p for p in problems)
    assert any("required shape" in p for p in problems)
    assert any("Section 6 uses unknown rule X1" in p for p in problems)


def test_an_unhashable_id_is_reported_not_crashed():
    analysis = sample_analysis()
    analysis["answers"][2]["id"] = [3]
    assert any("Unknown section id(s)" in p for p in v.check_analysis(analysis))


def test_answers_must_be_a_list():
    assert any("must be a list" in p for p in v.check_analysis({"answers": "no"}))


# ------------------------------------------------------------ opportunity
def test_a_missing_opportunity_object_is_refused():
    analysis = sample_analysis()
    del analysis["opportunity"]
    assert any("no 'opportunity' object" in p for p in v.check_analysis(analysis))


@pytest.mark.parametrize("field", ["project_type", "technology", "industry"])
def test_vocabulary_fields_must_be_official_values(field):
    analysis = sample_analysis()
    analysis["opportunity"][field] = "Something else"
    problems = v.check_analysis(analysis)
    assert any(f"opportunity.{field} is 'Something else'" in p for p in problems)


def test_unknown_product_and_skill_names_are_refused():
    analysis = sample_analysis()
    analysis["opportunity"]["products"] = [{"name": "Engines", "percent": 100}]
    analysis["opportunity"]["skills"] = [{"name": "Tuning", "percent": 100}]
    problems = v.check_analysis(analysis)
    assert any("opportunity.products: 'Engines' is not an official" in p for p in problems)
    assert any("opportunity.skills: 'Tuning' is not an official" in p for p in problems)


def test_percentages_must_add_up_to_100():
    analysis = sample_analysis()
    analysis["opportunity"]["skills"] = [{"name": "Calibration", "percent": 60},
                                         {"name": "Design", "percent": 30}]
    assert any("opportunity.skills percentages add up to 90" in p
               for p in v.check_analysis(analysis))


@pytest.mark.parametrize("percent", [0, 101, "50", 50.0, True, None])
def test_percentages_are_whole_numbers_from_1_to_100(percent):
    analysis = sample_analysis()
    analysis["opportunity"]["products"] = [{"name": "Spark Ignited", "percent": percent}]
    assert any("opportunity.products: 'Spark Ignited' has percent" in p
               for p in v.check_analysis(analysis))


def test_a_name_listed_twice_is_refused():
    analysis = sample_analysis()
    analysis["opportunity"]["products"] = [{"name": "Spark Ignited", "percent": 50},
                                           {"name": "Spark Ignited", "percent": 50}]
    assert any("lists a name twice" in p for p in v.check_analysis(analysis))


def test_empty_percent_lists_are_refused():
    analysis = sample_analysis()
    analysis["opportunity"]["skills"] = []
    assert any("opportunity.skills must list at least one item" in p
               for p in v.check_analysis(analysis))


def test_lead_product_needs_at_least_five_percent():
    analysis = sample_analysis()
    analysis["opportunity"]["products"] = [
        {"name": "Spark Ignited", "percent": 4},
        {"name": "Battery", "percent": 96}]
    problems = v.check_analysis(analysis)
    assert any("opportunity.lead_product 'Spark Ignited' must be one of the listed "
               "products with at least 5%: Battery" in p for p in problems)
    analysis["opportunity"]["products"][0]["percent"] = 5
    analysis["opportunity"]["products"][1]["percent"] = 95
    assert v.check_analysis(analysis) == []


def test_opportunity_name_joins_short_and_title_with_an_en_dash():
    analysis = sample_analysis()
    analysis["opportunity"]["opportunity_name"] = "Northwind - V6 Engine Calibration"
    problems = v.check_analysis(analysis)
    assert any("opportunity.opportunity_name must be exactly" in p
               and "–" in p for p in problems)


def test_customer_short_and_project_title_are_required():
    analysis = sample_analysis()
    analysis["opportunity"]["project_title"] = ""
    assert any("customer_short and opportunity.project_title must both be filled" in p
               for p in v.check_analysis(analysis))


@pytest.mark.parametrize("field", ["account_name", "kam_pte"])
def test_account_fields_are_left_to_the_pipeline(field):
    analysis = sample_analysis()
    analysis["opportunity"][field] = "Bosch (Stuttgart)"
    assert any(f"opportunity.{field} must be 'Info not available'" in p
               for p in v.check_analysis(analysis))


def test_check_opportunity_values_without_the_name_rule():
    info = sample_analysis()["opportunity"]
    info["opportunity_name"] = "whatever"
    assert v.check_opportunity_values(info) != []
    assert v.check_opportunity_values(info, require_name=False) == []
    assert v.check_opportunity_values("no") != []


# -------------------------------------------------------------- slide plan
def test_good_plan_passes():
    assert v.check_plan(sample_plan()) == []


def test_section_13_is_rejected_in_the_draft():
    plan = sample_plan()
    plan["questions"].insert(11, {"number": 13, "titleEn": "Additional Information",
                                  "titleDe": "Zusätzliche Informationen",
                                  "slides": [{"layout": "bullets", "title": "Additional Information",
                                              "bullets": [{"text": "x"}]}]})
    problems = v.check_plan(plan)
    assert any("canonical order" in p for p in problems)
    assert any("Question 13 is not one of the 12 sections" in p for p in problems)


def test_plan_with_a_wrong_title_is_refused():
    plan = sample_plan()
    plan["questions"][6]["titleEn"] = "Scope of Work"
    plan["questions"][6]["titleDe"] = "Umfang"
    problems = v.check_plan(plan)
    assert any("Question 7 titleEn is 'Scope of Work'" in p for p in problems)
    assert any("Question 7 titleDe is 'Umfang'" in p for p in problems)


def test_plan_with_an_unknown_layout_is_refused():
    plan = sample_plan()
    plan["questions"][2]["slides"][0] = {"layout": "carousel", "title": "X"}
    assert any("unknown layout 'carousel'" in p for p in v.check_plan(plan))


def test_plan_with_a_question_with_no_slides_is_refused():
    plan = sample_plan()
    plan["questions"][2]["slides"] = []
    assert any("Question 3 has no slides" in p for p in v.check_plan(plan))


def test_plan_missing_a_question_is_refused():
    plan = sample_plan()
    plan["questions"] = plan["questions"][:11]
    assert any("Missing question(s): 12" in p for p in v.check_plan(plan))


def test_section_1_must_be_exactly_one_opportunity_slide():
    plan = sample_plan()
    plan["questions"][0]["slides"] = [{"layout": "bullets", "title": "Opportunity Info",
                                       "bullets": [{"text": "Customer: Northwind"}]}]
    assert any("Question 1 (Opportunity Info) must be exactly one 'opportunity' slide" in p
               for p in v.check_plan(plan))
    plan["questions"][0]["slides"] = [{"layout": "opportunity", "title": "Opportunity Info"}] * 2
    assert any("Question 1 (Opportunity Info) must be exactly one" in p
               for p in v.check_plan(plan))


def test_collaboration_needs_one_collab_slide_with_two_parties():
    plan = sample_plan()
    plan["questions"][4]["slides"][0]["parties"] = [{"name": "AVL", "type": "avl"}]
    assert any("Question 5 (Collaboration Approach) must show at least the customer and AVL" in p
               for p in v.check_plan(plan))
    plan["questions"][4]["slides"] = [{"layout": "bullets", "title": "Collaboration Approach",
                                       "bullets": [{"text": "AVL and Northwind"}]}]
    assert any("Question 5 (Collaboration Approach) must be exactly one 'collab' slide" in p
               for p in v.check_plan(plan))


@pytest.mark.parametrize("number,slides,expected", [
    (3, [{"layout": "bullets", "title": TITLES[3][0], "bullets": [{"text": "x"}]}],
     "it must be exactly table"),
    (2, [{"layout": "prose", "title": TITLES[2][0], "body": "a"}] * 3,
     "it must be exactly prose or prose + prose"),
    (9, [{"layout": "table", "title": TITLES[9][0], "columns": ["a"], "rows": [["b"]]}],
     "it must be exactly gantt + table or timeline + table"),
    (7, [{"layout": "table", "title": TITLES[7][0], "columns": ["a"], "rows": [["b"]]}],
     "it must be exactly ownership"),
    (11, [{"layout": "panel", "title": "Risk Detection", "heading": "Project Risks",
           "items": ["x"]}],
     "it must be exactly panel + panel"),
])
def test_section_shapes_are_enforced(number, slides, expected):
    plan = sample_plan()
    plan["questions"][number - 1]["slides"] = slides
    problems = v.check_plan(plan)
    assert any(f"Question {number} ({TITLES[number][0]}) has slides" in p and expected in p
               for p in problems), problems


def test_a_section_may_not_grow_an_extra_slide():
    plan = sample_plan()
    plan["questions"][7]["slides"].append(
        {"layout": "table", "title": "AVL Deliverables — Extra", "columns": ["a"], "rows": [["b"]]})
    assert any("Question 8 (AVL Deliverables) has slides table + table" in p
               for p in v.check_plan(plan))


def test_alternative_shapes_pass():
    plan = sample_plan()
    plan["questions"][5]["slides"] = [{"layout": "table", "title": TITLES[6][0],
                                       "columns": ["Phase", "Scope"], "rows": [["Concept", "x"]]}]
    plan["questions"][8]["slides"][0] = {"layout": "timeline", "title": TITLES[9][0],
                                         "steps": [{"label": "SOP", "date": "2028", "desc": ""}]}
    plan["questions"][9]["slides"] = [{"layout": "bullets", "title": TITLES[10][0],
                                       "bullets": [{"text": "ISO 26262"}]}]
    plan["questions"][11]["slides"] = [{"layout": "table", "title": TITLES[12][0],
                                        "columns": ["File"], "rows": [[SOURCE_FILE]]}]
    assert v.check_plan(plan) == []


def test_risk_panels_must_not_be_empty():
    plan = sample_plan()
    plan["questions"][10]["slides"][1]["items"] = []
    assert any("Question 11 (Risk Detection): both risk panels must carry at least one item" in p
               for p in v.check_plan(plan))


def test_a_non_object_question_is_reported_not_crashed():
    plan = sample_plan()
    plan["questions"][4] = "oops"
    assert any("not objects" in p for p in v.check_plan(plan))


def test_a_non_object_slide_is_reported_not_crashed():
    plan = sample_plan()
    plan["questions"][2]["slides"] = ["oops"]
    assert any("not an object" in p for p in v.check_plan(plan))


def test_plan_that_cannot_render_is_refused_before_finalize():
    plan = sample_plan()
    plan["questions"][2]["slides"][0] = {"layout": "table", "title": "X"}
    problems = v.check_plan(plan)
    assert problems != []
    assert any("layout needs" in p for p in problems)


def test_questions_must_be_a_list():
    assert any("'questions' must be a list" in p for p in v.check_plan({"questions": 3}))


# ------------------------------------------------------------- evaluation
def _scored(report):
    """Every section rated 10/10 with notes in the scored format, as the
    deck's notes read once delivery scores the sections from their
    deductions."""
    for question in report["slidePlan"]["questions"]:
        question["confidence"], question["score"] = "high", 10
        question["confidenceNotes"] = confidence.notes(
            10, "high", [], "Check: nothing needed a separate reviewer.", "",
            question.get("sourceDetails") or "")
    return report


@pytest.fixture(scope="module")
def finalized():
    from rfq import delivery
    plan, deck, report = delivery.finalize(sample_corpus(), sample_analysis(), sample_plan())
    return _scored(report)


@pytest.fixture
def report(finalized):
    return copy.deepcopy(finalized)


def _labels(lines):
    return {line.split(" ", 1)[0] for line in lines}


def _question(report, number):
    return next(q for q in report["slidePlan"]["questions"] if q["number"] == number)


def test_a_finalized_report_passes_every_check_and_warning(report):
    fails, warns, oks = v.evaluate(report, sample_corpus()["filesContents"][0]["extracted_text"])
    assert fails == []
    assert warns == []
    assert _labels(oks) == {"C1", "C1b", "C9", "C2", "C3", "C4", "C5", "C6", "C7", "C8",
                            "W1", "W2", "W3", "W4", "W5", "W6"}


def test_evaluation_without_corpus_text_skips_the_corpus_checks(report):
    fails, warns, oks = v.evaluate(report)
    assert fails == [] and warns == []
    assert "C2" not in _labels(oks) and "W2" not in _labels(oks)


def test_c1_missing_analysis_section(report):
    report["analysis"]["answers"] = [a for a in report["analysis"]["answers"] if a["id"] != 4]
    fails, _, _ = v.evaluate(report)
    assert any(f.startswith("C1 ") and "MISSING [4]" in f for f in fails)


def test_c1_does_not_need_the_source_material_answer(report):
    report["analysis"]["answers"] = [a for a in report["analysis"]["answers"] if a["id"] != 12]
    fails, _, oks = v.evaluate(report)
    assert fails == [] and "C1 sections 1-11 present" in oks


def test_c1b_plan_sections_out_of_canonical_order(report):
    questions = report["slidePlan"]["questions"]
    questions[1], questions[2] = questions[2], questions[1]
    fails, _, _ = v.evaluate(report)
    assert any(f.startswith("C1b") for f in fails)


def test_c9_invalid_final_plan_structure(report):
    _question(report, 3)["slides"][0]["layout"] = "carousel"
    fails, _, _ = v.evaluate(report)
    assert any(f.startswith("C9 final plan structure is invalid") for f in fails)


def test_c9_opportunity_tables_must_match_the_analysis(report):
    _question(report, 1)["slides"][0]["rows"][0][1] = "Someone else"
    fails, _, _ = v.evaluate(report)
    assert any(f.startswith("C9") and "rows differ" in f for f in fails)


def test_c2_untraceable_phase_names_fail(report):
    _question(report, 6)["slides"][0]["phases"].append({"name": "Zeta Omega Rollout", "desc": ""})
    fails, _, _ = v.evaluate(report, "Concept and A-Sample phases apply.")
    assert any(f.startswith("C2") and "Zeta Omega Rollout" in f for f in fails)


def test_c3_literal_tags_fail(report):
    _question(report, 2)["slides"][0]["body"] = "Due in June (assessment)."
    fails, _, _ = v.evaluate(report)
    assert any(f.startswith("C3") and "(assessment)" in f.lower() for f in fails)
    # "(inferred)" is no stray tag: the slide shows it beside the item.
    _question(report, 2)["slides"][0]["body"] = "Due in June (inferred)."
    fails, _, _ = v.evaluate(report)
    assert not any(f.startswith("C3") for f in fails)


def test_c3_ignores_the_speaker_notes(report):
    _question(report, 2)["confidenceNotes"] += "\n- Quote: due in June (inferred)"
    fails, _, oks = v.evaluate(report)
    assert fails == [] and "C3" in _labels(oks)


def test_c4_ownership_cells_must_be_owners(report):
    _question(report, 7)["slides"][0]["rows"][0][1] = "TBD"
    fails, _, _ = v.evaluate(report)
    assert any(f.startswith("C4") and "TBD" in f for f in fails)


def test_c5_timeline_disorder_warns_only(report):
    steps = _question(report, 9)["slides"][0]["steps"]
    steps[0], steps[2] = steps[2], steps[0]
    fails, warns, _ = v.evaluate(report)
    assert fails == []
    assert any(w.startswith("C5") for w in warns)


def test_c6_first_slide_title_must_be_the_section_title(report):
    _question(report, 8)["slides"][0]["title"] = "Deliverables"
    fails, _, _ = v.evaluate(report)
    assert any(f.startswith("C6") and "Deliverables" in f for f in fails)


def test_c7_source_references_must_be_in_the_notes(report):
    _question(report, 4)["sourceDetails"] = None
    fails, _, _ = v.evaluate(report)
    assert any(f.startswith("C7") and "MISSING" in f and "Application Approach" in f
               for f in fails)


def test_c7_answered_section_may_not_lose_its_sources(report):
    from rfq.sources import NOT_FOUND_LINE
    _question(report, 4)["sourceDetails"] = NOT_FOUND_LINE
    fails, _, _ = v.evaluate(report)
    assert any(f.startswith("C7") and "NOT FOUND although answered" in f for f in fails)


def test_c8_confidence_must_be_explained(report):
    _question(report, 5)["confidenceNotes"] = ""
    fails, _, _ = v.evaluate(report)
    assert any(f.startswith("C8") and "Collaboration Approach" in f for f in fails)


@pytest.mark.parametrize("notes", [
    "CONFIDENCE: HIGH\n\nReason:\nStated in the SOR.",
    "Confidence 11/10 (High)", "Confidence 7/10 (high)", "Confidence 0/10 (Low)",
    "Score 7/10 (High)", " Confidence 7/10 (High)"])
def test_c8_notes_must_open_with_the_score_and_band(report, notes):
    _question(report, 6)["confidenceNotes"] = notes
    fails, _, _ = v.evaluate(report)
    assert any(f.startswith("C8") and "Development Phases" in f for f in fails), fails


def test_c8_accepts_the_legacy_header_only_in_an_unscored_report(report):
    """`rfq_run.py evaluate` still works on a 1.0 report (no deductions,
    notes opening "CONFIDENCE: HIGH"); a scored report must use the score."""
    legacy = "CONFIDENCE: HIGH\n\nReason:\nStated in the SOR."
    _question(report, 6)["confidenceNotes"] = legacy
    fails, _, _ = v.evaluate(report)
    assert any(f.startswith("C8") for f in fails), "scored: the score is required"
    for answer in report["analysis"]["answers"]:
        answer.pop("deductions", None)
    fails, _, oks = v.evaluate(report)
    assert not any(f.startswith("C8") for f in fails) and "C8" in _labels(oks)
    _question(report, 6)["confidenceNotes"] = "CONFIDENCE: certain"
    fails, _, _ = v.evaluate(report)
    assert any(f.startswith("C8") and "Development Phases" in f for f in fails)


@pytest.mark.parametrize("header", ["Confidence 10/10 (High)", "Confidence 5/10 (Medium)",
                                    "Confidence 1/10 (Low)"])
def test_c8_accepts_every_score_and_band(report, header):
    _question(report, 6)["confidenceNotes"] = header + "\n-2  S6.2  calendar spans derived"
    fails, _, oks = v.evaluate(report)
    assert fails == [] and "C8" in _labels(oks)


def test_c8_skips_an_unrated_section(report):
    question = _question(report, 6)
    question["confidence"], question["confidenceNotes"] = "", ""
    fails, warns, oks = v.evaluate(report)
    assert fails == [] and "C8" in _labels(oks)
    assert any(w.startswith("W3") for w in warns)


def test_w1_description_scope(report):
    question = _question(report, 2)
    question["slides"] = question["slides"] * 3
    _, warns, _ = v.evaluate(report)
    assert any(w.startswith("W1") and "3 slides" in w for w in warns)
    question["slides"] = question["slides"][:1]
    question["slides"][0]["body"] = "word " * 301
    _, warns, _ = v.evaluate(report)
    assert any(w.startswith("W1") and "300 words" in w for w in warns)


def test_w2_standards_not_in_the_corpus_warn(report):
    _, warns, _ = v.evaluate(report, "Nothing about norms here.")
    assert any(w.startswith("W2") and "ISO 26262" in w for w in warns)


def test_w3_missing_confidence_warns(report):
    _question(report, 10)["confidence"] = ""
    _, warns, _ = v.evaluate(report)
    assert any(w.startswith("W3") and "Customer Specific Standards" in w for w in warns)


def test_w4_thin_two_column_slides_warn(report):
    _question(report, 10)["slides"] = [{"layout": "twoColumn", "title": TITLES[10][0],
                                        "leftHeading": "A", "leftItems": ["one"],
                                        "rightHeading": "B", "rightItems": []}]
    _, warns, _ = v.evaluate(report)
    assert any(w.startswith("W4") for w in warns)


def test_w5_timing_without_a_gantt_warns(report):
    timing = _question(report, 9)
    timing["slides"][0] = {"layout": "timeline", "title": TITLES[9][0],
                           "steps": timing["slides"][0]["steps"]}
    _, warns, _ = v.evaluate(report)
    assert any(w.startswith("W5") and "fallback timeline" in w for w in warns)
    timing["slides"] = timing["slides"][1:]
    _, warns, _ = v.evaluate(report)
    assert any(w.startswith("W5") and "no timing diagram" in w for w in warns)


def test_w6_mixed_risk_groups_warn(report):
    _question(report, 11)["slides"] = [{"layout": "twoColumn", "title": "Risk Detection",
                                        "leftHeading": "Project Risks", "leftItems": ["a", "b"],
                                        "rightHeading": "Document Risks", "rightItems": ["c"]}]
    _, warns, _ = v.evaluate(report)
    assert any(w.startswith("W6") for w in warns)


def test_a_non_report_payload_is_a_c9_failure():
    fails, _, _ = v.evaluate("nope")
    assert fails == ["C9 final plan structure is invalid: expected a report object"]
    fails, _, _ = v.evaluate({"analysis": {}, "slidePlan": {"questions": "x"}})
    assert fails and fails[-1].startswith("C1b")


def test_run_evaluation_reads_the_files_and_formats_lines(report, tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps(sample_corpus()), encoding="utf-8")
    fails, warns, oks = v.run_evaluation(str(report_path), str(corpus_path))
    assert fails == [] and warns == []
    assert "C2" in _labels(oks)
    lines = v.format_lines(fails, warns, oks)
    assert all(line.startswith("  PASS  ") for line in lines)
    assert len(lines) == len(oks)
    assert v.format_lines(["C1 x"], ["W1 y"], []) == ["  WARN  W1 y", "  FAIL  C1 x"]


def test_run_evaluation_tolerates_a_trailing_comma_in_the_corpus(report, tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text('{"filesContents": [{"filename": "a", "extracted_text": "Concept",},],}',
                           encoding="utf-8")
    fails, _, oks = v.run_evaluation(str(report_path), str(corpus_path))
    assert "C2" in _labels(oks)
