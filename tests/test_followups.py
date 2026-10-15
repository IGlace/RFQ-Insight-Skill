"""rfq/followups.py: ask, answer and add-followups on a finished folder,
without a model."""

import json
from pathlib import Path

import pytest

from conftest import SKILL_ROOT
from rfq import followups, state
from rfq.corpus import corpus_revision, run_extraction
from rfq.opportunity import build_opportunity_slide
from rfq.schema import ADDITIONAL_INFO_ID, TITLES

VOCAB = json.loads((Path(SKILL_ROOT) / "references" / "data" /
                    "vocabularies.json").read_text(encoding="utf-8"))
SOW = "sow.txt"
SOW_TEXT = ("Northwind Mobility statement of work. The review takes place on "
            "19 December 2026. Production volume is not stated.")


# ------------------------------------------------------------- builders
def _opportunity() -> dict:
    product = VOCAB["products"][0]["name"]
    return {
        "customer": "Northwind Mobility", "customer_site": "Info not available",
        "customer_contact": "Dana Example", "quotation_due_date": "20 October 2026",
        "customer_short": "Northwind", "project_title": "Cedar",
        "opportunity_name": "Northwind – Cedar",
        "account_name": "Info not available", "kam_pte": "Info not available",
        "project_type": VOCAB["project_types"][0]["name"],
        "lead_product": product,
        "technology": VOCAB["technologies"][0]["name"],
        "industry": VOCAB["industries"][0]["name"],
        "products": [{"name": product, "percent": 100}],
        "skills": [{"name": VOCAB["skills"][0]["name"], "percent": 100}],
    }


def _analysis() -> dict:
    return {"answers": [
        {"id": i, "answer": f"Section {i} states the facts.",
         "not_found": False, "deductions": [], "shown": None,
         "sources": [{"filename": SOW, "locator": ""}]}
        for i in range(1, 13)], "opportunity": _opportunity()}


def _plan(analysis: dict) -> dict:
    """The plan finalize froze into the report: section 1 is the built
    Opportunity slide, every other section one bullets slide."""
    return {"projectName": "Cedar", "oppId": "", "date": "2026-10-01",
            "questions": [
                {"number": n, "titleEn": TITLES[n][0], "titleDe": TITLES[n][1],
                 "confidence": "high",
                 "slides": ([build_opportunity_slide(analysis["opportunity"])]
                            if n == 1 else
                            [{"layout": "bullets", "title": TITLES[n][0],
                              "bullets": [{"text": f"Point {n}."}]}])}
                for n in range(1, 13)]}


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _pending(folder: Path, stage: str) -> None:
    _write(folder / "output" / ".work" / "progress.json",
           {"version": 1, "pending": stage})


def _finished(tmp_path: Path, deliverables: bool = True):
    """A folder whose run is done: corpus, analysis, deck, report and
    delivery record. Returns (folder, work)."""
    folder = tmp_path / "rfq"
    folder.mkdir(parents=True)
    (folder / SOW).write_text(SOW_TEXT, encoding="utf-8")
    corpus, _manifest = run_extraction(str(folder), "Cedar")
    work = folder / "output" / ".work"
    analysis = _analysis()
    _write(work / "analysis.json", analysis)
    _pending(folder, "done")
    if deliverables:
        out = folder / "output"
        (out / "deck.pptx").write_bytes(b"PK\x03\x04 earlier deck")
        _write(out / "deck.json", {
            "run": {"projectName": "Cedar", "corpusRevision": corpus_revision(corpus),
                    "followupsInDeck": []},
            "analysis": analysis, "slidePlan": _plan(analysis),
            "verification": None})
        _write(work / "deliverables.json",
               {"pptx": str(out / "deck.pptx"), "report": str(out / "deck.json")})
    return folder, work


def _answer(work: Path, request: dict, text: str, **fields) -> None:
    question = _read(work / followups.QUESTION)
    payload = {"id": question["id"], "answer": text,
               "sources": [{"filename": SOW, "locator": ""}], "not_found": False,
               "mode": "extracted", "deductions": []}
    payload.update(fields)
    _write(Path(request["outputs"][0]), payload)


