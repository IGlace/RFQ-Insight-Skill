#!/usr/bin/env python3
"""Persist the next RFQ stage and preserve old model outputs before reruns.

    python workflow_state.py FOLDER --resume
    python workflow_state.py FOLDER --start analysis
    python workflow_state.py FOLDER --complete analysis

Start is required before each stage; complete follows successful validation.
Neither command removes checkpoints. Old model outputs are archived so a fresh
worker never has to read an earlier answer merely to overwrite its file.
"""

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid

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
        os.replace(temporary, work / "progress.json")
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _pending(work):
    data = json.loads((work / "progress.json").read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("version") != 1 or
            data.get("pending") not in (*STAGES, "done")):
        raise ValueError("The progress record is invalid; choose an explicit stage to restart.")
    return data["pending"]


def start(folder, stage):
    if stage not in STAGES:
        raise ValueError(f"Unknown stage: {stage}")
    work = _work(folder)
    # Save first: a crash during archival must still resume the requested stage.
    _save(work, stage)
    paths = [work / name for name in MODEL_OUTPUTS.get(stage, ())]
    if stage == "figures":
        paths.extend(path for path in (work / "image_text").glob("*.txt")
                     if not path.read_text(encoding="utf-8").strip())
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
        path.replace(target)
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--resume", action="store_true")
    action.add_argument("--start", choices=STAGES)
    action.add_argument("--complete", choices=STAGES)
    args = parser.parse_args(argv)
    try:
        if args.start:
            result = start(args.folder, args.start)
        elif args.complete:
            result = complete(args.folder, args.complete)
        else:
            result = resume(args.folder)
    except (ValueError, OSError) as exc:
        print(f"Could not update or read RFQ progress: {exc}", file=sys.stderr)
        return 2
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
