"""rfq.workers: routing, fresh-worker requests, evidence boundaries."""

import hashlib
import json
import re
from pathlib import Path

import pytest

from rfq import state, workers

PNG_A = b"image fixture A"
PNG_B = b"image fixture B"


@pytest.fixture
def package(tmp_path):
    folder = tmp_path / "Acme RFQ"
    work = folder / "output" / ".work"
    work.mkdir(parents=True)
    (work / "corpus.txt").write_text("=== FILE: SOR.txt ===\nDue October 20.", encoding="utf-8")
    (work / "claims.json").write_text('{"claims": [{"id": 1}]}')
    (work / "analysis.json").write_text('{"secret_reasoning": "DO NOT PASS"}')
    (work / "plan_input.json").write_text('{"answers": []}')
    (work / "followup_question.json").write_text('{"question": "When is SOP?"}')
    (work / "images").mkdir()
    (work / "images" / "chart.png").write_bytes(PNG_A)
    (work / "images" / "photo.png").write_bytes(PNG_B)
    (work / "images.json").write_text(json.dumps({"images": [
        {"id": "sor__img1", "file": "chart.png", "source": "SOR.pdf",
         "locator": "p. 1", "sha256": hashlib.sha256(PNG_A).hexdigest()},
        {"id": "sor__img2", "file": "photo.png", "source": "SOR.pdf",
         "locator": "p. 2", "sha256": hashlib.sha256(PNG_B).hexdigest()}]}))
    return folder


# ------------------------------------------------------------------ route
@pytest.mark.parametrize("host,expected", [
    ("claude", ["opus", "opus", "sonnet", "opus", "opus", "haiku"]),
    ("codex", ["gpt-6.1-sol"] * 5 + ["gpt-6-luna"]),
])
def test_shipped_routes(host, expected):
    assert [workers.route(host, role)["model"] for role in workers.ROLES] == expected


def test_codex_routes_carry_a_reasoning_effort():
    assert workers.route("codex", "analysis")["reasoning_effort"] == "high"
    assert "reasoning_effort" not in workers.route("claude", "analysis")


@pytest.mark.parametrize("host,role", [("gemini", "analysis"), ("claude", "render"),
                                       ("", "analysis")])
def test_unknown_host_or_role_is_refused(host, role):
    with pytest.raises(ValueError, match="Unknown host or role"):
        workers.route(host, role)


@pytest.mark.parametrize("model", ["gpt-6-sol", "gpt-6.1-luna", "gpt-12-sol"])
def test_codex_accepts_sol_and_luna_families(model):
    config = workers.load_routes()
    config["codex"]["analysis"] = {"model": model, "reasoning_effort": "medium"}
    assert workers.route("codex", "analysis", config=config)["model"] == model


@pytest.mark.parametrize("model", ["gpt-6-astra", "gpt-6.1.2-sol", "sol", "gpt-6-sol-mini",
                                   "GPT-6-SOL", "opus"])
def test_codex_refuses_other_model_names(model):
    config = workers.load_routes()
    config["codex"]["analysis"]["model"] = model
    with pytest.raises(ValueError, match="Sol or Luna"):
        workers.route("codex", "analysis", config=config)


@pytest.mark.parametrize("effort", [None, "max", "xhigh", ""])
def test_codex_effort_must_be_low_medium_or_high(effort):
    config = workers.load_routes()
    config["codex"]["slides"]["reasoning_effort"] = effort
    with pytest.raises(ValueError, match="low, medium or high"):
        workers.route("codex", "slides", config=config)


@pytest.mark.parametrize("model", ["opus", "sonnet", "haiku"])
def test_claude_accepts_its_aliases(model):
    config = workers.load_routes()
    config["claude"]["figures"]["model"] = model
    assert workers.route("claude", "figures", config=config) == {"model": model}


@pytest.mark.parametrize("model", ["claude-opus-4", "gpt-6-sol", "Opus", ""])
def test_claude_refuses_full_model_ids(model):
    config = workers.load_routes()
    config["claude"]["analysis"]["model"] = model
    with pytest.raises(ValueError, match="opus, sonnet or haiku"):
        workers.route("claude", "analysis", config=config)


