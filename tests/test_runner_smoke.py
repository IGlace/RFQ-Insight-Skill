"""Drive the installed runner from an unrelated working directory.

The plugin folder is copied to an unrelated location first, the way a host
installs it, and `rfq_run.py` is run from a different working directory on
the synthetic package. This checks relocation, the checkpoint layout and the
shape of the worker requests the coordinator dispatches; it does not certify
live model judgement, so the run stops at the first model stage.
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
from msgfile import build_msg
from test_extractors import _minimal_pdf

ROOT = Path(REPO_ROOT)
PLUGIN = ROOT / "plugins" / "rfq-insight"


@pytest.fixture
def installed(tmp_path):
    target = tmp_path / "installed" / "rfq-insight"
    shutil.copytree(PLUGIN, target, ignore=shutil.ignore_patterns("__pycache__"))
    assert (target / ".claude-plugin" / "plugin.json").is_file()
    return target


@pytest.fixture
def runner(installed, tmp_path):
    script = installed / "skills" / "rfq-insight" / "scripts" / "rfq_run.py"

    def run(*args):
        env = os.environ.copy()
        # Retain only installed dependencies, never source-repo imports.
        env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if Path(p).name == "site-packages")
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run([sys.executable, str(script), *map(str, args)],
                                cwd=tmp_path, env=env, capture_output=True, text=True,
                                encoding="utf-8", timeout=180)
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)
    return run


def _package(tmp_path, name="RFQ with spaces"):
    folder = tmp_path / name
    shutil.copytree(ROOT / "examples" / "synthetic-rfq", folder)
    return folder


def test_extract_stops_at_the_requested_stage_and_writes_the_corpus(runner, tmp_path):
    folder = _package(tmp_path)
    assert runner("next", folder, "--host", "claude", "--until", "extract") == \
        {"status": "stopped", "stage": "extract"}
    work = folder / "output" / ".work"
    for name in ("progress.json", "corpus.json"):
        assert (work / name).is_file(), name
    corpus = json.loads((work / "corpus.json").read_text(encoding="utf-8"))
    files = corpus["filesContents"]
    assert {entry["filename"] for entry in files} == \
        {"01_statement_of_work.txt", "02_appendix_b.txt"}
    assert any("Northwind Mobility requests a proposal" in entry["extracted_text"]
               for entry in files)
    assert not list(folder.glob("output/*.pptx"))


def test_text_only_package_dispatches_the_analysis_on_the_claude_route(runner, installed, tmp_path):
    folder = _package(tmp_path)
    outcome = runner("next", folder, "--host", "claude", "--project", "Cedar Demo")
    assert outcome["status"] == "dispatch" and outcome["stage"] == "analysis"
    [request] = outcome["requests"]
    assert request["model"] == "opus"
    assert request["inherit_history"] is False
    assert request["agent"] == "general-purpose"
    assert request["request_id"]
    # Instruction files are resolved against the INSTALLED copy, not the repo.
    for path in request["instructions"]:
        assert Path(path).is_file(), path
        assert Path(path).is_relative_to(installed), path
    assert Path(request["instructions"][0]).name == "RFQ_QA_Extraction_Prompt_v15.md"
    assert any(Path(p).name == "90_guidance_denominators.md" for p in request["instructions"])
    work = folder / "output" / ".work"
    assert Path(request["inputs"][0]) == work / "corpus.txt"
    assert Path(request["outputs"][0]) == work / "analysis.json"
    assert "RFQ_QA_Extraction_Prompt_v15.md" in request["message"]
    assert "completely" in request["message"]
    # Inspection is read-only and already sees the issued request.
    timing = runner("timing", folder)
    assert timing["status"] == "available"
    assert timing["requests"][0]["request_id"] == request["request_id"]
    assert timing["requests"][0]["requested_model"] == "opus"


def test_mail_attachments_reach_the_analysis_corpus(runner, tmp_path):
    folder = _package(tmp_path)
    forwarded = dict(subject="Original RFQ", sender=("E", "e@x.invalid"), to=("A", "a@x.invalid"),
                     body="The original request.",
                     attachments=[("Annex C.pdf", _minimal_pdf(["Annex C load cases"]))])
    build_msg(str(folder / "cover.msg"), subject="RFQ cover note", sender=("D", "d@x.invalid"),
              to=("A", "a@x.invalid"), body="Please see the attached appendix.",
              attachments=[("Appendix B.pdf", _minimal_pdf(["Appendix B scope"])),
                           ("CAD_data.zip", b"PK\x03\x04junk"),
                           ("Original RFQ", forwarded)])
    outcome = runner("next", folder, "--host", "claude", "--project", "Cedar Demo")
    # Neither the archive nor the forwarded mail stops the run.
    assert outcome["status"] == "dispatch" and outcome["stage"] == "analysis"
    text = (folder / "output" / ".work" / "corpus.txt").read_text(encoding="utf-8")
    assert "=== FILE: cover.msg ===" in text
    assert "Subject: RFQ cover note" in text
    assert "=== FILE: cover.msg \u203a Appendix B.pdf ===" in text
    assert "Appendix B scope" in text
    assert "=== FILE: cover.msg \u203a Original RFQ.msg ===" in text
    assert "=== FILE: cover.msg \u203a Original RFQ.msg \u203a Annex C.pdf ===" in text
    assert "Annex C load cases" in text
    corpus = json.loads((folder / "output" / ".work" / "corpus.json").read_text(encoding="utf-8"))
    assert corpus["extraction"]["ignored"] == ["cover.msg \u203a CAD_data.zip"]


def test_pictures_are_transcribed_before_the_analysis_on_the_codex_route(runner, tmp_path):
    folder = _package(tmp_path)
    image = Image.new("RGB", (800, 400), "white")
    ImageDraw.Draw(image).text((30, 30), "Review: 19 December 2026", fill="black")
    image.save(folder / "review.png")

    outcome = runner("next", folder, "--host", "codex")
    assert outcome["status"] == "dispatch" and outcome["stage"] == "figures"
    [request] = outcome["requests"]
    assert request["model"] == "gpt-6.1-sol"
    assert request["reasoning_effort"] == "medium"
    assert request["inherit_history"] is False
    assert request["image_ids"] == ["review.png__img01"]
    assert Path(request["instructions"][0]).name == "RFQ_Figure_Transcription_Prompt_v3.md"
    work = folder / "output" / ".work"
    [output] = map(Path, request["outputs"])
    assert output == work / "image_text" / "review.png__img01.txt"

    # The worker's transcription is folded into the corpus the analysis reads.
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("Review: 19 December 2026", encoding="utf-8")
    outcome = runner("next", folder, "--host", "codex", "--completed", request["request_id"])
    assert outcome["status"] == "dispatch" and outcome["stage"] == "analysis"
    [analysis] = outcome["requests"]
    assert analysis["model"] == "gpt-6.1-sol"
    assert analysis["reasoning_effort"] == "high"
    assert "19 December 2026" in (work / "corpus.txt").read_text(encoding="utf-8")


def test_a_comparison_needs_two_finished_runs(runner, tmp_path):
    a = _package(tmp_path, "RFQ A")
    b = _package(tmp_path, "RFQ B")
    outcome = runner("compare", a, b)
    assert outcome["status"] == "blocked"
    assert "RFQ A" in outcome["message"]


def test_restarting_extract_keeps_the_saved_identity(runner, tmp_path):
    """--author/--department are saved with the run like --project: a
    re-extraction without the flags keeps them; the dispatch is unchanged."""
    folder = _package(tmp_path)
    corpus_path = folder / "output" / ".work" / "corpus.json"
    assert runner("next", folder, "--host", "claude", "--until", "extract",
                  "--author", "A. One", "--department", "LBP") == \
        {"status": "stopped", "stage": "extract"}
    assert runner("next", folder, "--host", "claude", "--until", "extract",
                  "--restart", "extract") == \
        {"status": "stopped", "stage": "extract"}
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    assert (corpus["author"], corpus["department"]) == ("A. One", "LBP")

    outcome = runner("next", folder, "--host", "claude")
    assert outcome["status"] == "dispatch" and outcome["stage"] == "analysis"
    [request] = outcome["requests"]
    assert request["model"] == "opus"
    assert "A. One" not in json.dumps(request)
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    assert (corpus["author"], corpus["department"]) == ("A. One", "LBP")
    assert not list(folder.glob("output/*.pptx"))