def _answered(folder: Path, work: Path, question: str) -> dict:
    """ask + a valid answer, returning the `answer` result."""
    asked = followups.ask(str(folder), "claude", question)
    assert asked["status"] == "dispatch", asked
    _answer(work, asked["requests"][0], f"Answer to: {question}")
    result = followups.answer(str(folder), "claude")
    assert result["status"] == "answered", result
    return result


# ------------------------------------------------------------------- ask
def test_ask_dispatches_one_followup_worker(tmp_path):
    folder, work = _finished(tmp_path)
    result = followups.ask(str(folder), "claude", "  When is   the review? ")
    assert result["status"] == "dispatch" and result["stage"] == "followup"
    (request,) = result["requests"]
    assert request["stage"] == "followup" and request["model"] == "opus"
    assert request["inherit_history"] is False
    assert Path(request["outputs"][0]) == work / followups.ANSWER
    inputs = [Path(p).name for p in request["inputs"]]
    assert inputs[:2] == ["corpus.txt", followups.QUESTION]
    assert "analysis.json" in inputs, "the standard answers are context"
    question = _read(work / followups.QUESTION)
    assert question["id"] == 1
    assert question["question"] == "When is the review?", "whitespace folded"
    assert question["corpus_revision"] == corpus_revision(_read(work / "corpus.json"))
    pending = _read(work / followups.STATE)
    assert pending["id"] == 1 and pending["attempt"] == 1
    assert pending["request_id"] == request["request_id"]
    timing = _read(work / state.TIMING_FILE)["requests"]
    assert [r["stage"] for r in timing] == ["followup"]


def test_ask_needs_a_question_and_an_analysed_folder(tmp_path):
    folder, _work = _finished(tmp_path)
    assert followups.ask(str(folder), "claude", "   ") == {
        "status": "blocked", "message": "A follow-up question is required."}
    bare = tmp_path / "bare"
    bare.mkdir()
    result = followups.ask(str(bare), "claude", "Anything?")
    assert result["status"] == "blocked"
    assert "has not been analysed yet" in result["message"]


def test_ask_is_stale_when_the_documents_changed(tmp_path):
    folder, work = _finished(tmp_path)
    (folder / SOW).write_text(SOW_TEXT + " Amended.", encoding="utf-8")
    (folder / "extra.txt").write_text("A new document.", encoding="utf-8")
    result = followups.ask(str(folder), "claude", "What changed?")
    assert result["status"] == "stale"
    assert result["changes"] == {"added": ["extra.txt"], "removed": [],
                                 "changed": [SOW]}
    assert result["message"].startswith("The RFQ files changed since the last run.")
    assert result["message"].endswith(followups.REFRESH_HINT)
    assert "--until figures" in followups.REFRESH_HINT
    assert state.resume(str(folder)) == "extract", "the refresh starts here"
    assert not (work / followups.STATE).exists()
    assert not (work / followups.QUESTION).exists()


@pytest.mark.parametrize("pending", ["extract", "figures"])
def test_ask_is_stale_while_the_documents_are_not_fully_read(tmp_path, pending):
    folder, _work = _finished(tmp_path)
    _pending(folder, pending)
    result = followups.ask(str(folder), "claude", "Anything?")
    assert result["status"] == "stale"
    assert result["changes"] == {"added": [], "removed": [], "changed": []}
    assert result["message"].startswith("The RFQ documents are not fully read yet.")
    assert state.resume(str(folder)) == pending


def test_ask_works_from_the_analysis_stage_on(tmp_path):
    folder, _work = _finished(tmp_path)
    _pending(folder, "analysis")
    assert followups.ask(str(folder), "claude", "Anything?")["status"] == "dispatch"


def test_question_ids_grow_and_never_reuse_a_pending_one(tmp_path):
    folder, work = _finished(tmp_path)
    assert _answered(folder, work, "First?")["id"] == 1
    second = followups.ask(str(folder), "claude", "Second?")
    assert _read(work / followups.QUESTION)["id"] == 2
    # Asked again before the worker answered: the pending id is burnt.
    third = followups.ask(str(folder), "claude", "Third?")
    assert _read(work / followups.QUESTION)["id"] == 3
    assert _read(work / followups.STATE)["id"] == 3
    assert third["requests"][0]["request_id"] != second["requests"][0]["request_id"]
    # A late answer to question 2 is never stored under question 3.
    _answer(work, third["requests"][0], "Late answer.", id=2)
    result = followups.answer(str(folder), "claude")
    assert result["status"] == "repair"
    assert any("'id' must be 3" in e for e in result["errors"])
    assert [e["id"] for e in followups.load(work)["followups"]] == [1]