def test_route_returns_a_copy_of_the_configuration():
    config = workers.load_routes()
    result = workers.route("codex", "analysis", config=config)
    result["model"] = "changed"
    assert config["codex"]["analysis"]["model"] == "gpt-6.1-sol"


# ---------------------------------------------------------------- prepare
def test_analysis_request_bundles_prompt_sections_and_nine_knowledge_files(package):
    request = workers.prepare(package, "codex", "analysis")
    names = [Path(p).name for p in request["instructions"]]
    assert names[0] == "RFQ_QA_Extraction_Prompt_v13.md"
    assert names[1] == "sections.md"
    knowledge = names[2:]
    assert len(knowledge) == 9
    assert knowledge == sorted(knowledge)
    assert all(n.endswith(".md") for n in knowledge)
    assert all(Path(p).is_absolute() and Path(p).is_file()
               for p in request["instructions"] + request["inputs"])
    assert [Path(p).name for p in request["inputs"]] == ["corpus.txt"]
    assert [Path(p).name for p in request["outputs"]] == ["analysis.json"]


def test_analysis_refuses_an_incomplete_knowledge_pack(package, tmp_path):
    root = tmp_path / "skill"
    (root / "references" / "prompts").mkdir(parents=True)
    (root / "references" / "knowledge").mkdir()
    (root / "references" / "platforms").mkdir()
    for name in workers.PROMPTS.values():
        (root / "references" / "prompts" / name).write_text("prompt")
    (root / "references" / "sections.md").write_text("sections")
    (root / "references" / "knowledge" / "10_only.md").write_text("one")
    (root / "references" / "platforms" / "models.json").write_text(
        json.dumps(workers.load_routes()))
    with pytest.raises(ValueError, match="nine domain references"):
        workers.prepare(package, "codex", "analysis", skill_root=root)


def test_request_shape_is_explicit_about_routing_and_isolation(package):
    request = workers.prepare(package, "claude", "analysis")
    assert request["host"] == "claude" and request["stage"] == "analysis"
    assert request["model"] == "opus"
    assert request["agent"] == "general-purpose"
    assert request["inherit_history"] is False
    assert request["reuse_existing"] is False
    assert re.fullmatch(r"[0-9a-f]{32}", request["request_id"])
    assert "repair_message" not in request


def test_codex_request_has_no_claude_agent(package):
    request = workers.prepare(package, "codex", "analysis")
    assert "agent" not in request
    assert request["reasoning_effort"] == "high"


def test_message_demands_a_complete_read_and_lists_only_its_files(package):
    request = workers.prepare(package, "claude", "analysis")
    message = request["message"]
    assert "completely" in message
    assert "Complete only the RFQ analysis task" in message
    for path in request["instructions"] + request["inputs"] + request["outputs"]:
        assert path in message
    assert "analysis.json" in message            # the output, by its path
    assert "claims.json" not in message


def test_telemetry_describes_the_inputs_and_hashes_the_corpus(package):
    request = workers.prepare(package, "codex", "analysis")
    corpus = package / "output" / ".work" / "corpus.txt"
    assert request["input_sizes"] == [{"path": str(corpus.resolve()),
                                       "bytes": corpus.stat().st_size}]
    assert request["input_bytes"] == corpus.stat().st_size
    assert request["instruction_bytes"] == sum(
        Path(p).stat().st_size for p in request["instructions"])
    assert request["message_bytes"] == len(request["message"].encode("utf-8"))
    assert request["corpus_identity"] == {
        "path": str(corpus.resolve()),
        "sha256": hashlib.sha256(corpus.read_bytes()).hexdigest()}
    assert "telemetry_error" not in request


def test_verification_receives_no_analysis_or_history(package):
    request = workers.prepare(package, "codex", "verification")
    assert request["inherit_history"] is False
    assert {Path(p).name for p in request["inputs"]} == {"corpus.txt", "claims.json"}
    assert len(request["instructions"]) == 1
    assert Path(request["instructions"][0]).name == "RFQ_Claim_Verifier_Prompt_v2.md"
    assert "DO NOT PASS" not in json.dumps(request)
    assert "analysis.json" not in request["message"]
    assert [Path(p).name for p in request["outputs"]] == ["verdicts.json"]


