"""Platform requests must preserve evidence boundaries and explicit routing."""

import json
from pathlib import Path

import pytest

import stage_request as sr


@pytest.fixture
def package(tmp_path):
    folder = tmp_path / "Acme RFQ"
    work = folder / "output" / ".work"
    work.mkdir(parents=True)
    (work / "corpus.txt").write_text("=== FILE: SOR.txt ===\nDue October 20.")
    (work / "claims.json").write_text('{"claims": [{"id": 1}]}')
    (work / "analysis.json").write_text('{"secret_reasoning": "DO NOT PASS"}')
    (work / "plan_input.json").write_text('{"answers": []}')
    (work / "images").mkdir()
    (work / "images" / "chart.png").write_bytes(b"image fixture")
    (work / "images.json").write_text(json.dumps({"images": [
        {"id": "sor__img1", "file": "chart.png"}]}))
    return folder


@pytest.mark.parametrize("host,expected", [
    ("claude", ["opus", "opus", "sonnet", "opus", "haiku"]),
    ("codex", ["gpt-6-sol"] * 4 + ["gpt-6-luna"]),
])
def test_model_routing(host, expected):
    assert [sr.route(host, role)["model"] for role in
            ("analysis", "verification", "figures", "slides", "support")] == expected


def test_verification_receives_no_analysis_or_history(package):
    request = sr.prepare(package, "codex", "verification")
    assert request["inherit_history"] is False
    assert {Path(p).name for p in request["inputs"]} == {"corpus.txt", "claims.json"}
    assert len(request["instructions"]) == 1
    assert Path(request["instructions"][0]).name == "RFQ_Claim_Verifier_Prompt_v2.md"
    assert "DO NOT PASS" not in json.dumps(request)
    assert "analysis.json" not in request["message"]
    assert request["reasoning_effort"] == "high"


def test_slide_planner_cannot_reopen_corpus(package):
    request = sr.prepare(package, "claude", "slides")
    assert [Path(p).name for p in request["inputs"]] == ["plan_input.json"]
    assert "corpus.txt" not in request["message"]
    assert request["agent"] == "general-purpose"


@pytest.mark.parametrize("stage,model", [
    ("analysis", "opus"), ("verification", "opus"),
    ("figures", "sonnet"), ("slides", "opus"),
])
def test_claude_uses_fresh_general_agent_and_same_model(package, stage, model):
    request = sr.prepare(
        package, "claude", stage,
        image_id="sor__img1" if stage == "figures" else None,
    )
    assert request["agent"] == "general-purpose"
    assert request["model"] == model
    assert request["inherit_history"] is False
    assert "DO NOT PASS" not in json.dumps(request)


def test_claude_cli_uses_general_agent_without_plugin_configuration(package, capsys):
    args = [str(package), "--host", "claude", "--stage", "slides"]
    assert sr.main(args) == 0
    assert json.loads(capsys.readouterr().out)["agent"] == "general-purpose"


def test_analysis_includes_all_domain_references(package):
    request = sr.prepare(package, "codex", "analysis")
    assert len(request["instructions"]) == 10
    assert all(Path(p).is_absolute() and Path(p).is_file()
               for p in request["instructions"] + request["inputs"])
    assert Path(request["outputs"][0]).name == "analysis.json"


def test_figures_are_individually_bounded_and_existing_text_is_reused(package):
    request = sr.prepare(package, "codex", "figures", image_id="sor__img1")
    assert [Path(p).name for p in request["inputs"]] == ["chart.png"]
    assert Path(request["outputs"][0]).name == "sor__img1.txt"
    assert request["reuse_existing"] is False
    output = Path(request["outputs"][0])
    output.parent.mkdir()
    output.write_text("October 20")
    assert sr.prepare(package, "codex", "figures", image_id="sor__img1")["reuse_existing"]


def test_missing_checkpoint_does_not_create_outputs(package):
    (package / "output" / ".work" / "claims.json").unlink()
    with pytest.raises(ValueError, match="claims.json"):
        sr.prepare(package, "codex", "verification")
    assert not (package / "output" / ".work" / "verdicts.json").exists()


@pytest.mark.parametrize("bad", ["../outside.png", "/outside.png", "C:/outside.png"])
def test_manifest_cannot_escape_image_directory(package, bad):
    manifest = package / "output" / ".work" / "images.json"
    manifest.write_text(json.dumps({"images": [{"id": "sor__img1", "file": bad}]}))
    with pytest.raises(ValueError):
        sr.prepare(package, "codex", "figures", image_id="sor__img1")


def test_unknown_model_family_rejected():
    config = sr.load_routes()
    config["codex"]["analysis"]["model"] = "gpt-6-astra"
    with pytest.raises(ValueError, match="Sol or Luna"):
        sr.route("codex", "analysis", config=config)


def test_request_cli_is_read_only_and_handles_spaces(package, capsys):
    before = set(package.rglob("*"))
    assert sr.main([str(package), "--host", "codex", "--stage", "analysis"]) == 0
    assert json.loads(capsys.readouterr().out)["model"] == "gpt-6-sol"
    assert set(package.rglob("*")) == before
