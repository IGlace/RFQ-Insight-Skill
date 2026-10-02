"""Stage-output gates: corpus size, analysis shape, slide-plan shape."""

import json

import pytest

import validate as v
from rfq.schema import TITLES


def _answers(overrides=None):
    overrides = overrides or {}
    out = []
    for i in range(1, 12):
        a = {"id": i, "answer": f"Answer {i}", "tldr": f"T{i}",
             "not_found": False, "confidence": "high", "evidence_files": []}
        a.update(overrides.get(i, {}))
        out.append(a)
    return out


def _plan():
    return {"projectName": "Demo", "questions": [
        {"number": i, "titleEn": TITLES[i][0], "titleDe": TITLES[i][1],
         "slides": [{"layout": "bullets", "title": TITLES[i][0],
                     "bullets": [{"text": "A point."}]}]}
        for i in range(1, 12)]}


# ----------------------------------------------------------------- corpus
def test_good_corpus_passes():
    corpus = {"projectName": "Demo", "filesContents": [
        {"filename": "SOR.docx", "extracted_text": "Content."}]}
    assert v.check_corpus(corpus) == []


def test_empty_corpus_is_refused():
    problems = v.check_corpus({"projectName": "Demo", "filesContents": []})
    assert problems and "no files" in problems[0].lower()


def test_oversize_corpus_names_the_largest_files():
    files = [{"filename": f"f{n}.pdf", "extracted_text": "x" * 150_000}
             for n in range(6)]
    problems = v.check_corpus({"projectName": "Demo", "filesContents": files})
    assert len(problems) == 1
    message = problems[0]
    assert "900,000 characters" in message
    assert "600,000" in message
    assert message.count("150,000 chars") == 5      # five largest, not six


def test_corpus_entry_missing_text_is_reported():
    corpus = {"projectName": "Demo",
              "filesContents": [{"filename": "SOR.docx"}]}
    assert any("extracted_text" in p for p in v.check_corpus(corpus))


# --------------------------------------------------------------- analysis
def test_good_analysis_passes():
    assert v.check_analysis({"answers": _answers()}) == []


def test_missing_section_is_named():
    answers = [a for a in _answers() if a["id"] != 7]
    problems = v.check_analysis({"answers": answers})
    assert any("7" in p for p in problems)


def test_unknown_section_id_is_refused():
    answers = _answers() + [{"id": 12, "answer": "x", "tldr": "",
                             "not_found": False, "confidence": "high",
                             "evidence_files": []}]
    assert any("12" in p for p in v.check_analysis({"answers": answers}))


def test_sections_out_of_order_are_refused():
    answers = _answers()
    answers[0], answers[1] = answers[1], answers[0]
    assert any("ascending" in p.lower()
               for p in v.check_analysis({"answers": answers}))


def test_missing_answer_field_is_named():
    answers = _answers()
    del answers[3]["tldr"]
    problems = v.check_analysis({"answers": answers})
    assert any("tldr" in p for p in problems)


def test_unknown_confidence_value_is_refused():
    problems = v.check_analysis({"answers": _answers({5: {"confidence": "ok"}})})
    assert any("confidence" in p for p in problems)


def test_empty_answer_text_is_refused():
    problems = v.check_analysis({"answers": _answers({2: {"answer": "  "}})})
    assert any("empty" in p.lower() for p in problems)


def test_a_repeated_section_id_is_refused():
    answers = _answers()
    answers[3]["id"] = 3          # now two answers claim section 3
    problems = v.check_analysis({"answers": answers})
    assert any("more than once" in p for p in problems)


def test_a_shape_failure_does_not_hide_the_other_problems():
    """A retry gets three attempts and these messages are its only input,
    so one pass must report everything wrong - not the first thing wrong."""
    answers = _answers()
    del answers[0]["id"]                      # shape failure: id is required
    answers[4]["confidence"] = "quite sure"   # and a business-rule failure
    problems = v.check_analysis({"answers": answers})
    assert any("required shape" in p for p in problems)
    assert any("confidence" in p for p in problems)