# ---------------------------------------------------------------- answer
def test_check_followup_answer_rules():
    corpus = {"filesContents": [{"filename": SOW, "extracted_text": SOW_TEXT}]}
    good = {"id": 4, "answer": "On 19 December 2026.",
            "sources": [{"filename": SOW, "locator": ""}], "not_found": False,
            "mode": "extracted", "deductions": []}
    assert followups.check_followup_answer(good, corpus, 4) == []
    assert followups.ANSWER_FIELDS == {"id", "answer", "sources", "not_found",
                                       "mode", "deductions"}
    assert followups.NOT_FOUND == "Not found in the RFQ documents."

    def problems(**changes):
        return followups.check_followup_answer({**good, **changes}, corpus, 4)

    assert followups.check_followup_answer("text", corpus, 4) == [
        "The follow-up answer must be a JSON object."]
    assert any("Unknown field(s): extra" in p for p in problems(extra=1))
    assert any("'id' must be 4" in p for p in problems(id=5))
    assert any("'id' must be 4" in p for p in problems(id="4"))
    assert any("'answer' must be a non-empty string" in p for p in problems(answer=" "))
    assert any("'not_found' must be true or false" in p for p in problems(not_found="no"))
    assert any(f'must start with "{followups.NOT_FOUND}"' in p
               for p in problems(not_found=True))
    assert problems(not_found=True, answer=followups.NOT_FOUND + " Related: none.") == []
    assert problems(not_found=True, answer=followups.NOT_FOUND, sources=[]) == []
    assert any("'sources' must be a list" in p for p in problems(sources="x"))
    assert any("must cite at least one source" in p for p in problems(sources=[]))
    assert any("is not a corpus file" in p
               for p in problems(sources=[{"filename": "other.pdf", "locator": ""}]))
    assert any("has no page 99" in p
               for p in problems(sources=[{"filename": SOW, "locator": "p. 99"}]))
    assert any("is not one of" in p
               for p in problems(sources=[{"filename": SOW, "locator": "garbage"}]))


def test_check_followup_answer_mode_and_deductions():
    corpus = {"filesContents": [{"filename": SOW, "extracted_text": SOW_TEXT}]}
    good = {"id": 4, "answer": "On 19 December 2026.",
            "sources": [{"filename": SOW, "locator": ""}], "not_found": False,
            "mode": "extracted",
            "deductions": [{"rule": "G3", "count": 1, "items": "the date",
                            "basis": ""}]}

    def problems(**changes):
        return followups.check_followup_answer({**good, **changes}, corpus, 4)

    assert problems() == []
    assert problems(mode="analysed", deductions=[
        {"rule": "S2.1", "count": 2, "items": "two sentences", "basis": ""}]) == []
    assert problems(mode="guessed") == [
        "'mode' must be \"extracted\" or \"analysed\"."]
    assert any("G3" in p and "extracted" in p for p in problems(mode="analysed"))
    assert any("S7.1" in p for p in problems(deductions=[
        {"rule": "S7.1", "count": 1, "items": "x", "basis": ""}]))
    assert any("only the runner may write" in p for p in problems(deductions=[
        {"rule": "V1", "count": 1, "items": "x", "basis": ""}]))
    assert problems(deductions="x") == [
        "'deductions' must be a list of objects (rule, count, items, basis)."]
    assert any("at most 25 words" in p for p in problems(deductions=[
        {"rule": "G3", "count": 1, "items": "word " * 26, "basis": ""}]))


def test_a_new_answer_must_declare_its_mode():
    corpus = {"filesContents": [{"filename": SOW, "extracted_text": SOW_TEXT}]}
    answer = {"id": 4, "answer": "On 19 December 2026.",
              "sources": [{"filename": SOW, "locator": ""}], "not_found": False,
              "deductions": []}
    assert followups.check_followup_answer(answer, corpus, 4) == [
        "'mode' must be \"extracted\" or \"analysed\"."]


