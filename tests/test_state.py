"""rfq.state: progress marker, checkpoint archival, execution and timing records."""

import json
import os
import re

import pytest

from rfq import state


def _work(folder):
    work = folder / "output" / ".work"
    work.mkdir(parents=True, exist_ok=True)
    return work


def _request(request_id="req-1", host="claude", stage="analysis", **extra):
    return {"request_id": request_id, "host": host, "stage": stage,
            "model": "opus", "outputs": ["/tmp/analysis.json"], **extra}


# ----------------------------------------------------------------- stages
def test_stage_order_is_the_workflow_order():
    assert state.STAGES == ("extract", "figures", "analysis", "verification",
                            "slides", "finalize", "evaluate")
    assert set(state.MODEL_OUTPUTS) <= set(state.STAGES)


def test_start_rejects_an_unknown_stage_and_a_missing_folder(tmp_path):
    with pytest.raises(ValueError, match="Unknown stage"):
        state.start(tmp_path, "render")
    with pytest.raises(ValueError, match="couldn't find"):
        state.start(tmp_path / "nope", "analysis")


# ------------------------------------------------------------ progress.json
def test_start_writes_the_progress_marker_atomically(tmp_path):
    assert state.start(tmp_path, "analysis") == "analysis"
    work = tmp_path / "output" / ".work"
    data = json.loads((work / "progress.json").read_text(encoding="utf-8"))
    assert data == {"version": 1, "pending": "analysis"}
    assert not list(work.glob("progress-*.tmp"))        # no temp file left over


def test_complete_advances_to_the_next_stage(tmp_path):
    state.start(tmp_path, "analysis")
    assert state.complete(tmp_path, "analysis") == "verification"
    assert state.resume(tmp_path) == "verification"


def test_complete_refuses_a_stage_that_is_not_pending(tmp_path):
    state.start(tmp_path, "analysis")
    with pytest.raises(ValueError, match="pending"):
        state.complete(tmp_path, "slides")
    assert state.resume(tmp_path) == "analysis"


def test_complete_refuses_an_unknown_stage(tmp_path):
    state.start(tmp_path, "analysis")
    with pytest.raises(ValueError, match="Unknown stage"):
        state.complete(tmp_path, "render")


def test_completed_run_resumes_as_done(tmp_path):
    state.start(tmp_path, "evaluate")
    assert state.complete(tmp_path, "evaluate") == "done"
    assert state.resume(tmp_path) == "done"
    marker = tmp_path / "output" / ".work" / "progress.json"
    assert json.loads(marker.read_text(encoding="utf-8"))["pending"] == "done"


def test_corrupt_progress_is_not_ignored(tmp_path):
    state.start(tmp_path, "analysis")
    (tmp_path / "output" / ".work" / "progress.json").write_text("broken")
    with pytest.raises(ValueError):            # json.JSONDecodeError is one
        state.resume(tmp_path)


def test_progress_with_an_unknown_stage_is_invalid(tmp_path):
    work = _work(tmp_path)
    (work / "progress.json").write_text(json.dumps({"version": 1, "pending": "render"}))
    with pytest.raises(ValueError):
        state.resume(tmp_path)


# ---------------------------------------------------------------- archival
def test_start_archives_previous_answers_before_fresh_worker(tmp_path):
    work = _work(tmp_path)
    path = work / "verdicts.json"
    path.write_text('{"old": true}')
    state.start(tmp_path, "verification")
    assert not path.exists()
    history = list((work / "history").rglob("verdicts.json"))
    assert len(history) == 1
    assert re.fullmatch(r"[0-9a-f]{32}", history[0].parent.name)
    assert json.loads(history[0].read_text()) == {"old": True}
    # A second start keeps the earlier archive untouched.
    state.start(tmp_path, "verification")
    assert history[0].is_file()


def test_start_archives_only_its_own_stage_outputs(tmp_path):
    work = _work(tmp_path)
    (work / "analysis.json").write_text('{"old": true}')
    (work / "slide_plan.json").write_text('{"keep": true}')
    state.start(tmp_path, "analysis")
    assert not (work / "analysis.json").exists()
    assert (work / "slide_plan.json").is_file()
    assert len(list((work / "history").rglob("analysis.json"))) == 1


