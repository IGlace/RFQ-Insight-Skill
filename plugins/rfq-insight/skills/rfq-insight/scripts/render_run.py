#!/usr/bin/env python3
"""Re-render a saved run report — the fast loop for deck/layout work.

A full pipeline run costs two Opus-class calls plus the verifier and takes
minutes. When you are only changing rfq/renderer.py, none of that has to
happen again: the slide plan is already stored in the run report, so this
script replays STEP 3 alone.

    python render_run.py <name>_RFQ_Analysis.json [preview.pptx]

Takes report["slidePlan"] — which finalize.py stores POST-sanitizer, i.e. the
exact dict that was handed to the renderer — re-validates it against
rfq.schema.SlidePlan, tightens it the way finalize.py does, and calls
rfq.renderer.render_to_bytes. Same input, same code path, no network. If the
output filename is omitted it is derived from the report (<report>.pptx).

Also accepts a bare slide-plan JSON file (a dict with "questions"), so you can
hand-edit a plan to probe a layout edge case without a corpus at all.
"""

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)                  # scripts/ -> import rfq

from rfq.renderer import render_to_bytes       # noqa: E402
from rfq.schema import SlidePlan, tighten_plan  # noqa: E402


def load_plan(path: str) -> dict:
    """Pull the slide plan out of a run report, or accept a bare plan."""
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    plan = payload.get("slidePlan", payload)
    if not isinstance(plan, dict) or "questions" not in plan:
        print(f"No slide plan in {path} — expected a run report with "
              f'"slidePlan", or a plan with "questions".')
        sys.exit(1)
    return plan


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__.strip())
        sys.exit(2)
    report_path = sys.argv[1]
    if not os.path.exists(report_path):
        print(f"Not found: {report_path}")
        sys.exit(1)

    plan = load_plan(report_path)
    # Re-validate: a hand-edited plan should fail here, not halfway through
    # the renderer, and this is the same gate finalize.py applies.
    #
    # Then tighten, for the same reason finalize.py tightens again right
    # before rendering: model_dump() makes every UNSET optional explicit as
    # None, and the renderer's d.get(key, default) only falls back for an
    # ABSENT key, so an explicit None reaches python-pptx and crashes. Any
    # report whose plan left an optional unset - a collab slide with no
    # `hub`, an ownership slide with no `customerAbbr` - would fail here
    # while rendering perfectly inside the pipeline.
    plan = tighten_plan(SlidePlan.model_validate(plan).model_dump())

    if len(sys.argv) > 2:
        out_path = sys.argv[2]
    else:
        base = os.path.splitext(report_path)[0]
        out_path = (base[:-4] if base.endswith("_run") else base) + ".pptx"

    out_dir = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(out_dir, exist_ok=True)
    deck = render_to_bytes(plan)
    with open(out_path, "wb") as fh:
        fh.write(deck)

    slides = sum(len(q.get("slides", [])) for q in plan.get("questions", []))
    print(f"Rendered {len(plan.get('questions', []))} sections / {slides} "
          f"content slides -> {out_path} ({len(deck):,} bytes)")


if __name__ == "__main__":
    main()