def test_each_deduction_is_validated_strictly_before_it_is_priced():
    corpus = {"filesContents": [{"filename": SOW, "extracted_text": SOW_TEXT}]}
    good = {"id": 4, "answer": "On 19 December 2026.",
            "sources": [{"filename": SOW, "locator": ""}], "not_found": False,
            "mode": "extracted"}

    def problems(*deductions):
        return followups.check_followup_answer(
            {**good, "deductions": list(deductions)}, corpus, 4)

    shape = problems({"rule": "G3", "count": "2", "items": "x", "basis": ""})
    assert len(shape) == 1 and "count" in shape[0]
    assert "Use one of" not in shape[0]
    stray = problems({"rule": "G3", "count": 1, "items": "x", "points": 3})
    assert len(stray) == 1 and "points" in stray[0]
    assert "Use one of" not in stray[0]
    (count,) = problems({"rule": "G3", "count": 0, "items": "x", "basis": ""})
    assert "count" in count and "Use one of" not in count
    (code,) = problems({"rule": "S7.1", "count": 1, "items": "x", "basis": ""})
    assert "S7.1" in code and code.endswith("Use one of: G1, G2, G3, G4, G5.")


def test_an_extracted_answer_must_copy_dates_standards_and_quantities():
    corpus = {"filesContents": [{"filename": SOW, "extracted_text": SOW_TEXT}]}
    good = {"id": 4, "sources": [{"filename": SOW, "locator": ""}],
            "not_found": False, "mode": "extracted", "deductions": []}

    def problems(text, **changes):
        return followups.check_followup_answer(
            {**good, "answer": text, **changes}, corpus, 4)

    assert problems("The review is on 19 December 2026.") == []
    (date,) = problems("The review is on 20 December 2026.")
    assert date.startswith("Follow-up ") and "'20 December 2026'" in date
    (standard,) = problems("Testing follows ISO 26262.")
    assert "'ISO 26262'" in standard
    (quantity,) = problems("The supply is 48 V.")
    assert "'48 V'" in quantity
    # An analysed answer reasons over the documents: no corpus gate.
    assert problems("ISO 26262 makes 48 V likely by 20 December 2026.",
                    mode="analysed") == []
    # A line the answer itself tags (inferred) is exempt.
    assert problems("- 48 V supply (inferred)") == []


def test_the_third_attempt_turns_corpus_misses_into_v3(tmp_path):
    folder, work = _finished(tmp_path)
    asked = followups.ask(str(folder), "claude", "Which standard?")
    for attempt in (2, 3):
        _answer(work, asked["requests"][0], "Testing follows ISO 26262.")
        result = followups.answer(str(folder), "claude")
        assert result["status"] == "repair" and result["attempt"] == attempt
        assert any("'ISO 26262'" in e for e in result["errors"])
    _answer(work, asked["requests"][0], "Testing follows ISO 26262.")
    result = followups.answer(str(folder), "claude")
    assert result["status"] == "answered", result
    (entry,) = followups.load(work)["followups"]
    assert entry["deductions"] == [{"rule": "V3", "count": 1,
                                    "items": "ISO 26262", "basis": ""}]
    resolved, score, band = followups.followup_confidence(entry)
    assert (score, band) == (7, "high")
    assert resolved[0]["line"].startswith("-3  V3  not found in the corpus")


def test_the_third_attempt_still_blocks_on_other_problems(tmp_path):
    folder, work = _finished(tmp_path)
    asked = followups.ask(str(folder), "claude", "Which standard?")
    for _ in (2, 3):
        _answer(work, asked["requests"][0], "Testing follows ISO 26262.",
                sources=[])
        assert followups.answer(str(folder), "claude")["status"] == "repair"
    _answer(work, asked["requests"][0], "Testing follows ISO 26262.", sources=[])
    assert followups.answer(str(folder), "claude") == {
        "status": "blocked", "message": followups.MSG_INVALID}
    assert followups.load(work)["followups"] == []


