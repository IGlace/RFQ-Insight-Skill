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
from rfq import pipeline, state, verification
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


def _analysis_attempt(folder: Path, work: Path, attempt: int, analysis: dict):
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
        result = _analysis_attempt(folder, work, attempt, unfaithful)
        assert result["status"] == "repair" and result["attempt"] == attempt
        assert result["errors"] == [
            "Section 10 names 'ISO 9999', which does not occur in the RFQ "
            "documents; copy the designation as written or remove it."]

    done = _analysis_attempt(folder, work, 4, unfaithful)
    assert done == {"status": "stopped", "stage": "analysis"}
    stored = _read(work / "analysis.json")
    assert stored["answers"][9]["deductions"] == [
        {"rule": "S10.2", "count": 1, "items": "bench norm", "basis": ""},
        {"rule": "V3", "count": 1, "items": "ISO 9999", "basis": ""}]
    assert all(a["deductions"] == [] for a in stored["answers"] if a["id"] != 10)
    assert pipeline._resume_rules(_run(folder), "verification") == "verification", \
        "the stored V3 entry is the runner's, not a model fault"


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
    result = _analysis_attempt(folder, work, 2, analysis)
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
    done = _analysis_attempt(folder, work, 2, analysis)
    assert done == {"status": "stopped", "stage": "analysis"}
    stored = _read(work / "analysis.json")
    assert [a["id"] for a in stored["answers"]] == list(range(1, 12 + with_12))
    assert all(a["deductions"] == [] for a in stored["answers"])


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
def test_many_claims_are_verified_in_four_disjoint_partitions(tmp_path):
    folder, work = _folder(tmp_path, pending="verification", absences=3)
    claims = verification.extract_claims(_read(work / "analysis.json"))
    assert len(claims) == 20 >= verification.PARTITION_THRESHOLD
    result = pipeline.advance(str(folder), "claude")
    assert result["status"] == "dispatch" and result["stage"] == "verification"
    requests = result["requests"]
    assert [r["partition_id"] for r in requests] == [
        "part-1", "part-2", "part-3", "part-4"]
    ids = [set(r["claim_ids"]) for r in requests]
    assert sum(len(s) for s in ids) == 20
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
    assert [v["id"] for v in merged] == list(range(1, 21))
    record = _read(work / "verification.json")
    assert record["status"] == "ok" and len(record["claims"]) == 20
    assert record["corpus_revision"] == jobs["corpus_revision"]
    assert _read(work / verification.RECEIPT_FILE)["run_id"] == jobs["run_id"]


def test_partition_claims_threshold():
    claims = [{"id": i} for i in range(1, 9)]
    assert verification.partition_claims(claims) == [claims[:6], claims[6:]]
    assert verification.partition_claims(claims[:7]) == [claims[:7]]
    assert verification.partition_claims([]) == []


def test_few_claims_use_the_top_level_claims_and_verdicts_files(tmp_path):
    folder, work = _folder(tmp_path, pending="verification", absences=0)
    analysis = _read(work / "analysis.json")
    analysis["answers"][2]["answer"] += "\n- Volume: not stated.\n- Price: not found."
    _write(work / "analysis.json", analysis)
    assert len(verification.extract_claims(analysis)) == 2 < verification.PARTITION_THRESHOLD
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


def test_no_claims_skips_the_verification_worker(tmp_path):
    folder, work = _folder(tmp_path, pending="verification", absences=0)
    result = pipeline.advance(str(folder), "claude")
    assert result["status"] == "dispatch" and result["stage"] == "slides"
    assert _read(work / "claims.json") == {"claims": []}
    assert not (work / "verification.json").exists()


def test_a_changed_accepted_partition_output_is_rejected(tmp_path):
    folder, work = _folder(tmp_path, pending="verification", absences=3)
    first = pipeline.advance(str(folder), "claude")
    requests = first["requests"]
    for request in requests[:3]:
        _verdicts(request)
    Path(requests[3]["outputs"][0]).write_text("{}", encoding="utf-8")

    repair = pipeline.advance(str(folder), "claude")
    assert repair["status"] == "repair" and repair["attempt"] == 2
    assert [r["partition_id"] for r in repair["requests"]] == ["part-4"]
    assert all(e.startswith("part-4: ") for e in repair["errors"])
    assert repair["requests"][0]["outputs"][0].endswith("part-4/attempt-2/verdicts.json")
    jobs = _read(work / verification.JOBS_FILE)
    accepted = [p["accepted_sha256"] for p in jobs["partitions"]]
    assert all(accepted[:3]) and accepted[3] is None

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
    assert jobs["partitions"][3]["accepted_sha256"]

    _verdicts(again["requests"][0])
    assert pipeline.advance(str(folder), "claude")["stage"] == "slides"
    assert len(_read(work / "verdicts.json")["verdicts"]) == 20


def test_verification_blocks_after_the_third_failed_partition_attempt(tmp_path):
    folder, work = _folder(tmp_path, pending="verification", absences=3)
    result = pipeline.advance(str(folder), "claude")
    for attempt in (2, 3):
        for request in result["requests"]:
            Path(request["outputs"][0]).write_text("[]", encoding="utf-8")
        result = pipeline.advance(str(folder), "claude")
        assert result["status"] == "repair" and result["attempt"] == attempt
        assert len(result["requests"]) == 4
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
