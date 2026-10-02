"""Stage-2 input shaping, and the deterministic tail that writes the files."""

import datetime
import json
import os
from pathlib import Path

import pytest

import finalize as fz
import plan_input as pi
from rfq.schema import TITLES


def _analysis():
    return {"answers": [
        {"id": i, "answer": f"Answer for section {i}.", "tldr": f"T{i}",
         "not_found": False,
         "confidence": "low" if i == 7 else "high",
         "evidence_files": [{"filename": "SOR.docx"}]}
        for i in range(1, 12)]}


def _corpus():
    return {"projectName": "Acme V6", "oppId": "",
            "filesContents": [
                {"filename": "SOR.docx", "extension": "docx",
                 "extracted_text": "Concept and A-Sample phases apply."},
                {"filename": "BOM.xlsx", "extension": "xlsx",
                 "extracted_text": "Injector, 4"}],
            "extraction": {"parsed": 2, "chars": 60, "skipped": [],
                           "ignored": [], "images_flagged": [],
                           "images_filtered": [],
                           "preprocess": {"SOR.docx": {"chars_before": 40,
                                                       "chars_after": 40,
                                                       "removed_pct": 0.0}}}}


def _draft_plan():
    """What the stage-2 model returns: no date, no oppId, no confidence."""
    return {"projectName": "Acme V6", "questions": [
        {"number": i, "titleEn": TITLES[i][0], "titleDe": TITLES[i][1],
         "slides": [{"layout": "bullets", "title": TITLES[i][0],
                     "bullets": [{"text": f"Point for {i}."}]}]}
        for i in range(1, 12)]}


# ------------------------------------------------------------ plan input
def test_plan_input_attaches_canonical_titles_by_id():
    payload = pi.build_plan_input(_corpus(), _analysis())
    assert payload["projectName"] == "Acme V6"
    seventh = next(a for a in payload["answers"] if a["id"] == 7)
    assert seventh["title_en"] == "Scope of Work and Responsibilities"
    assert seventh["title_de"] == "Leistungsumfang und Verantwortlichkeiten"


def test_plan_input_strips_the_debug_only_fields():
    payload = pi.build_plan_input(_corpus(), _analysis())
    for answer in payload["answers"]:
        assert set(answer) == {"id", "title_en", "title_de", "answer",
                               "confidence"}


def test_plan_input_carries_the_post_verify_confidence():
    payload = pi.build_plan_input(_corpus(), _analysis())
    assert next(a for a in payload["answers"] if a["id"] == 7)["confidence"] \
        == "low"


def test_plan_input_drops_an_unknown_section_id():
    analysis = _analysis()
    analysis["answers"].append({"id": 99, "answer": "stray", "tldr": "",
                                "not_found": False, "confidence": "high",
                                "evidence_files": []})
    payload = pi.build_plan_input(_corpus(), analysis)
    assert [a["id"] for a in payload["answers"]] == list(range(1, 12))