def test_answer_stores_the_history_with_in_deck_false(tmp_path):
    folder, work = _finished(tmp_path)
    asked = followups.ask(str(folder), "claude", "When is the review?")
    _answer(work, asked["requests"][0], "On 19 December 2026.",
            sources=[{"filename": SOW, "locator": ""}, {"filename": SOW}])
    result = followups.answer(str(folder), "claude", "claude-opus-4", None)
    assert result == {"status": "answered", "id": 1,
                      "answer": "On 19 December 2026.",
                      "sources": [{"filename": SOW, "locator": ""}] * 2,
                      "not_found": False}
    (entry,) = followups.load(work)["followups"]
    assert entry["id"] == 1 and entry["in_deck"] is False
    assert entry["question"] == "When is the review?"
    assert entry["corpus_revision"] == corpus_revision(_read(work / "corpus.json"))
    assert set(entry) == {"id", "asked_at", "question", "answer", "sources",
                          "not_found", "in_deck", "corpus_revision", "mode",
                          "deductions"}
    assert (entry["mode"], entry["deductions"]) == ("extracted", [])
    assert not (work / followups.STATE).exists()
    execution = _read(work / "execution.json")["stages"]
    assert execution[-1]["stage"] == "followup"
    assert execution[-1]["actual_model"] == "claude-opus-4"
    assert followups.answer(str(folder), "claude") == {
        "status": "blocked",
        "message": "No follow-up question is pending; ask one first."}


def test_answer_repairs_twice_then_blocks(tmp_path):
    folder, work = _finished(tmp_path)
    asked = followups.ask(str(folder), "claude", "Volume?")
    request_ids = [asked["requests"][0]["request_id"]]
    for attempt in (2, 3):
        _answer(work, asked["requests"][0], "Not stated anywhere.", sources=[])
        result = followups.answer(str(folder), "claude")
        assert result["status"] == "repair" and result["attempt"] == attempt
        assert result["stage"] == "followup"
        assert any("at least one source" in e for e in result["errors"])
        (repair,) = result["requests"]
        assert "Validation faults" in repair["repair_message"]
        assert repair["request_id"] not in request_ids
        request_ids.append(repair["request_id"])
        assert _read(work / followups.STATE)["attempt"] == attempt
    (work / followups.ANSWER).write_text("{broken", encoding="utf-8")
    blocked = followups.answer(str(folder), "claude")
    assert blocked == {"status": "blocked", "message": followups.MSG_INVALID}
    assert followups.MAX_ATTEMPTS == 3
    assert not (work / followups.STATE).exists()
    assert followups.load(work)["followups"] == []
    timing = {r["request_id"]: r for r in _read(work / state.TIMING_FILE)["requests"]}
    assert all(timing[r]["validation"]["accepted"] is False for r in request_ids)
    assert followups.answer(str(folder), "claude")["status"] == "blocked"
    # The next question starts cleanly, with a fresh id.
    assert followups.ask(str(folder), "claude", "Again?")["status"] == "dispatch"
    assert _read(work / followups.QUESTION)["id"] == 2


def test_answer_is_stale_when_the_documents_changed_meanwhile(tmp_path):
    folder, work = _finished(tmp_path)
    asked = followups.ask(str(folder), "claude", "Volume?")
    _answer(work, asked["requests"][0], "Not stated.")
    (folder / SOW).write_text("Rewritten.", encoding="utf-8")
    result = followups.answer(str(folder), "claude")
    assert result["status"] == "stale" and result["changes"]["changed"] == [SOW]
    assert "dispatch the same question again" in result["message"]
    assert state.resume(str(folder)) == "extract"
    assert not (work / followups.STATE).exists()


def test_not_found_answers_keep_their_prefix(tmp_path):
    folder, work = _finished(tmp_path)
    asked = followups.ask(str(folder), "claude", "Price?")
    _answer(work, asked["requests"][0],
            followups.NOT_FOUND + " Only the due date is given.",
            not_found=True, sources=[])
    result = followups.answer(str(folder), "claude")
    assert result["status"] == "answered" and result["not_found"] is True
    assert result["answer"].startswith(followups.NOT_FOUND)


