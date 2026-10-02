"""An interrupted upstream rerun must never render an older downstream plan."""

import json

import pytest

import workflow_state as ws


def test_interrupted_analysis_rerun_overrides_old_slide_plan(tmp_path):
    work = tmp_path / "output" / ".work"
    work.mkdir(parents=True)
    (work / "slide_plan.json").write_text('{"old": true}')
    ws.start(tmp_path, "analysis")
    (work / "analysis.json").write_text('{"new": true}')
    assert ws.resume(tmp_path) == "analysis"
    ws.complete(tmp_path, "analysis")
    assert ws.resume(tmp_path) == "verification"
    assert (work / "slide_plan.json").is_file()


def test_interrupted_slide_rerun_cannot_use_old_plan(tmp_path):
    ws.start(tmp_path, "slides")
    work = tmp_path / "output" / ".work"
    (work / "slide_plan.json").write_text('{"old": true}')
    assert ws.resume(tmp_path) == "slides"
    ws.complete(tmp_path, "slides")
    assert ws.resume(tmp_path) == "finalize"


def test_legacy_plan_input_requires_slide_planning(tmp_path):
    work = tmp_path / "output" / ".work"
    work.mkdir(parents=True)
    (work / "plan_input.json").write_text("{}")
    assert ws.resume(tmp_path) == "slides"


def test_corrupt_progress_is_not_ignored(tmp_path):
    ws.start(tmp_path, "analysis")
    (tmp_path / "output" / ".work" / "progress.json").write_text("broken")
    with pytest.raises(ValueError):
        ws.resume(tmp_path)


def test_stage_cannot_complete_out_of_order(tmp_path):
    ws.start(tmp_path, "analysis")
    with pytest.raises(ValueError, match="pending"):
        ws.complete(tmp_path, "slides")
    assert ws.resume(tmp_path) == "analysis"


def test_start_archives_previous_answers_before_fresh_worker(tmp_path):
    work = tmp_path / "output" / ".work"
    work.mkdir(parents=True)
    path = work / "verdicts.json"
    path.write_text('{"old": true}')
    ws.start(tmp_path, "verification")
    assert not path.exists()
    history = list((work / "history").rglob("verdicts.json"))
    assert len(history) == 1
    assert json.loads(history[0].read_text()) == {"old": True}
    ws.start(tmp_path, "verification")
    assert history[0].is_file()


def test_figures_preserve_nonempty_text_and_archive_empty_output(tmp_path):
    work = tmp_path / "output" / ".work"
    text = work / "image_text"
    text.mkdir(parents=True)
    (text / "good.txt").write_text("20 October")
    (text / "empty.txt").write_text("  ")
    ws.start(tmp_path, "figures")
    assert (text / "good.txt").read_text() == "20 October"
    assert not (text / "empty.txt").exists()


def test_completed_run_resumes_quality_check_for_delivery(tmp_path):
    ws.start(tmp_path, "evaluate")
    ws.complete(tmp_path, "evaluate")
    assert ws.resume(tmp_path) == "done"
    assert json.loads((tmp_path / "output" / ".work" / "progress.json").read_text())["pending"] == "done"
