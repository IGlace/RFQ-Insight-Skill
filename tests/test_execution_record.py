"""Reports distinguish requested models from host-observed execution."""

import json

import record_execution as execution
import finalize
from test_finalize import _analysis, _corpus, _draft_plan


def test_execution_record_keeps_prior_host_history_and_unknown_actual_model(tmp_path):
    work = tmp_path / "output" / ".work"
    work.mkdir(parents=True)
    assert execution.main([str(tmp_path), "--host", "claude", "--stage", "analysis",
                           "--mode", "isolated"]) == 0
    assert execution.main([str(tmp_path), "--host", "codex", "--stage", "verification",
                           "--mode", "in-thread", "--actual-model", "gpt-6-sol",
                           "--note", "Fresh workers unavailable"]) == 0
    records = json.loads((work / "execution.json").read_text())["stages"]
    assert [r["host"] for r in records] == ["claude", "codex"]
    assert records[0]["requested_model"] == "opus"
    assert records[0]["actual_model"] is None
    assert records[1]["mode"] == "in-thread"


def test_finalizer_adds_optional_execution_without_changing_legacy_shape():
    _, _, legacy = finalize.finalize(_corpus(), _analysis(), _draft_plan())
    assert "execution" not in legacy["run"]
    audit = {"stages": [{"host": "codex", "actual_model": None}]}
    _, _, report = finalize.finalize(_corpus(), _analysis(), _draft_plan(), execution=audit)
    assert report["run"]["execution"] == audit
    assert report["run"]["usage"] == legacy["run"]["usage"]


def test_corrupt_execution_history_is_not_overwritten(tmp_path):
    work = tmp_path / "output" / ".work"
    work.mkdir(parents=True)
    path = work / "execution.json"
    path.write_text("broken record")
    assert execution.main([str(tmp_path), "--host", "codex", "--stage", "analysis",
                           "--mode", "isolated"]) == 2
    assert path.read_text() == "broken record"