def test_plan_input_cli_writes_the_checkpoint(tmp_path):
    work = tmp_path / "output" / ".work"
    work.mkdir(parents=True)
    for name, payload in (("corpus.json", _corpus()),
                          ("analysis.json", _analysis())):
        with open(work / name, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
    assert pi.main([str(tmp_path)]) == 0
    with open(work / "plan_input.json", encoding="utf-8") as fh:
        assert len(json.load(fh)["answers"]) == 11


# -------------------------------------------------------------- finalize
def test_safe_name_strips_path_hostile_characters():
    assert fz.safe_name("Acme V6 / Phase 2") == "Acme_V6_Phase_2"
    assert fz.safe_name("   ") == "RFQ"


def test_deliverable_paths_follow_the_naming_contract(tmp_path):
    pptx, report = fz.deliverable_paths(str(tmp_path), "Acme V6")
    assert pptx.endswith(os.path.join("output", "Acme_V6_RFQ_Analysis.pptx"))
    assert report.endswith(os.path.join("output",
                                        "Acme_V6_RFQ_Analysis.json"))


@pytest.mark.parametrize("existing", [(".pptx",), (".json",), (".pptx", ".json")])
def test_deliverable_paths_preserve_either_existing_output(tmp_path, existing):
    out = tmp_path / "output"
    out.mkdir()
    for extension in existing:
        (out / ("Acme_V6_RFQ_Analysis" + extension)).write_bytes(b"keep me")
    # A partial later run must also reserve its whole output pair.
    (out / "Acme_V6_RFQ_Analysis_2.json").write_bytes(b"keep this too")
    pptx, report = fz.deliverable_paths(str(tmp_path), "Acme V6")
    assert Path(pptx).name == "Acme_V6_RFQ_Analysis_3.pptx"
    assert Path(report).name == "Acme_V6_RFQ_Analysis_3.json"


def test_finalize_stamps_the_date_and_leaves_oppid_empty():
    plan, _, _ = fz.finalize(_corpus(), _analysis(), _draft_plan())
    assert plan["date"] == datetime.date.today().isoformat()
    assert plan["oppId"] == ""


def test_finalize_attaches_confidence_per_question():
    plan, _, _ = fz.finalize(_corpus(), _analysis(), _draft_plan())
    by_title = {q["titleEn"]: q["confidence"] for q in plan["questions"]}
    assert by_title["Scope of Work and Responsibilities"] == "low"
    assert by_title["Commercial Info"] == "high"


def test_finalize_renders_a_real_pptx():
    _, deck, _ = fz.finalize(_corpus(), _analysis(), _draft_plan())
    assert deck[:2] == b"PK"
    assert len(deck) > 20_000


def test_finalize_runs_the_sanitizer_and_records_what_it_did():
    draft = _draft_plan()
    draft["questions"][4]["slides"] = [
        {"layout": "collab", "title": "Something Else",
         "parties": [{"name": "AVL", "role": "Lead", "type": "avl"}]}]
    _, _, report = fz.finalize(_corpus(), _analysis(), draft)
    actions = report["run"]["sanitizer"]
    assert any("Collaboration Approach" in a for a in actions)


def test_finalize_scrubs_literal_tags_through_the_sanitizer():
    draft = _draft_plan()
    draft["questions"][0]["slides"][0]["bullets"] = [
        {"text": "Quotation due 20.06.2026 (inferred)"}]
    plan, _, _ = fz.finalize(_corpus(), _analysis(), draft)
    bullet = plan["questions"][0]["slides"][0]["bullets"][0]
    assert "(inferred)" not in bullet["text"]
    assert bullet["inferred"] is True


def test_report_shape_matches_the_contract():
    _, _, report = fz.finalize(_corpus(), _analysis(), _draft_plan(),
                               verification={"status": "ok",
                                             "refuted_sections": [7]})
    run = report["run"]
    assert run["projectName"] == "Acme V6"
    assert run["oppId"] == ""
    assert run["corpusFiles"] == ["SOR.docx", "BOM.xlsx"]
    assert run["prompts"] == {
        "analysis": "RFQ_QA_Extraction_Prompt_v12.md",
        "slidePlan": "RFQ_Slide_Plan_Prompt_v11.md"}
    assert run["usage"] == {"mode": "in-session", "note": "not measured"}
    assert run["preprocess"]["SOR.docx"]["chars_after"] == 40
    assert run["extraction"]["parsed"] == 2
    assert "preprocess" not in run["extraction"]      # not stored twice
    assert report["analysis"]["answers"][0]["tldr"] == "T1"
    assert report["verification"]["refuted_sections"] == [7]
    assert report["slidePlan"]["questions"][0]["titleEn"] == "Commercial Info"
    json.dumps(report)                                # must serialise


def test_report_slideplan_is_what_was_rendered():
    """render_run.py replays report["slidePlan"], so it must be the
    POST-sanitizer plan, not the draft."""
    draft = _draft_plan()
    draft["questions"][0]["slides"][0]["bullets"] = [
        {"text": "Value (assessment)"}]
    plan, _, report = fz.finalize(_corpus(), _analysis(), draft)
    assert report["slidePlan"] == plan
    assert "(assessment)" not in json.dumps(report["slidePlan"])


def test_finalize_cli_writes_both_deliverables(tmp_path):
    work = tmp_path / "output" / ".work"
    work.mkdir(parents=True)
    for name, payload in (("corpus.json", _corpus()),
                          ("analysis.json", _analysis()),
                          ("slide_plan.json", _draft_plan()),
                          ("verification.json", {"status": "ok",
                                                 "refuted_sections": []})):
        with open(work / name, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    assert fz.main([str(tmp_path)]) == 0
    out = tmp_path / "output"
    assert (out / "Acme_V6_RFQ_Analysis.pptx").exists()
    assert (out / "Acme_V6_RFQ_Analysis.json").exists()
    with open(out / "Acme_V6_RFQ_Analysis.json", encoding="utf-8") as fh:
        assert json.load(fh)["run"]["projectName"] == "Acme V6"

    # A rerun preserves a deck edited by hand and records its new actual paths.
    original = out / "Acme_V6_RFQ_Analysis.pptx"
    original.write_bytes(b"manually edited presentation")
    original_report = (out / "Acme_V6_RFQ_Analysis.json").read_bytes()
    assert fz.main([str(tmp_path)]) == 0
    assert original.read_bytes() == b"manually edited presentation"
    assert (out / "Acme_V6_RFQ_Analysis.json").read_bytes() == original_report
    saved = json.loads((work / "deliverables.json").read_text(encoding="utf-8"))
    assert Path(saved["pptx"]) == out / "Acme_V6_RFQ_Analysis_2.pptx"
    assert Path(saved["report"]) == out / "Acme_V6_RFQ_Analysis_2.json"
    assert Path(saved["pptx"]).read_bytes().startswith(b"PK")
    assert json.loads(Path(saved["report"]).read_text(encoding="utf-8"))["run"]["projectName"] == "Acme V6"


def test_finalize_cli_rejects_an_unrenderable_plan(tmp_path):
    work = tmp_path / "output" / ".work"
    work.mkdir(parents=True)
    broken = _draft_plan()
    broken["questions"][0]["slides"][0] = {"layout": "table", "title": "X"}
    for name, payload in (("corpus.json", _corpus()),
                          ("analysis.json", _analysis()),
                          ("slide_plan.json", broken)):
        with open(work / name, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
    assert fz.main([str(tmp_path)]) == 2
    assert not (tmp_path / "output" / "Acme_V6_RFQ_Analysis.pptx").exists()


def test_plan_input_cli_says_what_is_missing_instead_of_crashing(
        tmp_path, capsys):
    """Same rule as finalize's own "A checkpoint is missing" - a resume
    that lands here must not produce a traceback."""
    work = tmp_path / "output" / ".work"
    work.mkdir(parents=True)
    assert pi.main([str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "checkpoint is missing" in err
    assert "Traceback" not in err and "corpus.json" not in err
