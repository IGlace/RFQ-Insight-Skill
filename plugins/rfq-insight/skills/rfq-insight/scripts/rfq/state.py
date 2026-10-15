"""Workflow progress, checkpoint archival, execution history and atomic writes.

Start precedes each stage; complete follows successful validation. Old model
outputs are archived so fresh workers never need to read earlier answers.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import time
import uuid
import math
import re

ATTEMPTS_FILE = "attempts.json"
TIMING_FILE = "timing.json"

REPLACE_ATTEMPTS = 10
REPLACE_DELAY = 0.05      # seconds; grows linearly per attempt (max ~2.3 s total)


def replace_with_retry(src, dst) -> None:
    """os.replace(src, dst), retried while Windows reports the target or the
    source as locked. Antivirus and the search indexer briefly hold files
    that were just written; a run must not fail on that. Any other error,
    or a lock that outlasts every attempt, is raised unchanged."""
    for attempt in range(1, REPLACE_ATTEMPTS + 1):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS:
                raise
            time.sleep(REPLACE_DELAY * attempt)


STAGES = ("extract", "figures", "analysis", "verification", "slides", "finalize", "evaluate")
MODEL_OUTPUTS = {
    "analysis": ("analysis.json",),
    "verification": ("verdicts.json", "verification.json"),
    "slides": ("slide_plan.json",),
}


def _work(folder):
    folder = Path(folder).expanduser().resolve()
    if not folder.is_dir():
        raise ValueError(f"I couldn't find that folder: {folder}")
    return folder / "output" / ".work"


def _save(work, pending):
    work.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=work,
                                         prefix="progress-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump({"version": 1, "pending": pending}, handle)
            handle.write("\n")
        replace_with_retry(temporary, work / "progress.json")
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _pending(work):
    data = json.loads((work / "progress.json").read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("version") != 1 or
            data.get("pending") not in (*STAGES, "done")):
        raise ValueError("The progress record is invalid; choose an explicit stage to restart.")
    return data["pending"]


def _incomplete_figure_outputs(work, figs=None):
    """The transcription and app metadata of every figure result that is
    not reusable. figures.figure_reusable is the one rule for a complete
    result, so what is archived here is exactly what the next request
    sends again."""
    from . import figures
    text_dir = work / "image_text"
    stems = ({p.stem for p in text_dir.glob("*.txt")} |
             {p.name[:-10] for p in text_dir.glob("*.meta.json")})
    found = []
    for stem in sorted(stems):
        if not figures.figure_reusable(work, stem, figs):
            found.extend(p for p in (figures.figure_output(work, stem),
                                     figures.figure_metadata(work, stem))
                         if p.exists())
    return found


def start(folder, stage, figs=None):
    """Make `stage` pending and archive its previous outputs. `figs` is the
    calling figure stage's figures.FigureSet, reused for its hashes."""
    if stage not in STAGES:
        raise ValueError(f"Unknown stage: {stage}")
    work = _work(folder)
    # Save first: a crash during archival must still resume the requested stage.
    _save(work, stage)
    paths = [work / name for name in MODEL_OUTPUTS.get(stage, ())]
    if STAGES.index(stage) <= STAGES.index("verification"):
        from . import verification
        paths.extend(verification.archive_paths(work))
        paths = list(dict.fromkeys(paths))
    if stage == "figures":
        from . import figures
        figs = figures.FigureSet(work) if figs is None else figs
        figures.accept_figure_outputs(work, figures._figure_receipts(work), figs)
        paths.extend(_incomplete_figure_outputs(work, figs))
        # The retired per-figure classification (<id>.json, before figures
        # wrote one .txt each): archived once, nothing reads it any more.
        paths.extend(path for path in sorted((work / "image_text").glob("*.json"))
                     if not path.name.endswith(".meta.json"))
    elif stage == "extract":
        from . import figures
        figures.invalidate_figure_requests(work)
    history = work / "history" / uuid.uuid4().hex
    for path in paths:
        if not path.exists():
            continue
        target = history / path.relative_to(work)
        if (not path.is_file() or path.is_symlink() or
                not path.resolve().is_relative_to(work.resolve()) or
                not target.resolve().is_relative_to(work.resolve())):
            raise ValueError("A checkpoint path is not a regular file inside the work directory.")
        target.parent.mkdir(parents=True, exist_ok=True)
        replace_with_retry(path, target)
    return stage