def test_a_non_object_answer_is_reported_not_crashed():
    """A validator that raises tells a retry nothing. One bad element must
    cost its own message, not every other message in the pass."""
    answers = _answers()
    answers[2] = "oops"
    problems = v.check_analysis({"answers": answers})
    assert any("not objects" in p for p in problems)
    assert any("required shape" in p for p in problems)


def test_a_bad_element_does_not_suppress_the_other_checks():
    """The point of reporting rather than raising: the remaining entries
    are still checked in the same pass."""
    answers = _answers()
    answers[2] = "oops"
    answers[5]["confidence"] = "quite sure"
    problems = v.check_analysis({"answers": answers})
    assert any("not objects" in p for p in problems)
    assert any("confidence" in p for p in problems)


# -------------------------------------------------------------- slide plan
def test_good_plan_passes():
    assert v.check_plan(_plan()) == []


def test_plan_with_a_wrong_title_is_refused():
    plan = _plan()
    plan["questions"][6]["titleEn"] = "Scope of Work"
    problems = v.check_plan(plan)
    assert any("titleEn" in p and "7" in p for p in problems)


def test_plan_with_an_unknown_layout_is_refused():
    plan = _plan()
    plan["questions"][0]["slides"][0] = {"layout": "carousel", "title": "X"}
    assert any("carousel" in p for p in v.check_plan(plan))


def test_plan_with_a_question_with_no_slides_is_refused():
    plan = _plan()
    plan["questions"][2]["slides"] = []
    assert any("no slides" in p for p in v.check_plan(plan))


def test_plan_missing_a_question_is_refused():
    plan = _plan()
    plan["questions"] = plan["questions"][:10]
    assert any("11" in p for p in v.check_plan(plan))


def test_a_non_object_question_is_reported_not_crashed():
    plan = _plan()
    plan["questions"][4] = "oops"
    problems = v.check_plan(plan)
    assert any("not objects" in p for p in problems)


def test_a_non_object_slide_is_reported_not_crashed():
    plan = _plan()
    plan["questions"][0]["slides"] = ["oops"]
    problems = v.check_plan(plan)
    assert any("not an object" in p for p in problems)


def test_plan_that_cannot_render_is_refused_before_finalize():
    """A slide whose required fields are absent must fail here, not in the
    renderer: the retry loop can only act on a validation failure."""
    plan = _plan()
    plan["questions"][0]["slides"][0] = {"layout": "table", "title": "X"}
    problems = v.check_plan(plan)
    assert problems != []
    assert any("layout needs" in p for p in problems)


# --------------------------------------------------------------------- CLI
def test_cli_exit_codes(tmp_path, capsys):
    good = tmp_path / "analysis.json"
    good.write_text(json.dumps({"answers": _answers()}), encoding="utf-8")
    assert v.main(["--analysis", str(good)]) == 0

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"answers": _answers()[:5]}), encoding="utf-8")
    assert v.main(["--analysis", str(bad)]) == 2

    assert v.main(["--analysis", str(tmp_path / "nope.json")]) == 1


def test_a_non_object_corpus_is_reported_not_crashed():
    """--corpus accepts any path, so a hand-edited or truncated checkpoint
    must be described, never raise. A validator that crashes says nothing."""
    assert v.check_corpus(["not", "a", "dict"]) != []
    assert v.check_corpus({"filesContents": "not a list"}) != []


def test_a_non_object_corpus_entry_is_reported_and_the_rest_still_checked():
    corpus = {"projectName": "Demo", "filesContents": [
        "oops", {"filename": "SOR.docx"}]}
    problems = v.check_corpus(corpus)
    assert any("not objects" in p for p in problems)
    assert any("extracted_text" in p for p in problems)