# ---------------------------------------------------------- add-followups
def test_add_followups_needs_a_finished_current_deck(tmp_path):
    folder, work = _finished(tmp_path, deliverables=False)
    result = followups.add_followups(str(folder))
    assert result["status"] == "blocked"
    assert result["message"].startswith("No finished presentation was found")

    folder, work = _finished(tmp_path / "b")
    _answered(folder, work, "Volume?")
    _pending(folder, "slides")
    assert followups.add_followups(str(folder)) == {
        "status": "blocked", "message": followups.MSG_OUTDATED}
    _pending(folder, "done")

    report_path = Path(_read(work / "deliverables.json")["report"])
    report = _read(report_path)
    report["run"]["corpusRevision"] = "0" * 64
    _write(report_path, report)
    assert followups.add_followups(str(folder)) == {
        "status": "blocked", "message": followups.MSG_OUTDATED}

    folder, work = _finished(tmp_path / "c")
    assert followups.add_followups(str(folder)) == {
        "status": "blocked", "message": followups.MSG_NO_CURRENT}


def test_add_followups_inserts_additional_information_before_source_material(tmp_path):
    folder, work = _finished(tmp_path)
    _answered(folder, work, "When does the review take place in the plan?")
    old_pptx = folder / "output" / "deck.pptx"
    result = followups.add_followups(str(folder))
    assert result["status"] == "done", result
    pptx, report_path = Path(result["pptx"]), Path(result["report"])
    assert pptx.is_file() and pptx.read_bytes().startswith(b"PK")
    assert pptx != old_pptx and old_pptx.read_bytes() == b"PK\x03\x04 earlier deck"
    assert pptx.parent == folder / "output" and pptx.name.startswith("RFQ Insight_")
    assert _read(work / "deliverables.json") == {"pptx": str(pptx),
                                                 "report": str(report_path)}
    report = _read(report_path)
    numbers = [q["number"] for q in report["slidePlan"]["questions"]]
    assert numbers == [*range(1, 12), ADDITIONAL_INFO_ID, 12]
    assert ADDITIONAL_INFO_ID == 13
    extra = report["slidePlan"]["questions"][11]
    assert extra["titleEn"] == "Additional Information"
    assert extra["titleDe"] == "Zusätzliche Informationen"
    (slide,) = extra["slides"]
    assert slide["layout"] == "panel" and slide["title"] == "Additional Information"
    assert slide["heading"] == "When does the review take place in the plan?"
    assert slide["items"] == ["Answer to: When does the review take place in the plan?"]
    assert slide["sourceLine"].startswith("Source:") and SOW in slide["sourceLine"]
    assert report["run"]["followupsInDeck"] == [1]
    assert report["run"]["followupsExcluded"] == []
    assert followups.load(work)["followups"][0]["in_deck"] is True
    # The original sections are the latest deck's, untouched.
    assert report["slidePlan"]["questions"][0]["slides"][0]["rows"] == \
        build_opportunity_slide(_opportunity())["rows"]
    assert followups.add_followups(str(folder)) == {
        "status": "blocked", "message": followups.MSG_NO_CURRENT}


def _added(folder: Path) -> dict:
    """add_followups' Additional Information question of the new report."""
    result = followups.add_followups(str(folder))
    assert result["status"] == "done", result
    report = _read(Path(result["report"]))
    return next(q for q in report["slidePlan"]["questions"]
                if q["number"] == ADDITIONAL_INFO_ID)


def test_additional_information_is_scored_from_its_followup(tmp_path):
    folder, work = _finished(tmp_path)
    asked = followups.ask(str(folder), "claude", "When is the review?")
    _answer(work, asked["requests"][0], "On 19 December 2026 (inferred).",
            mode="extracted", deductions=[
                {"rule": "G3", "count": 2, "items": "review date, venue",
                 "basis": "sow.txt"}])
    assert followups.answer(str(folder), "claude")["status"] == "answered"
    (entry,) = followups.load(work)["followups"]
    assert entry["mode"] == "extracted" and entry["deductions"][0]["rule"] == "G3"

    extra = _added(folder)
    assert (extra["confidence"], extra["score"]) == ("high", 8)
    assert [(d["rule"], d["points"], d["followup"]) for d in extra["deductions"]] \
        == [("G3", 2, 1)]
    assert extra["confidenceNotes"].startswith(
        "Confidence 8/10 (High)\n"
        "-2  G3  2 inferred items: review date, venue (sow.txt)\n"
        f"{followups.NO_CHECK}\n\nSources:\n")