def complete(folder, stage):
    if stage not in STAGES:
        raise ValueError(f"Unknown stage: {stage}")
    work = _work(folder)
    if _pending(work) != stage:
        raise ValueError(f"Cannot complete {stage}: it is not the pending stage.")
    index = STAGES.index(stage) + 1
    pending = STAGES[index] if index < len(STAGES) else "done"
    _save(work, pending)
    return pending


def resume(folder):
    work = _work(folder)
    if (work / "progress.json").exists():
        return _pending(work)
    # Legacy runs have no progress marker. Preserve their chronological
    # inference, with deterministic stage ordering when timestamps tie.
    legacy = (("corpus.json", "figures"), ("images.json", "figures"),
              ("corpus.txt", "analysis"), ("analysis.json", "verification"),
              ("claims.json", "verification"), ("verification.json", "slides"),
              ("plan_input.json", "slides"), ("slide_plan.json", "finalize"))
    found = [(path.stat().st_mtime_ns, rank, stage)
             for rank, (name, stage) in enumerate(legacy)
             if (path := work / name).is_file()]
    return max(found)[2] if found else "extract"


def record(folder, host, stage, mode, actual_model=None, actual_effort=None,
           image_id=None, note=""):
    from .workers import route
    """Append one completed model stage to .work/execution.json.
    Raises ValueError / OSError / KeyError / TypeError on failure."""
    work = Path(folder).expanduser().resolve() / "output" / ".work"
    path = work / "execution.json"
    temporary = None
    try:
        if not work.is_dir():
            raise ValueError("No RFQ checkpoints exist here yet.")
        data = (json.loads(path.read_text(encoding="utf-8"))
                if path.exists() else {"stages": []})
        if not isinstance(data, dict) or not isinstance(data.get("stages"), list):
            raise ValueError("The execution history is not a valid record; "
                             "it was preserved.")
        requested = route(host, stage)
        data["stages"].append({
            "recorded_at": datetime.now(timezone.utc).isoformat(
                timespec="seconds"),
            "host": host, "stage": stage, "mode": mode,
            "requested_model": requested["model"],
            "requested_reasoning_effort": requested.get("reasoning_effort"),
            "actual_model": actual_model,
            "actual_reasoning_effort": actual_effort,
            "image_id": image_id, "note": note,
        })
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=work,
                                         prefix="execution-", suffix=".tmp",
                                         delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        replace_with_retry(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _timestamp(value=None):
    """Require a timezone-aware host observation, or use coordinator receipt time."""
    if value is None:
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ValueError("The observation timestamp must include a timezone.") from None
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _stored_timestamp(value):
    if not isinstance(value, str) or not value:
        raise ValueError("Missing observation timestamp.")
    return _timestamp(value)


def _token_count(value):
    if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
        raise ValueError("Observed tokens must be nonnegative integers.")


def _timing_data(work, create=False):
    path = work / TIMING_FILE
    if not path.exists():
        if create:
            return {"version": 1, "requests": [], "stages": []}
        raise ValueError("No timing record exists.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(data, dict) or data.get("version") != 1 or
                not isinstance(data.get("requests"), list) or
                not isinstance(data.get("stages"), list)):
            raise ValueError()
        ids = set()
        for row in data["requests"]:
            if (not isinstance(row, dict) or not isinstance(row.get("request_id"), str)
                    or not row["request_id"] or row["request_id"] in ids
                    or row.get("stage") not in (*STAGES, "followup")
                    or type(row.get("attempt")) is not int or row["attempt"] < 1
                    or row.get("host") not in ("claude", "codex")
                    or row.get("mode") not in ("dispatch", "repair", "issued")
                    or not isinstance(row.get("requested_model"), str)
                    or not isinstance(row.get("outputs"), list)
                    or not all(isinstance(p, str) for p in row["outputs"])
                    or not isinstance(row.get("image_ids"), list)
                    or not isinstance(row.get("events"), list)):
                raise ValueError()
            ids.add(row["request_id"])
            _stored_timestamp(row["issued_at"])
            for key in ("input_bytes", "instruction_bytes", "message_bytes"):
                _token_count(row.get(key))
            sizes = row.get("input_sizes")
            if sizes is not None:
                if not isinstance(sizes, list):
                    raise ValueError()
                for item in sizes:
                    if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                        raise ValueError()
                    if type(item.get("bytes")) is not int:
                        raise ValueError()
                    _token_count(item["bytes"])
                if row.get("input_bytes") != sum(item["bytes"] for item in sizes):
                    raise ValueError()
            identity = row.get("corpus_identity")
            if identity is not None and (not isinstance(identity, dict) or
                    not isinstance(identity.get("path"), str) or
                    not isinstance(identity.get("sha256"), str) or
                    not re.fullmatch(r"[0-9a-f]{64}", identity["sha256"])):
                raise ValueError()
            previous = None
            for event_row in row["events"]:
                if not isinstance(event_row, dict):
                    raise ValueError()
                kind = event_row["event"]
                if kind not in ("started", "completed", "failed") or previous in ("completed", "failed"):
                    raise ValueError()
                if previous == "started" and kind == "started":
                    raise ValueError()
                current = _stored_timestamp(event_row["observed_at"])
                if event_row.get("time_source") not in ("host", "coordinator_observation"):
                    raise ValueError()
                for key in ("input_tokens", "output_tokens"):
                    _token_count(event_row.get(key))
                if previous is not None and current < last_time:
                    raise ValueError()
                previous, last_time = kind, current
            validation = row.get("validation")
            if validation is not None and (not isinstance(validation, dict) or
                    not isinstance(validation.get("accepted"), bool)):
                raise ValueError()
            if validation is not None:
                _stored_timestamp(validation["observed_at"])
                if not isinstance(validation.get("problems"), list):
                    raise ValueError()
        for row in data["stages"]:
            if (not isinstance(row, dict) or row.get("stage") not in (*STAGES, "done")
                    or not isinstance(row.get("duration_seconds"), (float, int))
                    or isinstance(row.get("duration_seconds"), bool)
                    or not math.isfinite(row["duration_seconds"]) or row["duration_seconds"] < 0):
                raise ValueError()
        return data
    except (ValueError, KeyError, TypeError, OverflowError, RecursionError):
        raise ValueError("The timing record is invalid; it was preserved.") from None


def _save_timing(work, data):
    work.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=work,
                                         prefix="timing-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        replace_with_retry(temporary, work / TIMING_FILE)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def timing_warning(folder, exc):
    """Best-effort diagnostics; preserve existing timing evidence unchanged."""
    try:
        work = _work(folder)
        work.mkdir(parents=True, exist_ok=True)
        with (work / "timing_error.txt").open("a", encoding="utf-8") as handle:
            handle.write(f"{_timestamp()}: {exc}\n")
    except (OSError, ValueError):
        pass


def issue_request(folder, request, attempt, mode="dispatch"):
    """Coordinator records an issued dispatch/repair; this is not worker start."""
    try:
        work = _work(folder)
        data = _timing_data(work, create=True)
        if any(r["request_id"] == request["request_id"] for r in data["requests"]):
            raise ValueError("The request ID was already issued.")
        data["requests"].append({
            "request_id": request["request_id"], "issued_at": _timestamp(),
            "host": request["host"], "stage": request["stage"], "attempt": attempt,
            "mode": mode, "requested_model": request["model"],
            "requested_reasoning_effort": request.get("reasoning_effort"),
            "corpus_identity": request.get("corpus_identity"),
            "input_bytes": request.get("input_bytes"),
            "input_sizes": request.get("input_sizes"),
            "instruction_bytes": request.get("instruction_bytes"),
            "message_bytes": request.get("message_bytes"),
            "image_ids": request.get("image_ids", []), "outputs": request["outputs"],
            "claim_ids": request.get("claim_ids", []),
            "partition_id": request.get("partition_id"),
            "partition_identity": request.get("partition_identity"),
            "events": [], "validation": None,
            "telemetry_error": request.get("telemetry_error"),
        })
        _save_timing(work, data)
        return True
    except (OSError, ValueError, KeyError, TypeError) as exc:
        timing_warning(folder, exc)
        return False


def event(folder, request_id, kind, observed_at=None, actual_model=None,
          actual_effort=None, input_tokens=None, output_tokens=None, note=""):
    """Record only coordinator/host observations; never validate an output."""
    if kind not in ("started", "completed", "failed"):
        raise ValueError("Unknown lifecycle event.")
    stamp = _timestamp(observed_at)
    for value in (input_tokens, output_tokens):
        _token_count(value)
    work = _work(folder)
    data = _timing_data(work)
    row = next((r for r in data["requests"] if r["request_id"] == request_id), None)
    if row is None:
        raise ValueError(f"Unknown request ID: {request_id}")
    events = row["events"]
    if events and (events[-1]["event"] in ("completed", "failed") or kind == "started"):
        raise ValueError("The event violates the request lifecycle order.")
    if events and stamp < _timestamp(events[-1]["observed_at"]):
        raise ValueError("The observation timestamp precedes the previous event.")
    events.append({"event": kind, "observed_at": stamp,
                   "time_source": "host" if observed_at is not None else "coordinator_observation",
                   "actual_model": actual_model, "actual_reasoning_effort": actual_effort,
                   "input_tokens": input_tokens, "output_tokens": output_tokens, "note": note})
    _save_timing(work, data)
    return {"status": "recorded", "request_id": request_id, "event": kind}


def observe_terminal(folder, completed=(), failed=(), actual_model=None,
                     actual_effort=None):
    """`next --completed/--failed`: one terminal event per request id, by
    the same path as `rfq_run.py event`, observed now. Telemetry never
    stops a run: an event that cannot be recorded (an unknown id, a second
    terminal event) is noted in timing_error.txt and reported as
    unavailable, and the caller advances anyway."""
    recorded = []
    for kind, request_ids in (("completed", completed), ("failed", failed)):
        for request_id in request_ids or ():
            try:
                recorded.append(event(folder, request_id, kind,
                                      actual_model=actual_model,
                                      actual_effort=actual_effort))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                timing_warning(folder, exc)
                recorded.append({"status": "unavailable",
                                 "request_id": request_id, "event": kind,
                                 "reason": str(exc)})
    return recorded


def validate_requests(folder, request_ids, accepted, problems=()):
    """Append coordinator validation separately from host completion."""
    if not request_ids:
        return
    try:
        work = _work(folder)
        data = _timing_data(work)
        for row in data["requests"]:
            if row["request_id"] in request_ids and row["validation"] is None:
                row["validation"] = {"accepted": bool(accepted), "observed_at": _timestamp(),
                                     "problems": list(problems)}
        _save_timing(work, data)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        timing_warning(folder, exc)


def record_duration(folder, stage, seconds, outcome):
    """Monotonic time spent inside one deterministic Python stage handler."""
    try:
        work = _work(folder)
        data = _timing_data(work, create=True)
        data["stages"].append({"stage": stage, "recorded_at": _timestamp(),
                               "duration_seconds": seconds, "outcome": outcome})
        _save_timing(work, data)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        timing_warning(folder, exc)


def timing_summary(folder):
    """Inspection only; null means unobserved, never an estimate."""
    try:
        data = _timing_data(_work(folder))
    except (OSError, ValueError) as exc:
        return {"status": "unavailable", "reason": str(exc), "requests": [], "stages": []}
    rows = []
    for request in data["requests"]:
        started = next((e for e in request["events"] if e["event"] == "started"), None)
        terminal = next((e for e in request["events"] if e["event"] in ("completed", "failed")), None)
        duration = ((datetime.fromisoformat(_stored_timestamp(terminal["observed_at"])) -
                     datetime.fromisoformat(_stored_timestamp(started["observed_at"]))).total_seconds()
                    if started and terminal else None)
        observed = {}
        for item in request["events"]:
            observed.update({k: v for k, v in item.items() if v is not None})
        rows.append({**{k: v for k, v in request.items() if k != "events"},
                     "started_at": started["observed_at"] if started else None,
                     "finished_at": terminal["observed_at"] if terminal else None,
                     "worker_seconds": duration, "queue_seconds": None,
                     "actual_model": observed.get("actual_model"),
                     "actual_reasoning_effort": observed.get("actual_reasoning_effort"),
                     "input_tokens": observed.get("input_tokens"),
                     "output_tokens": observed.get("output_tokens")})
    return {"status": "available", "requests": rows, "stages": data["stages"],
            "intervals": {"duration_seconds": "Python stage-handler wall time (monotonic)",
                          "worker_seconds": "Between observed started and terminal events",
                          "queue_seconds": "Unavailable: no queue admission observation"}}