def test_interrupted_analysis_rerun_overrides_old_slide_plan(tmp_path):
    work = _work(tmp_path)
    (work / "slide_plan.json").write_text('{"old": true}')
    state.start(tmp_path, "analysis")
    (work / "analysis.json").write_text('{"new": true}')
    assert state.resume(tmp_path) == "analysis"
    state.complete(tmp_path, "analysis")
    assert state.resume(tmp_path) == "verification"
    assert (work / "slide_plan.json").is_file()


def test_start_refuses_a_symlinked_checkpoint(tmp_path):
    work = _work(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text('{"outside": true}')
    (work / "analysis.json").symlink_to(outside)
    with pytest.raises(ValueError, match="regular file"):
        state.start(tmp_path, "analysis")
    assert outside.read_text() == '{"outside": true}'
    assert not (work / "history").exists()
    # The marker was saved before archival, so the stage still resumes.
    assert state.resume(tmp_path) == "analysis"


def test_start_refuses_a_verification_directory_outside_the_work_folder(tmp_path):
    work = _work(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (work / "verification").symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes|symlink"):
        state.start(tmp_path, "verification")


def test_start_archives_verification_partition_files(tmp_path):
    work = _work(tmp_path)
    part = work / "verification" / "run1"
    part.mkdir(parents=True)
    (part / "part-1.json").write_text("{}")
    (work / "verification_jobs.json").write_text("{}")
    state.start(tmp_path, "verification")
    assert not (part / "part-1.json").exists()
    assert not (work / "verification_jobs.json").exists()
    archived = list((work / "history").rglob("part-1.json"))
    assert len(archived) == 1
    assert archived[0].parent.name == "run1"


def test_figures_start_archives_incomplete_figure_outputs(tmp_path):
    work = _work(tmp_path)
    text = work / "image_text"
    text.mkdir()
    (text / "orphan.txt").write_text("20 October")       # no classification
    state.start(tmp_path, "figures")
    assert not (text / "orphan.txt").exists()
    assert len(list((work / "history").rglob("orphan.txt"))) == 1


def test_extract_start_drops_outstanding_figure_requests(tmp_path):
    work = _work(tmp_path)
    (work / "figure_requests.json").write_text("{}")
    state.start(tmp_path, "extract")
    assert not (work / "figure_requests.json").exists()


# ------------------------------------------------------------------ resume
def test_resume_without_any_checkpoint_starts_at_extract(tmp_path):
    _work(tmp_path)
    assert state.resume(tmp_path) == "extract"


@pytest.mark.parametrize("name,stage", [
    ("corpus.json", "figures"), ("images.json", "figures"),
    ("corpus.txt", "analysis"), ("analysis.json", "verification"),
    ("claims.json", "verification"), ("verification.json", "slides"),
    ("plan_input.json", "slides"), ("slide_plan.json", "finalize"),
])
def test_legacy_runs_infer_the_stage_from_their_checkpoints(tmp_path, name, stage):
    work = _work(tmp_path)
    (work / name).write_text("{}")
    assert state.resume(tmp_path) == stage


def test_legacy_inference_uses_the_newest_checkpoint(tmp_path):
    work = _work(tmp_path)
    (work / "slide_plan.json").write_text("{}")
    (work / "corpus.txt").write_text("")
    os.utime(work / "slide_plan.json", ns=(1_000, 1_000))
    os.utime(work / "corpus.txt", ns=(2_000, 2_000))
    assert state.resume(tmp_path) == "analysis"


def test_legacy_inference_breaks_timestamp_ties_in_workflow_order(tmp_path):
    work = _work(tmp_path)
    for name in ("corpus.json", "corpus.txt"):
        (work / name).write_text("")
        os.utime(work / name, ns=(5_000, 5_000))
    assert state.resume(tmp_path) == "analysis"


def test_progress_marker_wins_over_legacy_checkpoints(tmp_path):
    work = _work(tmp_path)
    (work / "slide_plan.json").write_text("{}")
    state.start(tmp_path, "analysis")
    assert state.resume(tmp_path) == "analysis"


# ------------------------------------------------------------------ record
def test_record_keeps_prior_host_history_and_unknown_actual_model(tmp_path):
    work = _work(tmp_path)
    state.record(tmp_path, "claude", "analysis", "isolated")
    state.record(tmp_path, "codex", "verification", "in-thread",
                 actual_model="gpt-6.1-sol", actual_effort="high",
                 note="Fresh workers unavailable")
    records = json.loads((work / "execution.json").read_text(encoding="utf-8"))["stages"]
    assert [r["host"] for r in records] == ["claude", "codex"]
    assert records[0]["requested_model"] == "opus"
    assert records[0]["requested_reasoning_effort"] is None
    assert records[0]["actual_model"] is None
    assert records[1]["mode"] == "in-thread"
    assert records[1]["requested_model"] == "gpt-6.1-sol"
    assert records[1]["requested_reasoning_effort"] == "medium"   # the route's
    assert records[1]["actual_reasoning_effort"] == "high"        # as reported
    assert records[1]["actual_model"] == "gpt-6.1-sol"
    assert records[1]["note"] == "Fresh workers unavailable"
    assert records[0]["recorded_at"].endswith("+00:00")
    assert not list(work.glob("execution-*.tmp"))


def test_corrupt_execution_history_is_not_overwritten(tmp_path):
    work = _work(tmp_path)
    path = work / "execution.json"
    path.write_text("broken record")
    with pytest.raises(ValueError):
        state.record(tmp_path, "codex", "analysis", "isolated")
    assert path.read_text() == "broken record"


def test_record_needs_an_existing_work_folder(tmp_path):
    with pytest.raises(ValueError, match="checkpoints"):
        state.record(tmp_path, "claude", "analysis", "isolated")


def test_record_rejects_an_unknown_route(tmp_path):
    _work(tmp_path)
    with pytest.raises(ValueError):
        state.record(tmp_path, "gemini", "analysis", "isolated")


# ------------------------------------------------------------------ timing
def test_issue_request_creates_the_timing_record(tmp_path):
    work = _work(tmp_path)
    assert state.issue_request(tmp_path, _request(input_bytes=12,
                               input_sizes=[{"path": "/tmp/corpus.txt", "bytes": 12}]),
                               attempt=1) is True
    data = json.loads((work / state.TIMING_FILE).read_text(encoding="utf-8"))
    assert data["version"] == 1 and data["stages"] == []
    [row] = data["requests"]
    assert row["request_id"] == "req-1"
    assert row["mode"] == "dispatch" and row["attempt"] == 1
    assert row["events"] == [] and row["validation"] is None
    assert row["issued_at"].endswith("+00:00")


def test_issue_request_refuses_a_repeated_id_and_notes_the_problem(tmp_path):
    work = _work(tmp_path)
    assert state.issue_request(tmp_path, _request(), 1)
    assert state.issue_request(tmp_path, _request(), 2) is False
    assert "already issued" in (work / "timing_error.txt").read_text(encoding="utf-8")
    data = json.loads((work / state.TIMING_FILE).read_text(encoding="utf-8"))
    assert len(data["requests"]) == 1


def test_events_follow_the_request_lifecycle(tmp_path):
    _work(tmp_path)
    state.issue_request(tmp_path, _request(), 1)
    result = state.event(tmp_path, "req-1", "started",
                         observed_at="2026-10-14T10:00:00Z")
    assert result == {"status": "recorded", "request_id": "req-1", "event": "started"}
    with pytest.raises(ValueError, match="lifecycle"):
        state.event(tmp_path, "req-1", "started")
    with pytest.raises(ValueError, match="precedes"):
        state.event(tmp_path, "req-1", "completed",
                    observed_at="2026-10-14T09:59:00+00:00")
    state.event(tmp_path, "req-1", "completed",
                observed_at="2026-10-14T10:05:30+00:00",
                actual_model="opus", input_tokens=1200, output_tokens=300)
    with pytest.raises(ValueError, match="lifecycle"):
        state.event(tmp_path, "req-1", "failed")


def test_event_rejects_bad_observations(tmp_path):
    _work(tmp_path)
    state.issue_request(tmp_path, _request(), 1)
    with pytest.raises(ValueError, match="Unknown lifecycle"):
        state.event(tmp_path, "req-1", "paused")
    with pytest.raises(ValueError, match="timezone"):
        state.event(tmp_path, "req-1", "started", observed_at="2026-10-14T10:00:00")
    with pytest.raises(ValueError, match="nonnegative"):
        state.event(tmp_path, "req-1", "started", input_tokens=-1)
    with pytest.raises(ValueError, match="nonnegative"):
        state.event(tmp_path, "req-1", "started", output_tokens=True)
    with pytest.raises(ValueError, match="Unknown request ID"):
        state.event(tmp_path, "req-9", "started")


def test_event_without_a_timing_record_is_an_error(tmp_path):
    _work(tmp_path)
    with pytest.raises(ValueError, match="No timing record"):
        state.event(tmp_path, "req-1", "started")


def test_coordinator_time_source_is_recorded(tmp_path):
    work = _work(tmp_path)
    state.issue_request(tmp_path, _request(), 1)
    state.event(tmp_path, "req-1", "started")
    state.event(tmp_path, "req-1", "failed", observed_at="2099-01-01T00:00:00Z")
    [row] = json.loads((work / state.TIMING_FILE).read_text(encoding="utf-8"))["requests"]
    assert [e["time_source"] for e in row["events"]] == ["coordinator_observation", "host"]
    assert row["events"][1]["observed_at"] == "2099-01-01T00:00:00.000000+00:00"


def test_validate_requests_records_the_verdict_once(tmp_path):
    work = _work(tmp_path)
    state.issue_request(tmp_path, _request(), 1)
    state.issue_request(tmp_path, _request("req-2"), 1)
    state.validate_requests(tmp_path, ["req-1"], False, problems=["Section 3 is empty."])
    state.validate_requests(tmp_path, ["req-1", "req-2"], True)
    rows = {r["request_id"]: r for r in json.loads(
        (work / state.TIMING_FILE).read_text(encoding="utf-8"))["requests"]}
    assert rows["req-1"]["validation"]["accepted"] is False
    assert rows["req-1"]["validation"]["problems"] == ["Section 3 is empty."]
    assert rows["req-2"]["validation"] == {"accepted": True, "problems": [],
                                           "observed_at": rows["req-2"]["validation"]["observed_at"]}
    state.validate_requests(tmp_path, [], True)        # a no-op, never an error


def test_timing_summary_reports_observed_durations_only(tmp_path):
    _work(tmp_path)
    state.issue_request(tmp_path, _request(), 1)
    state.issue_request(tmp_path, _request("req-2", stage="slides"), 1, mode="repair")
    state.event(tmp_path, "req-1", "started", observed_at="2026-10-14T10:00:00Z")
    state.event(tmp_path, "req-1", "completed", observed_at="2026-10-14T10:01:30Z",
                actual_model="opus", output_tokens=42)
    state.record_duration(tmp_path, "extract", 1.5, "ok")
    summary = state.timing_summary(tmp_path)
    assert summary["status"] == "available"
    first, second = summary["requests"]
    assert first["worker_seconds"] == 90.0
    assert first["queue_seconds"] is None
    assert first["actual_model"] == "opus" and first["output_tokens"] == 42
    assert first["input_tokens"] is None
    assert "events" not in first
    assert second["worker_seconds"] is None and second["started_at"] is None
    assert second["mode"] == "repair"
    assert summary["stages"] == [{"stage": "extract", "recorded_at": summary["stages"][0]["recorded_at"],
                                  "duration_seconds": 1.5, "outcome": "ok"}]


def test_timing_summary_is_unavailable_without_a_record(tmp_path):
    _work(tmp_path)
    summary = state.timing_summary(tmp_path)
    assert summary["status"] == "unavailable"
    assert summary["requests"] == [] and summary["stages"] == []


def test_corrupt_timing_record_is_preserved_and_reported(tmp_path):
    work = _work(tmp_path)
    (work / state.TIMING_FILE).write_text('{"version": 1, "requests": "no"}')
    assert state.issue_request(tmp_path, _request(), 1) is False
    assert (work / state.TIMING_FILE).read_text() == '{"version": 1, "requests": "no"}'
    assert state.timing_summary(tmp_path)["status"] == "unavailable"
    assert "invalid" in (work / "timing_error.txt").read_text(encoding="utf-8")