def test_a_legacy_followup_entry_scores_ten(tmp_path):
    folder, work = _finished(tmp_path)
    _answered(folder, work, "Volume?")
    history = followups.load(work)
    for entry in history["followups"]:
        entry.pop("mode"), entry.pop("deductions")
    followups.write_json(work / followups.FILE, history)
    extra = _added(folder)
    assert (extra["confidence"], extra["score"], extra["deductions"]) == (
        "high", 10, [])
    assert extra["confidenceNotes"].startswith(
        "Confidence 10/10 (High)\nNo deductions: every item is stated in "
        "the documents.\n")


def test_several_followups_take_the_lowest_score(tmp_path):
    folder, work = _finished(tmp_path)
    _answered(folder, work, "Volume?")
    asked = followups.ask(str(folder), "claude", "Is the plan feasible?")
    _answer(work, asked["requests"][0], "It is tight.", mode="analysed",
            deductions=[{"rule": "S2.1", "count": 2, "items": "both sentences",
                         "basis": ""}])
    assert followups.answer(str(folder), "claude")["status"] == "answered"
    extra = _added(folder)
    assert (extra["confidence"], extra["score"]) == ("medium", 6)
    assert extra["confidenceNotes"].startswith(
        "Confidence 6/10 (Medium)\n"
        'Follow-up 1 "Volume?": 10/10\n'
        "No deductions: every item is stated in the documents.\n"
        'Follow-up 2 "Is the plan feasible?": 6/10\n'
        "-4  S2.1  2 sentences rest on no stated fact: both sentences\n"
        f"{followups.NO_CHECK}\n\nSources:\n")


def test_add_followups_refuses_a_report_from_before_the_scoring(tmp_path):
    folder, work = _finished(tmp_path)
    _answered(folder, work, "Volume?")
    report_path = Path(_read(work / "deliverables.json")["report"])
    report = _read(report_path)
    for answer in report["analysis"]["answers"]:
        del answer["deductions"]
    _write(report_path, report)
    assert followups.add_followups(str(folder)) == {
        "status": "blocked", "message": followups.MSG_PRE_SCORING}
    assert followups.MSG_PRE_SCORING == (
        "The RFQ analysis predates the current scoring; run the analysis "
        "again before adding follow-ups.")


def test_add_followups_ids_select_answers_and_reject_stale_ones(tmp_path):
    folder, work = _finished(tmp_path)
    _answered(folder, work, "First question?")
    _answered(folder, work, "Second question?")
    history = followups.load(work)
    stale = dict(history["followups"][0], id=3, question="Old question?",
                 corpus_revision="f" * 64)
    history["followups"].append(stale)
    followups.write_json(work / followups.FILE, history)

    result = followups.add_followups(str(folder), [2])
    assert result["status"] == "done", result
    report = _read(Path(result["report"]))
    extra = next(q for q in report["slidePlan"]["questions"]
                 if q["number"] == ADDITIONAL_INFO_ID)
    assert [s["heading"] for s in extra["slides"]] == ["Second question?"]
    assert report["run"]["followupsInDeck"] == [2]
    assert report["run"]["followupsExcluded"] == [
        {"id": 3, "reason": "different or unknown corpus revision"}]
    flags = {e["id"]: e["in_deck"] for e in followups.load(work)["followups"]}
    assert flags == {1: False, 2: True, 3: False}

    assert followups.add_followups(str(folder), [3]) == {
        "status": "blocked",
        "message": "Follow-up answers refer to older RFQ documents: 3"}
    assert followups.add_followups(str(folder), [99]) == {
        "status": "blocked", "message": "Unknown follow-up id(s): 99"}
    assert followups.add_followups(str(folder), [2]) == {
        "status": "blocked", "message": followups.MSG_NO_CURRENT}

    # Default: every current answer not yet in the latest deck joins it.
    result = followups.add_followups(str(folder))
    assert result["status"] == "done"
    report = _read(Path(result["report"]))
    extra = next(q for q in report["slidePlan"]["questions"]
                 if q["number"] == ADDITIONAL_INFO_ID)
    assert [s["heading"] for s in extra["slides"]] == ["First question?",
                                                      "Second question?"]
    assert report["run"]["followupsInDeck"] == [1, 2]
    assert len(list((folder / "output").glob("*.pptx"))) == 3