def test_slide_planner_cannot_reopen_corpus(package):
    request = workers.prepare(package, "claude", "slides")
    assert [Path(p).name for p in request["inputs"]] == ["plan_input.json"]
    assert "corpus.txt" not in request["message"]
    assert Path(request["instructions"][0]).name == "RFQ_Slide_Plan_Prompt_v13.md"
    assert [Path(p).name for p in request["outputs"]] == ["slide_plan.json"]


def test_followup_reads_the_question_with_the_corpus(package):
    state.start(package, "analysis")        # analysis not yet run on these files
    request = workers.prepare(package, "claude", "followup")
    assert [Path(p).name for p in request["inputs"]] == ["corpus.txt", "followup_question.json"]
    assert "DO NOT PASS" not in json.dumps(request)
    assert [Path(p).name for p in request["outputs"]] == ["followup_answer.json"]


def test_followup_gets_the_answers_once_analysis_is_behind_it(package):
    state.start(package, "finalize")
    request = workers.prepare(package, "claude", "followup")
    assert [Path(p).name for p in request["inputs"]] == [
        "corpus.txt", "followup_question.json", "analysis.json"]


@pytest.mark.parametrize("stage,model", [
    ("analysis", "opus"), ("verification", "opus"),
    ("figures", "sonnet"), ("slides", "opus"), ("followup", "opus"),
])
def test_claude_uses_fresh_general_agent_and_same_model(package, stage, model):
    request = workers.prepare(
        package, "claude", stage,
        image_id="sor__img1" if stage == "figures" else None)
    assert request["agent"] == "general-purpose"
    assert request["model"] == model
    assert request["inherit_history"] is False
    assert "DO NOT PASS" not in json.dumps(request)


def test_unknown_stage_is_refused(package):
    with pytest.raises(ValueError, match="Unknown RFQ stage"):
        workers.prepare(package, "claude", "support")


def test_image_id_only_belongs_to_figures(package):
    with pytest.raises(ValueError, match="image-id"):
        workers.prepare(package, "claude", "slides", image_id="sor__img1")


def test_missing_checkpoint_does_not_create_outputs(package):
    (package / "output" / ".work" / "claims.json").unlink()
    with pytest.raises(ValueError, match="claims.json"):
        workers.prepare(package, "codex", "verification")
    assert not (package / "output" / ".work" / "verdicts.json").exists()


def test_missing_folder_is_refused(tmp_path):
    with pytest.raises(ValueError, match="couldn't find"):
        workers.prepare(tmp_path / "nope", "codex", "analysis")


# ------------------------------------------------------------ 600k gate
def test_oversized_corpus_text_is_refused_for_analysis(package):
    (package / "output" / ".work" / "corpus.txt").write_text("x" * 600_001, encoding="utf-8")
    with pytest.raises(ValueError, match="oversized analysis input"):
        workers.prepare(package, "codex", "analysis")


def test_oversized_original_corpus_is_refused_even_when_the_text_is_short(package):
    work = package / "output" / ".work"
    (work / "corpus.json").write_text(json.dumps({"filesContents": [
        {"filename": "big.pdf", "extracted_text": "y" * 600_001}]}))
    with pytest.raises(ValueError, match="oversized original corpus"):
        workers.prepare(package, "codex", "analysis")


def test_corpus_at_the_limit_is_accepted(package):
    (package / "output" / ".work" / "corpus.txt").write_text("x" * 600_000, encoding="utf-8")
    assert workers.prepare(package, "codex", "analysis")["input_bytes"] == 600_000


def test_source_catalogue_rides_along_when_it_fits(package):
    work = package / "output" / ".work"
    (work / "source_catalog.json").write_text('{"references": []}')
    request = workers.prepare(package, "codex", "analysis")
    assert [Path(p).name for p in request["inputs"]] == ["corpus.txt", "source_catalog.json"]
    (work / "source_catalog.json").write_text("z" * 600_000)
    request = workers.prepare(package, "codex", "analysis")
    assert [Path(p).name for p in request["inputs"]] == ["corpus.txt"]


