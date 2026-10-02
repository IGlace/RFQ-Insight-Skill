#!/usr/bin/env python3
"""Record host-reported model execution without pretending to measure usage.

Call from the coordinator after completed model work. The requested model comes
from the routing policy. Omit --actual-model unless the host reports it.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile

from stage_request import ROLES, route


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder")
    parser.add_argument("--host", required=True, choices=("claude", "codex"))
    parser.add_argument("--stage", required=True, choices=ROLES)
    parser.add_argument("--mode", required=True, choices=("isolated", "in-thread"))
    parser.add_argument("--actual-model")
    parser.add_argument("--actual-reasoning-effort", choices=("low", "medium", "high"))
    parser.add_argument("--image-id")
    parser.add_argument("--note", default="")
    args = parser.parse_args(argv)
    work = Path(args.folder).expanduser().resolve() / "output" / ".work"
    path = work / "execution.json"
    temporary = None
    try:
        if not work.is_dir():
            raise ValueError("No RFQ checkpoints exist here yet.")
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"stages": []}
        if not isinstance(data, dict) or not isinstance(data.get("stages"), list):
            raise ValueError("The execution history is not a valid record; it was preserved.")
        requested = route(args.host, args.stage)
        data["stages"].append({
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "host": args.host, "stage": args.stage, "mode": args.mode,
            "requested_model": requested["model"],
            "requested_reasoning_effort": requested.get("reasoning_effort"),
            "actual_model": args.actual_model,
            "actual_reasoning_effort": args.actual_reasoning_effort,
            "image_id": args.image_id, "note": args.note,
        })
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=work,
                                         prefix="execution-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"Could not record model execution: {exc}", file=sys.stderr)
        return 2
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    print(f"Recorded {args.host} {args.stage} execution.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
