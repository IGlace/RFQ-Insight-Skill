"""Run the installed plugin's runner end to end with canned worker outputs.

The plugin folder is copied to an unrelated location first, the way a host
installs it, and `rfq_run.py next` is driven by subprocess from a different
working directory. The test plays the coordinator: it dispatches every
request the runner returns by writing the worker's output files itself and
records the worker lifecycle with `event`. This checks relocation, the
filesystem contracts, checkpoints, resume and restart; it does not certify
live model judgement.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw
import pytest

from conftest import REPO_ROOT
from rfq.schema import TITLES

ROOT = Path(REPO_ROOT)
PLUGIN = ROOT / "plugins" / "rfq-insight"
VOCAB = json.loads((PLUGIN / "skills" / "rfq-insight" / "references" / "data"
                    / "vocabularies.json").read_text(encoding="utf-8"))

SOW = "01_statement_of_work.txt"
APPENDIX = "02_appendix_b.txt"
TRANSCRIPTION = "Review: 19 December 2026"


# ------------------------------------------------------- canned worker output
def _opportunity() -> dict:
    """Section 1 with official Guidance vocabulary values."""
    product = VOCAB["products"][3]["name"]
    return {
        "customer": "Northwind Mobility", "customer_site": "Info not available",
        "customer_contact": "Dana Example",
        "quotation_due_date": "20 October 2026",
        "customer_short": "Northwind", "project_title": "Cedar Controller",
        "opportunity_name": "Northwind – Cedar Controller",
        "account_name": "Info not available", "kam_pte": "Info not available",
        "project_type": VOCAB["project_types"][3]["name"],
        "lead_product": product,
        "technology": VOCAB["technologies"][3]["name"],
        "industry": VOCAB["industries"][0]["name"],
        "products": [{"name": product, "percent": 100}],
        "skills": [{"name": VOCAB["skills"][3]["name"], "percent": 100}],
    }


_ANSWERS = {
    1: ("Customer: Northwind Mobility\nCustomer contact: Dana Example\n"
        "Quotation due date: 20 October 2026"),
    2: ("Northwind Mobility requests a proposal from AVL for the Cedar "
        "controller programme. The customer will provide prototype hardware."),
    3: ("| Item | Value |\n|---|---|\n| Sensor modules | four |\n"
        "| Supply voltage | 9 to 16 V |\n- Production volume: not stated."),
    4: "Bench verification follows ETS-42:2024 on customer prototype hardware.",
    5: "Northwind Mobility is the customer; AVL delivers the engineering work.",
    6: ("| Phase | Start | End |\n|---|---|---|\n"
        "| Bench Readiness | 2 November 2026 | 27 November 2026 |\n"
        "| Vehicle Check | 30 November 2026 | 18 December 2026 |"),
    7: ("- Requirements review: AVL\n- Vehicle integration: Northwind\n"
        "- Interface approval: joint\n- Prototype shipping: not stated."),
    8: "- Requirements review\n- Bench test report",
    9: ("- Bench Readiness: 2 November 2026 to 27 November 2026\n"
        "- Vehicle Check: 30 November 2026 to 18 December 2026\n"
        "- Review: 19 December 2026"),
    10: "- ETS-42:2024 for bench verification",
    11: ("- Discrepancies between the statement and Appendix B must be "
         "clarified before quotation.\n- Production volume is not stated."),
    12: f"- {SOW}\n- {APPENDIX}",
}


def _analysis() -> dict:
    """A 12-section analysis whose sources name real corpus files."""
    return {"answers": [
        {"id": i, "answer": _ANSWERS[i], "not_found": False, "deductions": [],
         "sources": ([{"filename": SOW, "locator": ""}]
                     + ([{"filename": APPENDIX, "locator": ""}]
                        if i in (11, 12) else []))}
        for i in range(1, 13)], "opportunity": _opportunity()}


def _table(number, columns, rows) -> dict:
    return {"layout": "table", "title": TITLES[number][0],
            "columns": columns, "rows": rows}


def _slide_plan(project: str) -> dict:
    """A draft plan with exactly the shapes schema.SECTION_SHAPES allows."""
    slides = {
        1: [{"layout": "opportunity", "title": TITLES[1][0]}],
        2: [{"layout": "prose", "title": TITLES[2][0],
             "body": "Northwind Mobility requests a proposal from AVL for "
                     "the Cedar controller programme."}],
        3: [_table(3, ["Item", "Value"], [["Sensor modules", "four"],
                                          ["Supply voltage", "9 to 16 V"]])],
        4: [_table(4, ["Approach", "Detail"],
                   [["Bench verification", "ETS-42:2024 on customer hardware"]])],
        5: [{"layout": "collab", "title": TITLES[5][0], "parties": [
            {"name": "Northwind Mobility", "role": "Customer", "type": "customer"},
            {"name": "AVL", "role": "Engineering partner", "type": "avl"}]}],
        6: [{"layout": "phases", "title": TITLES[6][0], "phases": [
            {"name": "Bench Readiness", "desc": "2 Nov - 27 Nov 2026"},
            {"name": "Vehicle Check", "desc": "30 Nov - 18 Dec 2026"}]}],
        7: [{"layout": "ownership", "title": TITLES[7][0],
             "customerAbbr": "Northwind",
             "columns": ["Scope of Work", "Bench Readiness", "Vehicle Check"],
             "rows": [["Requirements review", "AVL", "AVL"],
                      ["Vehicle integration", "Customer", "Customer"],
                      ["Interface approval", "Joint", "Joint"]]}],
        8: [_table(8, ["Deliverable", "Phase"],
                   [["Requirements review", "Bench Readiness"],
                    ["Bench test report", "Vehicle Check"]])],
        9: [{"layout": "gantt", "title": TITLES[9][0], "steps": [
                {"label": "Bench Readiness start", "date": "2026-11-02", "desc": ""},
                {"label": "Vehicle Check start", "date": "2026-11-30", "desc": ""},
                {"label": "Review", "date": "2026-12-19", "desc": ""}],
             "bars": [{"name": "Bench Readiness", "start": "2026-11-02",
                       "end": "2026-11-27"},
                      {"name": "Vehicle Check", "start": "2026-11-30",
                       "end": "2026-12-18"}]},
            dict(_table(9, ["Milestone", "Target timing", "Phase / Task"],
                        [["Bench Readiness start", "2026-11-02", "Bench Readiness"],
                         ["Vehicle Check start", "2026-11-30", "Vehicle Check"],
                         ["Review", "2026-12-19", "Review"]]),
                 title=TITLES[9][0] + " — Milestone Table")],
        10: [_table(10, ["Standard", "Scope"],
                    [["ETS-42:2024", "Bench verification"]])],
        11: [{"layout": "panel", "title": TITLES[11][0], "heading": "Project Risks",
              "items": ["Discrepancies between the statement and Appendix B "
                        "must be clarified."]},
             {"layout": "panel", "title": TITLES[11][0], "heading": "Document Risks",
              "items": ["Production volume is not stated."]}],
        12: [_table(12, ["Document", "Content"],
                    [[SOW, "Statement of work"], [APPENDIX, "Customer requirements"]])],
    }
    return {"projectName": project, "questions": [
        {"number": n, "titleEn": TITLES[n][0], "titleDe": TITLES[n][1],
         "slides": slides[n]} for n in range(1, 13)]}


def _serve(request: dict) -> None:
    """Write the canned output(s) of one worker request."""
    stage = request["stage"]
    if stage == "figures":
        for out in request["outputs"]:
            path = Path(out)
            path.parent.mkdir(parents=True, exist_ok=True)
            if out.endswith(".txt"):
                path.write_text(TRANSCRIPTION, encoding="utf-8")
            else:
                path.write_text(json.dumps({
                    "category": "text", "product_relevance": "low",
                    "caption": "Review date note"}), encoding="utf-8")
        return
    out = Path(request["outputs"][0])
    out.parent.mkdir(parents=True, exist_ok=True)
    if stage == "analysis":
        payload = _analysis()
    elif stage == "verification":
        payload = {"verdicts": [
            {"id": i, "verdict": "confirmed",
             "evidence": "Production volume is not stated."}
            for i in request["claim_ids"]]}
    elif stage == "slides":
        payload = _slide_plan("Cedar Demo")
    else:
        raise AssertionError(f"unexpected stage {stage}")
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


# ------------------------------------------------------------- the driver
class Coordinator:
    """Drives the installed runner from an unrelated cwd, as a host would."""

    def __init__(self, scripts: Path, folder: Path, cwd: Path):
        self.scripts, self.folder, self.cwd = scripts, folder, cwd
        self.served = []          # (stage, request_id) in dispatch order

    def run(self, *args) -> dict:
        env = os.environ.copy()
        # Retain only installed dependencies, never source-repo imports.
        env["PYTHONPATH"] = os.pathsep.join(
            p for p in sys.path if Path(p).name == "site-packages")
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [sys.executable, str(self.scripts / "rfq_run.py"), *map(str, args)],
            cwd=self.cwd, env=env, capture_output=True, text=True,
            encoding="utf-8", timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stderr == "", result.stderr
        return json.loads(result.stdout)

    def next(self, *extra) -> dict:
        return self.run("next", self.folder, "--host", "claude",
                        "--project", "Cedar Demo", *extra)

    def dispatch(self, result: dict) -> None:
        assert result["status"] in ("dispatch", "repair"), result
        for request in result["requests"]:
            assert request["host"] == "claude"
            assert request["inherit_history"] is False
            assert request["agent"] == "general-purpose"
            event = self.run("event", self.folder, "--request-id",
                             request["request_id"], "--event", "started")
            assert event["status"] == "recorded"
            _serve(request)
            event = self.run("event", self.folder, "--request-id",
                             request["request_id"], "--event", "completed")
            assert event == {"status": "recorded",
                             "request_id": request["request_id"],
                             "event": "completed"}
            self.served.append((request["stage"], request["request_id"]))

    def loop(self, *extra, limit: int = 12) -> dict:
        """`next` until the runner stops needing workers."""
        for _ in range(limit):
            result = self.next(*extra)
            if result["status"] in ("done", "stopped", "blocked"):
                return result
            assert result["status"] == "dispatch", result
            self.dispatch(result)
        raise AssertionError("the runner never settled")


@pytest.fixture(scope="module")
def coordinator(tmp_path_factory) -> Coordinator:
    tmp = tmp_path_factory.mktemp("host")
    installed = tmp / "installed" / "rfq-insight"
    shutil.copytree(PLUGIN, installed,
                    ignore=shutil.ignore_patterns("__pycache__"))
    assert (installed / ".claude-plugin" / "plugin.json").is_file()
    folder = tmp / "RFQ with spaces"
    shutil.copytree(ROOT / "examples" / "synthetic-rfq", folder)
    image = Image.new("RGB", (800, 400), "white")
    ImageDraw.Draw(image).text((30, 30), TRANSCRIPTION, fill="black")
    image.save(folder / "review.png")
    return Coordinator(installed / "skills" / "rfq-insight" / "scripts",
                       folder, cwd=tmp)


@pytest.fixture(scope="module")
def finished(coordinator: Coordinator) -> dict:
    """The whole run, remembering what each step returned."""
    log = {}
    # The figures worker is needed even when the user only wants the
    # documents read: `--until figures` dispatches it first ...
    log["first"] = coordinator.next("--until", "figures")
    assert log["first"]["status"] == "dispatch"
    assert log["first"]["stage"] == "figures"
    coordinator.dispatch(log["first"])
    # ... and only reports `stopped` once the stage is complete.
    log["stopped"] = coordinator.next("--until", "figures")
    log["analysis"] = coordinator.next()
    assert log["analysis"]["status"] == "dispatch"
    assert log["analysis"]["stage"] == "analysis"
    coordinator.dispatch(log["analysis"])
    log["done"] = coordinator.loop()
    return log


# ------------------------------------------------------------------ tests
def test_until_figures_dispatches_the_figure_worker_then_stops(finished):
    first = finished["first"]
    (request,) = first["requests"]
    assert request["model"] == "sonnet"
    assert len(request["image_ids"]) == 1
    assert [Path(p).suffix for p in request["outputs"]] == [".txt", ".json"]
    assert all(Path(p).parent.name == "image_text" for p in request["outputs"])
    assert finished["stopped"] == {"status": "stopped", "stage": "figures"}


def test_analysis_request_routes_to_opus_with_the_full_instruction_set(
        coordinator, finished):
    (request,) = finished["analysis"]["requests"]
    assert request["model"] == "opus"
    assert "completely" in request["message"]
    names = [Path(p).name for p in request["instructions"]]
    assert names[0].startswith("RFQ_QA_Extraction_Prompt")
    assert "sections.md" in names
    assert all(Path(p).is_relative_to(coordinator.scripts.parent)
               for p in request["instructions"]), "instructions must come " \
        "from the installed copy, not the source repo"
    corpus_txt = coordinator.folder / "output" / ".work" / "corpus.txt"
    assert "19 December 2026" in corpus_txt.read_text(encoding="utf-8"), \
        "the figure transcription must be merged before the analysis reads"


def test_run_finishes_with_a_deck_and_a_twelve_section_report(
        coordinator, finished):
    done = finished["done"]
    assert done["status"] == "done", done
    pptx, report_path = Path(done["pptx"]), Path(done["report"])
    assert pptx.is_file() and pptx.parent == coordinator.folder / "output"
    assert pptx.read_bytes().startswith(b"PK")
    assert pptx.suffix == ".pptx" and report_path.suffix == ".json"
    assert [s for s, _ in coordinator.served] == [
        "figures", "analysis", "verification", "slides"]

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert len(report["slidePlan"]["questions"]) == 12
    assert [q["number"] for q in report["slidePlan"]["questions"]] == list(range(1, 13))
    assert report["verification"]["status"] == "ok"
    assert report["verification"]["mode"] == "subagent"
    assert report["verification"]["claims"], "the canned answers carry claims"
    assert all(c["verdict"] == "confirmed" for c in report["verification"]["claims"])
    stages = {s["stage"]: s for s in report["run"]["execution"]["stages"]}
    assert stages["analysis"]["requested_model"] == "opus"
    assert stages["figures"]["requested_model"] == "sonnet"
    assert stages["analysis"]["mode"] == "isolated"
    assert report["run"]["projectName"] == "Cedar Demo"
    assert report["run"]["corpusFiles"] == [SOW, APPENDIX, "review.png"]

    evaluation = (coordinator.folder / "output" / ".work" / "evaluation.txt")
    assert "0 fail" in evaluation.read_text(encoding="utf-8")
    assert json.loads((coordinator.folder / "output" / ".work" /
                       "progress.json").read_text())["pending"] == "done"


def test_opportunity_slide_carries_the_analysis_values(finished):
    report = json.loads(Path(finished["done"]["report"]).read_text(encoding="utf-8"))
    info = _opportunity()
    first = report["slidePlan"]["questions"][0]
    assert first["titleEn"] == "Opportunity Info"
    (slide,) = first["slides"]
    assert slide["layout"] == "opportunity"
    rows = dict(slide["rows"])
    assert rows["Customer"] == info["customer"]
    assert rows["Customer contact"] == info["customer_contact"]
    assert rows["Quotation due date"] == info["quotation_due_date"]
    assert rows["Opportunity name"] == info["opportunity_name"]
    assert rows["Project type"] == info["project_type"]
    assert rows["Lead product"] == info["lead_product"]
    assert rows["Technology"] == info["technology"]
    assert rows["Industry"] == info["industry"]
    # No Salesforce account matches the synthetic customer: the lookup is
    # the runner's, never the model's, and it leaves the placeholders.
    assert rows["Account Name (Site)"] == "Info not available"
    assert rows["KAM (PTE)"] == "Info not available"
    assert slide["products"] == [[info["lead_product"], "100%"]]
    assert slide["skills"] == [[info["skills"][0]["name"], "100%"]]

    from pptx import Presentation
    deck = Presentation(str(finished["done"]["pptx"]))
    texts = [shape.text_frame.text for s in deck.slides for shape in s.shapes
             if shape.has_text_frame]
    tables = [cell.text for s in deck.slides for shape in s.shapes
              if shape.has_table for row in shape.table.rows for cell in row.cells]
    assert any(info["customer"] in t for t in texts + tables)
    assert any(info["project_type"] in t for t in texts + tables)


def test_timing_records_every_dispatched_request(coordinator, finished):
    timing = coordinator.run("timing", coordinator.folder)
    assert timing["status"] == "available"
    by_id = {r["request_id"]: r for r in timing["requests"]}
    assert set(by_id) == {rid for _, rid in coordinator.served}
    for stage, request_id in coordinator.served:
        row = by_id[request_id]
        assert row["stage"] == stage and row["mode"] == "dispatch"
        assert row["started_at"] and row["finished_at"]
        assert row["worker_seconds"] >= 0
        assert row["validation"]["accepted"] is True
    assert {s["stage"] for s in timing["stages"]} >= {
        "extract", "figures", "analysis", "verification", "slides",
        "finalize", "evaluate"}


def test_next_on_a_finished_folder_delivers_again_without_rebuilding(
        coordinator, finished):
    output = coordinator.folder / "output"
    before = sorted(p.name for p in output.glob("*.pptx"))
    assert len(before) == 1
    stat = Path(finished["done"]["pptx"]).stat()
    again = coordinator.next()
    assert again == finished["done"]
    assert sorted(p.name for p in output.glob("*.pptx")) == before
    assert Path(again["pptx"]).stat().st_mtime_ns == stat.st_mtime_ns
    # No worker was needed: `done` only re-ran the quality gate.
    assert len(coordinator.served) == 4


def test_restart_slides_dispatches_the_slide_worker_again(
        coordinator, finished):
    restarted = coordinator.next("--restart", "slides")
    assert restarted["status"] == "dispatch"
    assert restarted["stage"] == "slides"
    (request,) = restarted["requests"]
    assert request["model"] == "opus"
    assert Path(request["outputs"][0]).name == "slide_plan.json"
    assert not Path(request["outputs"][0]).exists(), \
        "the previous plan is archived so a fresh worker never reads it"
    work = coordinator.folder / "output" / ".work"
    assert json.loads((work / "progress.json").read_text())["pending"] == "slides"
    assert list((work / "history").rglob("slide_plan.json"))

    coordinator.dispatch(restarted)
    done = coordinator.loop()
    assert done["status"] == "done", done
    old, new = Path(finished["done"]["pptx"]), Path(done["pptx"])
    assert new != old and new.is_file() and old.is_file(), \
        "an existing presentation is never overwritten"
    assert new.stem == old.stem + "_2"
    assert new.read_bytes().startswith(b"PK")
    report = json.loads(Path(done["report"]).read_text(encoding="utf-8"))
    assert len(report["slidePlan"]["questions"]) == 12
    assert [s for s, _ in coordinator.served] == [
        "figures", "analysis", "verification", "slides", "slides"]
