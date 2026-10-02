"""Run the installed skill's CLIs end to end with canned model responses.

The plugin folder is copied to an unrelated location first, the way a host
installs it, and the run is driven from a different working directory. This
checks relocation, filesystem contracts, checkpoints and host hand-over; it
does not certify live model judgement.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw

from conftest import REPO_ROOT
from test_finalize import _analysis, _draft_plan

ROOT = Path(REPO_ROOT)
PLUGIN = ROOT / "plugins" / "rfq-insight"


def test_installed_plugin_resumes_across_hosts_from_unrelated_cwd(tmp_path):
    installed = tmp_path / "installed" / "rfq-insight"
    shutil.copytree(PLUGIN, installed, ignore=shutil.ignore_patterns("__pycache__"))
    assert (installed / ".claude-plugin" / "plugin.json").is_file()
    scripts = installed / "skills" / "rfq-insight" / "scripts"
    folder = tmp_path / "RFQ with spaces"
    shutil.copytree(ROOT / "examples" / "synthetic-rfq", folder)
    image = Image.new("RGB", (800, 400), "white")
    ImageDraw.Draw(image).text((30, 30), "Review: 19 December 2026", fill="black")
    image.save(folder / "review.png")
    work = folder / "output" / ".work"

    def run(script, *args):
        env = os.environ.copy()
        # Retain only installed dependencies, never source-repo imports.
        env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if Path(p).name == "site-packages")
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run([sys.executable, str(scripts / script), *map(str, args)],
                                cwd=tmp_path, env=env, capture_output=True, text=True,
                                encoding="utf-8", timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout

    def state(action, stage):
        run("workflow_state.py", folder, action, stage)

    # A Claude host starts the run.
    state("--start", "extract")
    run("extract_corpus.py", folder, "--project", "Cedar Demo")
    state("--complete", "extract")
    state("--start", "figures")
    manifest = json.loads((work / "images.json").read_text())
    assert len(manifest["images"]) == 1
    figure = json.loads(run("stage_request.py", folder, "--host", "claude",
                            "--stage", "figures", "--image-id", manifest["images"][0]["id"]))
    assert figure["model"] == "sonnet"
    output = Path(figure["outputs"][0])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("Review: 19 December 2026", encoding="utf-8")
    run("merge_image_text.py", folder)
    state("--complete", "figures")
    state("--start", "analysis")
    run("corpus_text.py", folder, "--out", work / "corpus.txt")
    assert "19 December 2026" in (work / "corpus.txt").read_text(encoding="utf-8")
    analysis_request = json.loads(run("stage_request.py", folder, "--host", "claude", "--stage", "analysis"))
    assert analysis_request["agent"] == "general-purpose"
    assert analysis_request["model"] == "opus"
    assert "completely" in analysis_request["message"]
    analysis = _analysis()
    for answer in analysis["answers"]:
        answer["evidence_files"] = [{"filename": "01_statement_of_work.txt"}]
    analysis["answers"][6]["answer"] = "Prototype shipping owner not stated."
    Path(analysis_request["outputs"][0]).write_text(json.dumps(analysis))
    run("validate.py", "--analysis", work / "analysis.json")
    run("record_execution.py", folder, "--host", "claude", "--stage", "analysis", "--mode", "isolated")
    state("--complete", "analysis")

    # A Codex host continues from the shared checkpoints.
    assert run("workflow_state.py", folder, "--resume").strip() == "verification"
    state("--start", "verification")
    run("extract_claims.py", folder)
    verification_request = json.loads(run("stage_request.py", folder, "--host", "codex", "--stage", "verification"))
    assert verification_request["inherit_history"] is False
    claims = json.loads((work / "claims.json").read_text())["claims"]
    assert claims
    verdicts = {"verdicts": [{"id": c["id"], "verdict": "confirmed", "evidence": ""} for c in claims]}
    Path(verification_request["outputs"][0]).write_text(json.dumps(verdicts))
    run("apply_verdicts.py", folder)
    state("--complete", "verification")
    state("--start", "slides")
    run("plan_input.py", folder)
    request = json.loads(run("stage_request.py", folder, "--host", "codex", "--stage", "slides"))
    plan = _draft_plan()
    plan["projectName"] = "Cedar Demo"
    Path(request["outputs"][0]).write_text(json.dumps(plan))
    run("validate.py", "--plan", work / "slide_plan.json")
    state("--complete", "slides")
    state("--start", "finalize")
    run("finalize.py", folder)
    state("--complete", "finalize")
    deliverables = json.loads((work / "deliverables.json").read_text(encoding="utf-8"))
    deck, report = Path(deliverables["pptx"]), Path(deliverables["report"])
    assert deck == folder / "output" / "Cedar_Demo_RFQ_Analysis.pptx"
    assert deck.read_bytes().startswith(b"PK")
    state("--start", "evaluate")
    run("evaluate.py", report, "--corpus", work / "corpus.json")
    state("--complete", "evaluate")
    assert run("workflow_state.py", folder, "--resume").strip() == "done"
    result = json.loads(report.read_text(encoding="utf-8"))
    assert len(result["slidePlan"]["questions"]) == 11
    assert result["verification"]["status"] == "ok"
    assert result["run"]["execution"]["stages"][0]["requested_model"] == "opus"
    assert output.read_text() == "Review: 19 December 2026"
