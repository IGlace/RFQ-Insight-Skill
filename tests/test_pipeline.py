"""rfq/pipeline.py and rfq/state.py together: blockers, attempts, resume
rules, verification partitions and redelivery - in-process, with canned
worker outputs and no model."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from conftest import REPO_ROOT, SKILL_ROOT
from rfq import delivery, pipeline, state, verification
from rfq.corpus import run_extraction
from rfq.schema import TITLES

VOCAB = json.loads((Path(SKILL_ROOT) / "references" / "data" /
                    "vocabularies.json").read_text(encoding="utf-8"))
SOW = "sow.txt"
SOW_TEXT = ("Northwind Mobility statement of work. Review 19 December 2026. "
            "Production volume is not stated.")


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


def _analysis(absences: int = 1) -> dict:
    """A valid analysis; every section carries `absences` checkable
    "not stated" lines (0 = nothing for the verifier)."""
    answers = []
    for i in range(1, 13):
        lines = [f"Section {i} states the facts."]
        lines += [f"- Item {i}.{k}: not stated." for k in range(absences)]
        answers.append({"id": i, "answer": "\n".join(lines),
                        "not_found": False, "deductions": [], "shown": None,
                        "sources": [{"filename": SOW, "locator": ""}]})
    return {"answers": answers, "opportunity": _opportunity()}


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _pending(folder: Path, stage: str) -> None:
    _write(folder / "output" / ".work" / "progress.json",
           {"version": 1, "pending": stage})


def _folder(tmp_path: Path, pending: str | None = None, absences: int = 1):
    """An extracted RFQ folder holding one text file and a valid analysis.
    Returns (folder, work)."""
    folder = tmp_path / "rfq"
    folder.mkdir()
    (folder / SOW).write_text(SOW_TEXT, encoding="utf-8")
    run_extraction(str(folder), "Cedar")
    work = folder / "output" / ".work"
    _write(work / "analysis.json", _analysis(absences))
    if pending is not None:
        _pending(folder, pending)
    return folder, work


def _run(folder: Path, **kw) -> pipeline._Run:
    return pipeline._Run(str(folder), folder / "output" / ".work", "claude", **kw)


def _verdicts(request: dict) -> None:
    out = Path(request["outputs"][0])
    out.parent.mkdir(parents=True, exist_ok=True)
    _write(out, {"verdicts": [{"id": i, "verdict": "confirmed",
                               "evidence": "not stated"}
                              for i in request["claim_ids"]]})


# ------------------------------------------------------------ (a) + (b)
def test_missing_folder_is_blocked(tmp_path):
    result = pipeline.advance(str(tmp_path / "nope"), "claude")
    assert result == {"status": "blocked", "message": pipeline.MSG_NO_FOLDER}
    assert not (tmp_path / "nope").exists(), "nothing is created for it"


def test_unreadable_input_blocks_and_names_the_file(tmp_path):
    folder = tmp_path / "rfq"
    folder.mkdir()
    (folder / "good.txt").write_text("Readable statement.", encoding="utf-8")
    (folder / "broken.docx").write_bytes(b"this is not a zip archive")
    result = pipeline.advance(str(folder), "claude")
    assert result["status"] == "blocked"
    assert result["message"] == pipeline.MSG_UNREADABLE.format(names="broken.docx")
    assert "broken.docx" in result["message"]
    skipped = _read(folder / "output" / ".work" / "corpus.json")["extraction"]["skipped"]
    assert [s["filename"] for s in skipped] == ["broken.docx"]
    # The same answer until a readable copy arrives (resume re-reads).
    assert pipeline.advance(str(folder), "claude") == result
    (folder / "broken.docx").unlink()
    assert pipeline.advance(str(folder), "claude")["status"] == "dispatch"


def test_folder_without_readable_documents_is_blocked(tmp_path):
    folder = tmp_path / "rfq"
    folder.mkdir()
    (folder / "notes.xyz").write_text("unsupported", encoding="utf-8")
    result = pipeline.advance(str(folder), "claude")
    assert result == {"status": "blocked", "message": pipeline.MSG_NOTHING_READABLE}


def test_invalid_progress_record_is_blocked_until_an_explicit_restart(tmp_path):
    folder, work = _folder(tmp_path)
    _write(work / "progress.json", {"version": 1, "pending": "bogus"})
    result = pipeline.advance(str(folder), "claude")
    assert result == {"status": "blocked", "message": pipeline.MSG_BAD_PROGRESS}
    assert _read(work / "progress.json")["pending"] == "bogus", "preserved"
    with pytest.raises(ValueError):
        state.resume(str(folder))
    repaired = pipeline.advance(str(folder), "claude", restart="analysis")
    assert repaired["status"] == "dispatch" and repaired["stage"] == "analysis"
    assert _read(work / "progress.json")["pending"] == "analysis"


# ------------------------------------------------------------- (c) attempts
def test_three_failed_attempts_repair_twice_then_block_and_reset(tmp_path):
    folder, work = _folder(tmp_path, pending="slides")
    first = pipeline.advance(str(folder), "claude")
    assert first["status"] == "dispatch" and first["stage"] == "slides"
    (request,) = first["requests"]
    plan_path = Path(request["outputs"][0])
    assert plan_path == work / "slide_plan.json"
    assert _read(work / state.ATTEMPTS_FILE) == {
        "stage": "slides", "count": 1, "image_ids": [],
        "request_ids": [request["request_id"]]}

    seen = []
    for attempt in (2, 3):
        plan_path.write_text('{"questions": "not a list"}', encoding="utf-8")
        result = pipeline.advance(str(folder), "claude")
        assert result["status"] == "repair", result
        assert result["stage"] == "slides" and result["attempt"] == attempt
        assert result["errors"] and all(isinstance(e, str) for e in result["errors"])
        (repair,) = result["requests"]
        assert "Validation faults" in repair["repair_message"]
        assert repair["request_id"] not in seen
        seen.append(repair["request_id"])
        attempts = _read(work / state.ATTEMPTS_FILE)
        assert attempts["count"] == attempt
        assert attempts["request_ids"] == [repair["request_id"]]
        assert _read(work / "progress.json")["pending"] == "slides"

    plan_path.write_text("not json at all", encoding="utf-8")
    blocked = pipeline.advance(str(folder), "claude")
    assert blocked == {"status": "blocked", "message": pipeline.MSG_SLIDES}
    assert _read(work / state.ATTEMPTS_FILE)["count"] == 0, "count reset"
    assert _read(work / state.ATTEMPTS_FILE)["stage"] == "slides"
    assert _read(work / "progress.json")["pending"] == "slides", "progress saved"

    # The timing record keeps every rejection, with the problems.
    rows = {r["request_id"]: r for r in _read(work / state.TIMING_FILE)["requests"]}
    assert rows[request["request_id"]]["validation"]["accepted"] is False
    assert all(rows[r]["validation"]["accepted"] is False for r in seen)
    assert all(rows[r]["mode"] == "repair" for r in seen)

    # A later call starts the stage afresh: three new attempts, old output
    # archived rather than read.
    fresh = pipeline.advance(str(folder), "claude")
    assert fresh["status"] == "dispatch" and fresh["stage"] == "slides"
    assert fresh["requests"][0]["request_id"] not in seen
    assert not plan_path.exists()
    assert _read(work / state.ATTEMPTS_FILE)["count"] == 1


# ------------------------------------------------------- faithfulness gate
UNSTATED_STANDARD = ("| Standard | Scope |\n|---|---|\n"
                     "| ISO 9999 | Bench safety |")


def _analysis_attempt(folder: Path, work: Path, analysis: dict):
    """Write `analysis` as the worker's output and advance up to the end of
    the analysis stage."""
    _write(work / "analysis.json", analysis)
    return pipeline.advance(str(folder), "claude", until="analysis")


def test_a_corpus_miss_is_repaired_then_becomes_a_v3_deduction(tmp_path):
    folder, work = _folder(tmp_path, pending="analysis")
    first = pipeline.advance(str(folder), "claude", until="analysis")
    assert first["status"] == "dispatch" and first["stage"] == "analysis"
    unfaithful = _analysis()
    unfaithful["answers"][9]["answer"] = UNSTATED_STANDARD
    unfaithful["answers"][9]["deductions"] = [
        {"rule": "S10.2", "count": 1, "items": "bench norm", "basis": ""}]
    for attempt in (2, 3):
        result = _analysis_attempt(folder, work, unfaithful)
        assert result["status"] == "repair" and result["attempt"] == attempt
        assert result["errors"] == [
            "Section 10 names 'ISO 9999', which does not occur in the RFQ "
            "documents; copy the designation as written or remove it."]

    done = _analysis_attempt(folder, work, unfaithful)
    assert done == {"status": "stopped", "stage": "analysis"}
    stored = _read(work / "analysis.json")
    assert stored["answers"][9]["deductions"] == [
        {"rule": "S10.2", "count": 1, "items": "bench norm", "basis": ""},
        {"rule": "V3", "count": 1, "items": "ISO 9999", "basis": ""}]
    assert all(a["deductions"] == [] for a in stored["answers"] if a["id"] != 10)
    assert pipeline._resume_rules(_run(folder), "verification") == "verification", \
        "the stored V3 entry is the runner's, not a model fault"


def test_an_owner_cell_outside_the_owner_set_still_blocks_on_the_last_attempt(tmp_path):
    folder, work = _folder(tmp_path, pending="analysis")
    pipeline.advance(str(folder), "claude", until="analysis")
    bad = _analysis()
    bad["answers"][6]["answer"] = ("| Scope of Work | Bench |\n|---|---|\n"
                                   "| Design | TBD (inferred) |")
    for attempt in (2, 3):
        result = _analysis_attempt(folder, work, bad)
        assert result["status"] == "repair" and result["attempt"] == attempt
    blocked = _analysis_attempt(folder, work, bad)
    assert blocked == {"status": "blocked", "message": pipeline.MSG_ANALYSIS}


def test_the_v3_deductions_are_applied_once(tmp_path):
    folder, work = _folder(tmp_path)
    analysis = _analysis()
    analysis["answers"][9]["answer"] = UNSTATED_STANDARD + "\n| DIN 70020 | Power |"
    corpus = _read(work / "corpus.json")
    pipeline._faithfulness_deductions(analysis, corpus)
    again = json.loads(json.dumps(analysis))
    pipeline._faithfulness_deductions(again, corpus)
    assert again == analysis
    assert analysis["answers"][9]["deductions"] == [
        {"rule": "V3", "count": 2, "items": "ISO 9999, DIN 70020", "basis": ""}]
    analysis["answers"][9]["answer"] = "Section 10 states the facts."
    pipeline._faithfulness_deductions(analysis, corpus)
    assert analysis["answers"][9]["deductions"] == [], "a fixed miss costs nothing"


def test_a_v3_code_from_the_model_is_repaired(tmp_path):
    folder, work = _folder(tmp_path, pending="analysis")
    pipeline.advance(str(folder), "claude", until="analysis")
    analysis = _analysis()
    analysis["answers"][9]["deductions"] = [
        {"rule": "V3", "count": 1, "items": "x", "basis": ""}]
    result = _analysis_attempt(folder, work, analysis)
    assert result["status"] == "repair"
    assert any("Section 10 uses rule V3, which only the runner may write." in e
               for e in result["errors"])


@pytest.mark.parametrize("with_12", [True, False])
def test_a_faithful_analysis_is_accepted_at_once(tmp_path, with_12):
    folder, work = _folder(tmp_path, pending="analysis")
    pipeline.advance(str(folder), "claude", until="analysis")
    analysis = _analysis()
    if not with_12:
        analysis["answers"].pop()
    done = _analysis_attempt(folder, work, analysis)
    assert done == {"status": "stopped", "stage": "analysis"}
    stored = _read(work / "analysis.json")
    # Source Material is the runner's: a model-written one is dropped and
    # the Python-built table takes its place either way.
    assert [a["id"] for a in stored["answers"]] == list(range(1, 13))
    assert all(a["deductions"] == [] for a in stored["answers"])
    corpus = _read(work / "corpus.json")
    assert stored["answers"][-1] == delivery.build_source_material(corpus, stored)
    assert stored["answers"][-1]["answer"].splitlines() == [
        "| File | Type | Read | Used by sections |",
        "| --- | --- | --- | --- |",
        f"| {SOW} | TXT | whole file | 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11 |"]
    assert pipeline._resume_rules(_run(folder), "verification") == "verification", \
        "the stored analysis with its built section 12 is still valid"


# ------------------------------------------------------- slides in Python
def _sample_folder(tmp_path: Path, analysis: dict) -> tuple:
    """A folder holding the sample corpus whose analysis stage accepted
    `analysis` (the model's sections 1-11). Returns (folder, work)."""
    from helpers import CORPUS_TEXT, SOURCE_FILE
    folder = tmp_path / "rfq"
    folder.mkdir()
    (folder / SOURCE_FILE).write_text(CORPUS_TEXT, encoding="utf-8")
    run_extraction(str(folder), "Northwind RFQ")
    work = folder / "output" / ".work"
    _pending(folder, "analysis")
    pipeline.advance(str(folder), "claude", until="analysis")
    assert _analysis_attempt(folder, work, analysis) == {
        "status": "stopped", "stage": "analysis"}
    return folder, work


def _advance_serving_verification(folder: Path, until=None) -> tuple:
    """advance() until it stops needing the verifier; (result, stages of
    every request issued)."""
    issued = []
    for _ in range(6):
        result = pipeline.advance(str(folder), "claude", until=until)
        if result["status"] != "dispatch":
            return result, issued
        issued += [r["stage"] for r in result["requests"]]
        if result["stage"] != "verification":
            return result, issued
        for request in result["requests"]:
            _verdicts(request)
    raise AssertionError("the run never settled")


def test_the_sample_analysis_is_planned_in_python_without_a_slides_request(tmp_path):
    from helpers import model_analysis
    analysis = model_analysis()
    analysis["answers"][2]["answer"] += "\nA stray remark."
    folder, work = _sample_folder(tmp_path, analysis)
    result, issued = _advance_serving_verification(folder)
    assert "slides" not in issued
    assert result["status"] == "done", result
    assert _read(work / "slide_planning.json") == {
        "version": 1, "mode": "deterministic", "parsed": list(range(2, 13))}
    assert _read(work / "plan_actions.json") == [
        "Section 3: dropped text outside the table: A stray remark."]
    report = _read(Path(result["report"]))
    assert "Section 3: dropped text outside the table: A stray remark." \
        in report["run"]["sanitizer"]
    layouts = [s["layout"] for q in report["slidePlan"]["questions"] for s in q["slides"]]
    assert layouts[:3] == ["opportunity", "prose", "table"]


def test_an_unparsable_section_sends_the_deck_to_the_slide_worker(tmp_path):
    from helpers import model_analysis
    analysis = model_analysis()
    analysis["answers"][3]["answer"] = "| Topic | Approach |\n| Calibration | Base |"
    folder, work = _sample_folder(tmp_path, analysis)
    result, issued = _advance_serving_verification(folder)
    assert result["status"] == "dispatch" and result["stage"] == "slides"
    assert _read(work / "slide_planning.json") == {
        "version": 1, "mode": "worker", "unparsable": [4]}
    assert _read(work / "plan_actions.json") == []


# --------------------------------------------------------- (d) resume rules
@pytest.mark.parametrize("record", [{"mode": "in-thread", "status": "ok"},
                                    {"mode": "subagent", "status": "error"}])
def test_resume_restarts_an_in_thread_or_failed_verification(tmp_path, record):
    folder, work = _folder(tmp_path, pending="slides")
    _write(work / "verification.json", record)
    assert pipeline._resume_rules(_run(folder), "slides") == "verification"
    assert _read(work / "progress.json")["pending"] == "verification"
    assert not (work / "verification.json").exists(), "archived, not reused"
    assert list((work / "history").rglob("verification.json"))


def test_resume_keeps_an_isolated_verification(tmp_path):
    folder, work = _folder(tmp_path, pending="slides")
    _write(work / "verification.json", {"mode": "subagent", "status": "ok"})
    assert pipeline._resume_rules(_run(folder), "slides") == "slides"
    assert _read(work / "progress.json")["pending"] == "slides"
    assert (work / "verification.json").exists()


def test_resume_reads_the_folder_again_when_inputs_were_skipped(tmp_path):
    folder, work = _folder(tmp_path, pending="figures")
    corpus = _read(work / "corpus.json")
    corpus["extraction"]["skipped"] = [{"filename": "scan.pdf", "path": "scan.pdf",
                                        "reason": "I couldn't open it", "detail": ""}]
    _write(work / "corpus.json", corpus)
    assert pipeline._resume_rules(_run(folder), "figures") == "extract"
    assert _read(work / "progress.json")["pending"] == "extract"


def test_resume_reads_the_folder_again_without_a_usable_corpus(tmp_path):
    folder, work = _folder(tmp_path, pending="analysis")
    (work / "corpus.json").write_text("{broken", encoding="utf-8")
    assert pipeline._resume_rules(_run(folder), "analysis") == "extract"


def test_resume_answers_again_when_the_stored_analysis_is_invalid(tmp_path):
    folder, work = _folder(tmp_path, pending="slides")
    analysis = _read(work / "analysis.json")
    del analysis["opportunity"]
    _write(work / "analysis.json", analysis)
    assert pipeline._resume_rules(_run(folder), "slides") == "analysis"
    assert not (work / "analysis.json").exists()


# ---------------------------------------------------- (e) + (f) partitions
# absences=3: three absence claims in sections 1 and 3-11, plus the one
# Description sentence in section 2 (a "stated" claim): 34 claims.
MANY_CLAIMS = 34


def test_many_claims_are_verified_in_five_disjoint_partitions(tmp_path):
    folder, work = _folder(tmp_path, pending="verification", absences=3)
    claims = verification.extract_claims(_read(work / "analysis.json"))
    assert len(claims) == MANY_CLAIMS >= verification.PARTITION_THRESHOLD
    result = pipeline.advance(str(folder), "claude")
    assert result["status"] == "dispatch" and result["stage"] == "verification"
    requests = result["requests"]
    assert [r["partition_id"] for r in requests] == [
        "part-1", "part-2", "part-3", "part-4", "part-5"]
    assert [len(r["claim_ids"]) for r in requests] == [8, 8, 8, 8, 2]
    ids = [set(r["claim_ids"]) for r in requests]
    assert sum(len(s) for s in ids) == MANY_CLAIMS
    assert set.union(*ids) == {c["id"] for c in claims}
    assert all(not (a & b) for i, a in enumerate(ids) for b in ids[i + 1:])
    jobs = _read(work / verification.JOBS_FILE)
    base = (f"verification/{jobs['corpus_revision'][:12]}-"
            f"{jobs['claims_sha256'][:12]}/{jobs['run_id']}")
    for n, request in enumerate(requests, 1):
        out = Path(request["outputs"][0])
        assert out == work / f"{base}/part-{n}/attempt-1/verdicts.json"
        claims_in = Path(request["inputs"][0])
        assert claims_in == work / f"{base}/part-{n}/attempt-1/claims.json"
        assert [c["id"] for c in _read(claims_in)["claims"]] == request["claim_ids"]
        assert Path(request["inputs"][1]) == work / "corpus.txt"
        assert request["partition_identity"]["run_id"] == jobs["run_id"]
    assert _read(work / state.ATTEMPTS_FILE)["count"] == 1

    for request in requests:
        _verdicts(request)
    after = pipeline.advance(str(folder), "claude")
    assert after["status"] == "dispatch" and after["stage"] == "slides"
    merged = _read(work / "verdicts.json")["verdicts"]
    assert [v["id"] for v in merged] == list(range(1, MANY_CLAIMS + 1))
    record = _read(work / "verification.json")
    assert record["status"] == "ok" and len(record["claims"]) == MANY_CLAIMS
    assert record["corpus_revision"] == jobs["corpus_revision"]
    assert _read(work / verification.RECEIPT_FILE)["run_id"] == jobs["run_id"]


def test_partition_claims_threshold():
    claims = [{"id": i} for i in range(1, 10)]
    assert verification.partition_claims(claims) == [claims[:8], claims[8:]]
    assert verification.partition_claims(claims[:8]) == [claims[:8]]
    assert verification.partition_claims(claims[:7]) == [claims[:7]]
    assert verification.partition_claims([]) == []


def test_few_claims_use_the_top_level_claims_and_verdicts_files(tmp_path):
    folder, work = _folder(tmp_path, pending="verification", absences=0)
    analysis = _read(work / "analysis.json")
    analysis["answers"][2]["answer"] += "\n- Volume: not stated.\n- Price: not found."
    _write(work / "analysis.json", analysis)
    # The two absences plus the Description sentence.
    assert len(verification.extract_claims(analysis)) == 3 < verification.PARTITION_THRESHOLD
    result = pipeline.advance(str(folder), "claude")
    assert result["status"] == "dispatch" and result["stage"] == "verification"
    (request,) = result["requests"]
    assert request["partition_id"] == "part-1"
    assert Path(request["outputs"][0]) == work / "verdicts.json"
    assert Path(request["inputs"][0]) == work / "claims.json"
    assert not (work / "verification").exists()
    _verdicts(request)
    assert pipeline.advance(str(folder), "claude")["stage"] == "slides"
    assert _read(work / "verification.json")["status"] == "ok"


def test_no_claims_skips_the_verification_worker(tmp_path, monkeypatch):
    folder, work = _folder(tmp_path, pending="verification", absences=0)
    # A valid Description always yields a sentence claim; an analysis
    # without any is simulated.
    monkeypatch.setattr(verification, "extract_claims",
                        lambda analysis, max_claims=48: [])
    result = pipeline.advance(str(folder), "claude")
    assert result["status"] == "dispatch" and result["stage"] == "slides"
    assert _read(work / "claims.json") == {"claims": []}
    assert not (work / "verification.json").exists()


def test_a_changed_accepted_partition_output_is_rejected(tmp_path):
    folder, work = _folder(tmp_path, pending="verification", absences=3)
    first = pipeline.advance(str(folder), "claude")
    requests = first["requests"]
    assert len(requests) == 5
    for request in requests[:4]:
        _verdicts(request)
    Path(requests[4]["outputs"][0]).write_text("{}", encoding="utf-8")

    repair = pipeline.advance(str(folder), "claude")
    assert repair["status"] == "repair" and repair["attempt"] == 2
    assert [r["partition_id"] for r in repair["requests"]] == ["part-5"]
    assert all(e.startswith("part-5: ") for e in repair["errors"])
    assert repair["requests"][0]["outputs"][0].endswith("part-5/attempt-2/verdicts.json")
    jobs = _read(work / verification.JOBS_FILE)
    accepted = [p["accepted_sha256"] for p in jobs["partitions"]]
    assert all(accepted[:4]) and accepted[4] is None

    # Someone edits an already accepted partition file: same shape, new bytes.
    part1 = work / jobs["partitions"][0]["output_path"]
    payload = _read(part1)
    payload["verdicts"][0]["evidence"] = "tampered"
    _write(part1, payload)
    assert hashlib.sha256(part1.read_bytes()).hexdigest() != accepted[0]
    _verdicts(repair["requests"][0])

    again = pipeline.advance(str(folder), "claude")
    assert again["status"] == "repair"
    assert [r["partition_id"] for r in again["requests"]] == ["part-1"]
    assert again["errors"] == [
        "part-1: The accepted partition output changed; it must be checked again."]
    assert again["requests"][0]["outputs"][0].endswith("part-1/attempt-2/verdicts.json")
    jobs = _read(work / verification.JOBS_FILE)
    assert jobs["partitions"][0]["accepted_sha256"] is None
    assert jobs["partitions"][4]["accepted_sha256"]

    _verdicts(again["requests"][0])
    assert pipeline.advance(str(folder), "claude")["stage"] == "slides"
    assert len(_read(work / "verdicts.json")["verdicts"]) == MANY_CLAIMS


def test_verification_blocks_after_the_third_failed_partition_attempt(tmp_path):
    folder, work = _folder(tmp_path, pending="verification", absences=3)
    result = pipeline.advance(str(folder), "claude")
    for attempt in (2, 3):
        for request in result["requests"]:
            Path(request["outputs"][0]).write_text("[]", encoding="utf-8")
        result = pipeline.advance(str(folder), "claude")
        assert result["status"] == "repair" and result["attempt"] == attempt
        assert len(result["requests"]) == 5
    for request in result["requests"]:
        Path(request["outputs"][0]).write_text("[]", encoding="utf-8")
    blocked = pipeline.advance(str(folder), "claude")
    assert blocked == {"status": "blocked", "message": pipeline.MSG_VERIFICATION}
    assert _read(work / state.ATTEMPTS_FILE)["count"] == 0
    assert _read(work / "progress.json")["pending"] == "verification"


# ------------------------------------------------------- (g) redelivery
def _deliverables(folder: Path, name: str = "deck") -> tuple:
    out = folder / "output"
    pptx, report = out / f"{name}.pptx", out / f"{name}.json"
    pptx.write_bytes(b"PK\x03\x04 canned deck")
    _write(report, {"slidePlan": {"questions": []}})
    _write(folder / "output" / ".work" / "deliverables.json",
           {"pptx": str(pptx), "report": str(report)})
    return pptx, report


def test_done_re_evaluates_and_delivers_without_rebuilding(tmp_path, monkeypatch):
    folder, work = _folder(tmp_path, pending="done")
    pptx, report = _deliverables(folder)
    evaluated = []
    monkeypatch.setattr(pipeline, "_evaluate_deck",
                        lambda run, path: evaluated.append(path) or True)
    monkeypatch.setattr(pipeline, "_build_deck",
                        lambda run: pytest.fail("the deck must not be rebuilt"))
    result = pipeline.advance(str(folder), "claude")
    assert result == {"status": "done", "pptx": str(pptx), "report": str(report)}
    assert evaluated == [str(report)]
    assert pipeline.advance(str(folder), "claude") == result
    assert evaluated == [str(report)] * 2, "every delivery re-runs the gate"
    assert _read(work / "progress.json")["pending"] == "done"
    assert pptx.read_bytes() == b"PK\x03\x04 canned deck"


def test_done_blocks_when_the_quality_gate_fails(tmp_path, monkeypatch):
    folder, work = _folder(tmp_path, pending="done")
    _deliverables(folder)
    monkeypatch.setattr(pipeline, "_evaluate_deck", lambda run, path: False)
    result = pipeline.advance(str(folder), "claude")
    assert result == {"status": "blocked", "message": pipeline.MSG_EVALUATE}
    assert _read(work / "progress.json")["pending"] == "done"


def test_done_rebuilds_a_missing_deliverable(tmp_path, monkeypatch):
    folder, work = _folder(tmp_path, pending="done")
    pptx, _report = _deliverables(folder)
    pptx.unlink()
    built = []

    def build(run):
        built.append(run.folder)
        return _deliverables(folder, "rebuilt")

    monkeypatch.setattr(pipeline, "_build_deck", build)
    monkeypatch.setattr(pipeline, "_evaluate_deck", lambda run, path: True)
    result = pipeline.advance(str(folder), "claude")
    assert built == [str(folder)]
    assert result["status"] == "done"
    assert Path(result["pptx"]).name == "rebuilt.pptx"
    assert _read(work / "progress.json")["pending"] == "done"


def test_a_deliverable_outside_output_is_a_blocker(tmp_path):
    folder, work = _folder(tmp_path, pending="done")
    outside = tmp_path / "elsewhere.pptx"
    outside.write_bytes(b"PK")
    _write(work / "deliverables.json",
           {"pptx": str(outside), "report": str(folder / "output" / "r.json")})
    result = pipeline.advance(str(folder), "claude")
    assert result == {"status": "blocked", "message": pipeline.MSG_BAD_DELIVERABLES}


# ------------------------------------------------- (h) the blocked sentences
EXPECTED_MESSAGES = {
    "MSG_NO_FOLDER": "The RFQ folder could not be found; correct the path.",
    "MSG_BAD_PROGRESS": "The progress record is invalid; choose an explicit "
                        "stage to restart.",
    "MSG_NOTHING_READABLE": "The RFQ folder contains no readable supported "
                            "documents.",
    "MSG_UNREADABLE": "Cannot read {names}; provide readable copies to "
                      "generate the PowerPoint.",
    "MSG_TOO_LARGE": "The RFQ package exceeds the supported size; provide a "
                     "smaller package.",
    "MSG_ANALYSIS": "The analysis could not be validated; progress is saved.",
    "MSG_VERIFICATION": "The claim verification could not be completed; "
                        "progress is saved.",
    "MSG_SLIDES": "The slide plan could not be validated; progress is saved.",
    "MSG_BUILD": "The PowerPoint could not be generated; progress is saved.",
    "MSG_EVALUATE": "The PowerPoint did not pass validation; progress is saved.",
    "MSG_BAD_DELIVERABLES": "The delivery record is invalid; progress is saved.",
}


def test_blocked_messages_are_the_exact_sentences_skill_md_promises():
    skill = (Path(SKILL_ROOT) / "SKILL.md").read_text(encoding="utf-8")
    # SKILL.md: a blocked `message` is relayed "exactly as given, as the
    # only reply" and "Progress is saved."; some ask for an explicit stage.
    assert "Reply with `message` exactly as given" in skill
    assert "Progress is saved." in skill
    assert "asks for an explicit stage" in skill
    for name, sentence in EXPECTED_MESSAGES.items():
        assert getattr(pipeline, name) == sentence
    for name, sentence in EXPECTED_MESSAGES.items():
        assert sentence.endswith(".") and "\n" not in sentence
        assert sentence == " ".join(sentence.split()), name
        assert sentence.count(".") == 1, f"{name} must be one sentence"
    for name in ("MSG_ANALYSIS", "MSG_VERIFICATION", "MSG_SLIDES", "MSG_BUILD",
                 "MSG_EVALUATE", "MSG_BAD_DELIVERABLES"):
        assert EXPECTED_MESSAGES[name].endswith("; progress is saved.")
    assert "explicit stage" in pipeline.MSG_BAD_PROGRESS
    assert pipeline.MSG_UNREADABLE.format(names="a.pdf, b.docx") == \
        "Cannot read a.pdf, b.docx; provide readable copies to generate the PowerPoint."


def test_cli_relays_the_blocked_message_verbatim(tmp_path):
    script = Path(SKILL_ROOT) / "scripts" / "rfq_run.py"
    result = subprocess.run(
        [sys.executable, str(script), "next", str(tmp_path / "missing"),
         "--host", "claude"], cwd=tmp_path, capture_output=True, text=True,
        encoding="utf-8", timeout=60)
    assert result.returncode == 0 and result.stderr == ""
    assert json.loads(result.stdout) == {
        "status": "blocked", "message": pipeline.MSG_NO_FOLDER}


# ------------------------------------- (i) next --completed / --failed
def _next(capsys, folder, *extra) -> dict:
    import rfq_run
    assert rfq_run.workflow_main(["next", str(folder), "--host", "claude",
                                  *extra]) == 0
    out = capsys.readouterr()
    assert out.err == ""
    return json.loads(out.out)


def _events(work: Path) -> dict:
    return {r["request_id"]: [e["event"] for e in r["events"]]
            for r in _read(work / state.TIMING_FILE)["requests"]}


def test_next_records_terminal_events_then_advances_in_the_same_call(
        tmp_path, capsys):
    folder, work = _folder(tmp_path, pending="verification")
    first = _next(capsys, folder)
    assert first["status"] == "dispatch" and first["stage"] == "verification"
    ids = [r["request_id"] for r in first["requests"]]
    # Every worker ended without a result: --failed for each, and the same
    # call validates the (missing) outputs and asks for the repairs.
    repair = _next(capsys, folder, *[arg for i in ids for arg in ("--failed", i)],
                   "--actual-model", "claude-opus-4")
    assert repair["status"] == "repair" and repair["stage"] == "verification"
    events = _events(work)
    assert all(events[i] == ["failed"] for i in ids)
    rows = {r["request_id"]: r for r in _read(work / state.TIMING_FILE)["requests"]}
    assert all(rows[i]["events"][0]["actual_model"] == "claude-opus-4" for i in ids)
    assert all(rows[i]["validation"]["accepted"] is False for i in ids)
    for request in repair["requests"]:
        _verdicts(request)
    again = [r["request_id"] for r in repair["requests"]]
    after = _next(capsys, folder, *[arg for i in again for arg in ("--completed", i)])
    events = _events(work)
    assert all(events[i] == ["completed"] for i in again)
    assert after.get("stage") != "verification"
    assert _read(work / "progress.json")["pending"] != "verification"


def test_next_with_an_unknown_request_id_still_advances(tmp_path, capsys):
    folder, work = _folder(tmp_path, pending="verification")
    first = _next(capsys, folder)
    assert first["status"] == "dispatch"
    again = _next(capsys, folder, "--completed", "no-such-request")
    assert again["status"] == "repair" and again["stage"] == "verification"
    assert "Unknown request ID: no-such-request" in (
        work / "timing_error.txt").read_text(encoding="utf-8")


def test_the_figure_stage_asks_for_one_text_file_per_picture(tmp_path, capsys):
    from PIL import Image, ImageDraw
    folder = tmp_path / "rfq"
    folder.mkdir()
    (folder / SOW).write_text(SOW_TEXT, encoding="utf-8")
    image = Image.new("RGB", (800, 400), "white")
    ImageDraw.Draw(image).text((30, 30), "Review: 19 December 2026", fill="black")
    image.save(folder / "review.png")
    first = _next(capsys, folder)
    assert first["status"] == "dispatch" and first["stage"] == "figures"
    (request,) = first["requests"]
    (output,) = request["outputs"]
    assert Path(output).suffix == ".txt" and ".json" not in request["message"]
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text("Review: 19 December 2026", encoding="utf-8")
    analysis = _next(capsys, folder, "--completed", request["request_id"])
    assert analysis["status"] == "dispatch" and analysis["stage"] == "analysis"
    work = folder / "output" / ".work"
    assert sorted(p.suffix for p in (work / "image_text").iterdir()) == [
        ".json", ".txt"]                       # the app's .meta.json + the text
    assert [p.name for p in (work / "image_text").glob("*.json")][0].endswith(
        ".meta.json")
    assert "19 December 2026" in (work / "corpus.txt").read_text(encoding="utf-8")
    assert "unclassified" not in _read(work / "images.json")


def test_next_up_to_the_analysis_never_imports_the_deck_renderer(tmp_path):
    folder = tmp_path / "rfq"
    folder.mkdir()
    (folder / SOW).write_text(SOW_TEXT, encoding="utf-8")
    scripts = str(Path(SKILL_ROOT) / "scripts")
    code = (
        "import json, sys\n"
        f"sys.path.insert(0, {scripts!r})\n"
        "import rfq.followups, rfq.pipeline\n"
        "assert 'pptx' not in sys.modules, 'imported with the modules'\n"
        "import rfq_run\n"
        f"assert rfq_run.main(['next', {str(folder)!r}, '--host', 'claude']) == 0\n"
        "print(json.dumps(sorted(m for m in sys.modules\n"
        "                        if m.split('.')[0] == 'pptx'\n"
        "                        or m == 'rfq.renderer')), file=sys.stderr)\n")
    result = subprocess.run([sys.executable, "-c", code], cwd=tmp_path,
                            capture_output=True, text=True, encoding="utf-8",
                            timeout=120)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["stage"] == "analysis"
    assert json.loads(result.stderr) == []