# ---------------------------------------------------------- scoped repair
def test_scoped_repair_adds_a_repair_message_and_keeps_the_request(package):
    request = workers.prepare(package, "claude", "slides")
    original_message = request["message"]
    repaired = workers.scoped_repair(request, ["Question 3 has no slides."])
    assert repaired is request
    assert repaired["message"] == original_message
    assert "Repair only the validation faults" in repaired["repair_message"]
    assert "Question 3 has no slides." in repaired["repair_message"]
    assert request["outputs"][0] in repaired["repair_message"]


# ---------------------------------------------------------------- figures
def test_figures_are_individually_bounded_and_existing_text_is_reused(package):
    request = workers.prepare(package, "codex", "figures", image_id="sor__img1")
    assert [Path(p).name for p in request["inputs"]] == ["chart.png"]
    assert [Path(p).name for p in request["outputs"]] == ["sor__img1.txt", "sor__img1.json"]
    assert request["image_ids"] == ["sor__img1"]
    assert request["reuse_existing"] is False
    assert Path(request["instructions"][0]).name == "RFQ_Figure_Transcription_Prompt_v2.md"
    work = package / "output" / ".work"
    # The worker writes a valid pair and the coordinator certifies it
    # against the receipt the request left behind.
    text, meta = (Path(p) for p in request["outputs"])
    text.parent.mkdir(exist_ok=True)
    text.write_text("October 20", encoding="utf-8")
    meta.write_text(json.dumps({"category": "chart", "product_relevance": "low",
                                "caption": "Timing chart"}), encoding="utf-8")
    assert (work / "figure_requests.json").is_file()
    again = workers.prepare(package, "codex", "figures", image_id="sor__img1")
    assert again["reuse_existing"] is True
    assert text.read_text(encoding="utf-8") == "October 20"


@pytest.mark.parametrize("bad", ["../outside.png", "/outside.png", "C:/outside.png"])
def test_manifest_cannot_escape_image_directory(package, bad):
    manifest = package / "output" / ".work" / "images.json"
    manifest.write_text(json.dumps({"images": [{"id": "sor__img1", "file": bad}]}))
    with pytest.raises(ValueError):
        workers.prepare(package, "codex", "figures", image_id="sor__img1")


@pytest.mark.parametrize("bad", ["../sor__img1", "nope", ""])
def test_unknown_or_unsafe_image_ids_are_refused(package, bad):
    with pytest.raises(ValueError):
        workers.prepare(package, "codex", "figures", image_id=bad)


def test_figures_batch_covers_every_picture_in_one_request(package):
    request = workers.prepare_figures_batch(package, "claude", ["sor__img1", "sor__img2"])
    assert request["image_ids"] == ["sor__img1", "sor__img2"]
    assert [Path(p).name for p in request["inputs"]] == ["chart.png", "photo.png"]
    assert [Path(p).name for p in request["outputs"]] == [
        "sor__img1.txt", "sor__img1.json", "sor__img2.txt", "sor__img2.json"]
    assert request["model"] == "sonnet" and request["agent"] == "general-purpose"
    assert request["inherit_history"] is False
    assert request["reuse_existing"] is False
    assert "for these 2 picture(s)" in request["message"]
    assert "Treat every picture independently" in request["message"]
    for path in request["inputs"] + request["outputs"]:
        assert path in request["message"]
    assert re.fullmatch(r"[0-9a-f]{32}", request["request_id"])
    assert request["input_bytes"] == len(PNG_A) + len(PNG_B)
    assert request["message_bytes"] == len(request["message"].encode("utf-8"))


def test_figures_batch_needs_at_least_one_picture(package):
    with pytest.raises(ValueError, match="at least one image"):
        workers.prepare_figures_batch(package, "claude", [])


def test_figures_batch_validates_every_picture(package):
    with pytest.raises(ValueError):
        workers.prepare_figures_batch(package, "claude", ["sor__img1", "missing"])


def test_prepare_is_read_only_apart_from_figure_receipts(package):
    before = set(package.rglob("*"))
    for stage in ("analysis", "verification", "slides"):
        workers.prepare(package, "codex", stage)
    assert set(package.rglob("*")) == before
