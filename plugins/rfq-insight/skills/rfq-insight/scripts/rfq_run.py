#!/usr/bin/env python3
"""RFQ Insight pipeline runner - the coordinator's only script in a run.

    python rfq_run.py next "C:/RFQs/Acme V6" --host claude
        [--project NAME] [--completed REQUEST_ID ...] [--failed REQUEST_ID ...]
        [--actual-model ID] [--actual-reasoning-effort low|medium|high]
        [--until STAGE] [--restart STAGE]

Prints ONE JSON object whose "status" is dispatch, repair, done, stopped or
blocked (see rfq/pipeline.py). --completed / --failed (repeatable) first
record each listed worker's terminal observation, as `event` would, then
the run advances in the same call.

Follow-up mode, after a run (see rfq/followups.py):

    python rfq_run.py ask FOLDER --host claude --question TEXT
    python rfq_run.py answer FOLDER --host claude [--actual-model ID]
        [--actual-reasoning-effort low|medium|high]
    python rfq_run.py add-followups FOLDER [--ids N [N ...]]

Comparison of two finished runs (see rfq/comparison.py; no model worker):

    python rfq_run.py compare FOLDER_A FOLDER_B

`ask` returns dispatch, stale or blocked; `answer` returns answered, repair
or blocked; `add-followups` and `compare` return done or blocked. Exit 0 for every
status; exit 2 only when the runner itself fails, with one line on stderr
and nothing on stdout.
"""

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from rfq.state import STAGES        # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Run the RFQ Insight pipeline.",
        epilog="Inspection commands: lookup, validate, evaluate, render. "
               "Use debug --help for internal operations.")
    sub = ap.add_subparsers(dest="command", required=True)

    nxt = sub.add_parser(
        "next", help="run every deterministic step up to the next model stage")
    nxt.add_argument("folder", help="the folder holding the RFQ package")
    nxt.add_argument("--host", required=True, choices=("claude", "codex"))
    nxt.add_argument("--project",
                     help="display name for a new run's cover/footer "
                          "(not the deck's file name); ignored once the "
                          "folder already has one saved")
    nxt.add_argument("--completed", action="append", default=[],
                     metavar="REQUEST_ID",
                     help="a worker of this request returned its result "
                          "(repeat for each)")
    nxt.add_argument("--failed", action="append", default=[],
                     metavar="REQUEST_ID",
                     help="a worker of this request ended without a result "
                          "(repeat for each)")
    nxt.add_argument("--actual-model",
                     help="model the host reported for the last worker(s)")
    nxt.add_argument("--actual-reasoning-effort",
                     choices=("low", "medium", "high"))
    nxt.add_argument("--until", choices=STAGES,
                     help="stop once this stage is complete")
    nxt.add_argument("--restart", choices=STAGES,
                     help="run this stage again (and every later one)")

    p_ask = sub.add_parser(
        "ask", help="answer a follow-up question from the saved corpus")
    p_ask.add_argument("folder", help="the folder holding the RFQ package")
    p_ask.add_argument("--host", required=True, choices=("claude", "codex"))
    p_ask.add_argument("--question", required=True)

    p_answer = sub.add_parser(
        "answer", help="validate and store the follow-up answer")
    p_answer.add_argument("folder", help="the folder holding the RFQ package")
    p_answer.add_argument("--host", required=True, choices=("claude", "codex"))
    p_answer.add_argument("--actual-model",
                          help="model the host reported for the worker")
    p_answer.add_argument("--actual-reasoning-effort",
                          choices=("low", "medium", "high"))

    p_add = sub.add_parser(
        "add-followups", help="new deck with the follow-up answers added")
    p_add.add_argument("folder", help="the folder holding the RFQ package")
    p_add.add_argument("--ids", type=int, nargs="+",
                       help="add these follow-up answers; answers already in "
                            "the latest deck stay (default: add every answer "
                            "not yet in the latest deck)")

    p_compare = sub.add_parser(
        "compare", help="compare the last finished runs of two RFQ folders")
    p_compare.add_argument("folder_a", help="the first analysed RFQ folder")
    p_compare.add_argument("folder_b", help="the second analysed RFQ folder")
    p_event = sub.add_parser("event", help="record coordinator-observed worker lifecycle")
    p_event.add_argument("folder")
    p_event.add_argument("--request-id", required=True)
    p_event.add_argument("--event", required=True, choices=("started", "completed", "failed"))
    p_event.add_argument("--observed-at", help="host timestamp with timezone; omit to record observation receipt")
    p_event.add_argument("--actual-model")
    p_event.add_argument("--actual-reasoning-effort", choices=("low", "medium", "high"))
    p_event.add_argument("--input-tokens", type=int)
    p_event.add_argument("--output-tokens", type=int)
    p_event.add_argument("--note", default="")
    p_timing = sub.add_parser("timing", help="inspect timing evidence without changing checkpoints")
    p_timing.add_argument("folder")
    return ap


def workflow_main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
    except (ValueError, OSError):
        pass
    try:
        if args.command == "next":
            from rfq import pipeline, state
            # Telemetry first, never a blocker: a bad id is noted in
            # timing_error.txt and the run still advances.
            state.observe_terminal(args.folder, args.completed, args.failed,
                                   actual_model=args.actual_model,
                                   actual_effort=args.actual_reasoning_effort)
            result = pipeline.advance(
                args.folder, args.host, project=args.project,
                actual_model=args.actual_model,
                actual_effort=args.actual_reasoning_effort, until=args.until,
                restart=args.restart)
        elif args.command == "ask":
            from rfq import followups
            result = followups.ask(args.folder, args.host, args.question)
        elif args.command == "answer":
            from rfq import followups
            result = followups.answer(args.folder, args.host,
                                          args.actual_model,
                                          args.actual_reasoning_effort)
        elif args.command == "add-followups":
            from rfq import followups
            result = followups.add_followups(args.folder, args.ids)
        elif args.command == "compare":
            from rfq.comparison import run_compare
            result = run_compare(args.folder_a, args.folder_b)
        elif args.command == "event":
            from rfq import state
            try:
                result = state.event(args.folder, args.request_id, args.event,
                    observed_at=args.observed_at, actual_model=args.actual_model,
                    actual_effort=args.actual_reasoning_effort,
                    input_tokens=args.input_tokens, output_tokens=args.output_tokens, note=args.note)
            except OSError as exc:
                state.timing_warning(args.folder, exc)
                result = {"status": "unavailable", "reason": str(exc)}
        elif args.command == "timing":
            from rfq import state
            result = state.timing_summary(args.folder)
    except Exception as exc:    # never print a partial or misleading JSON
        message = " ".join(str(exc).split())
        print(f"The RFQ Insight runner failed: {type(exc).__name__}: {message}",
              file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cli_state(argv=None):
    from rfq import state

    parser = argparse.ArgumentParser(description='Persist the next RFQ stage and preserve old model outputs before reruns.\n\n    python rfq_run.py debug state FOLDER --resume\n    python rfq_run.py debug state FOLDER --start analysis\n    python rfq_run.py debug state FOLDER --complete analysis\n\nStart is required before each stage; complete follows successful validation.\nNeither command removes checkpoints. Old model outputs are archived so a fresh\nworker never has to read an earlier answer merely to overwrite its file.')
    parser.add_argument("folder")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--resume", action="store_true")
    action.add_argument("--start", choices=STAGES)
    action.add_argument("--complete", choices=STAGES)
    args = parser.parse_args(argv)
    try:
        if args.start:
            result = state.start(args.folder, args.start)
        elif args.complete:
            result = state.complete(args.folder, args.complete)
        else:
            result = state.resume(args.folder)
    except (ValueError, OSError) as exc:
        print(f"Could not update or read RFQ progress: {exc}", file=sys.stderr)
        return 2
    print(result)
    return 0


def cli_record(argv=None):
    from rfq import state, workers

    parser = argparse.ArgumentParser(description='Record host-reported model execution without pretending to measure usage.\n\nCall from the coordinator after completed model work. The requested model comes\nfrom the routing policy. Omit --actual-model unless the host reports it.')
    parser.add_argument("folder")
    parser.add_argument("--host", required=True, choices=("claude", "codex"))
    parser.add_argument("--stage", required=True, choices=workers.ROLES)
    parser.add_argument("--mode", required=True, choices=("isolated", "in-thread"))
    parser.add_argument("--actual-model")
    parser.add_argument("--actual-reasoning-effort", choices=("low", "medium", "high"))
    parser.add_argument("--image-id")
    parser.add_argument("--note", default="")
    args = parser.parse_args(argv)
    try:
        state.record(args.folder, args.host, args.stage, args.mode,
                     actual_model=args.actual_model,
                     actual_effort=args.actual_reasoning_effort,
                     image_id=args.image_id, note=args.note)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"Could not record model execution: {exc}", file=sys.stderr)
        return 2
    print(f"Recorded {args.host} {args.stage} execution.")
    return 0


def cli_request(argv=None):
    from rfq import workers

    parser = argparse.ArgumentParser(description='Prepare bounded native-agent work; never call a model or change checkpoints.\n\n    python rfq_run.py debug request FOLDER --host codex --stage verification\n    python rfq_run.py debug request FOLDER --host claude --stage figures --image-id ID\n\nThe host adapter consumes the JSON request and dispatches its `message` using\nthe specified model. Only the coordinator runs validation and subsequent stages.')
    parser.add_argument("folder")
    parser.add_argument("--host", required=True, choices=("codex", "claude"))
    parser.add_argument("--stage", required=True, choices=tuple(workers.PROMPTS))
    parser.add_argument("--image-id")
    args = parser.parse_args(argv)
    try:
        result = workers.prepare(args.folder, args.host, args.stage, args.image_id)
        from rfq import state
        state.issue_request(args.folder, result, 1, mode="issued")
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cli_extract(argv=None) -> int:
    from rfq.corpus import run_extraction, summary_lines

    ap = argparse.ArgumentParser(description="Extract an RFQ folder.")
    ap.add_argument("folder", help="the folder holding the RFQ package")
    ap.add_argument("--project", default=None,
                    help="opportunity name (defaults to the folder name)")
    args = ap.parse_args(argv)

    folder = os.path.abspath(args.folder)
    if not os.path.isdir(folder):
        print("I couldn't find that folder - check the path and try again.",
              file=sys.stderr)
        return 1

    corpus, manifest = run_extraction(folder, args.project)
    for line in summary_lines(corpus, manifest):
        print(line)

    if corpus["extraction"]["parsed"] == 0:
        print("That folder has nothing I can read. I handle PDF, Word, "
              "Excel, PowerPoint, text, CSV and images.", file=sys.stderr)
        return 1
    return 0


def cli_corpus(argv=None) -> int:
    from rfq.corpus import format_corpus

    ap = argparse.ArgumentParser(
        description="Print the corpus as delimited === FILE: === blocks.")
    ap.add_argument("folder", help="the folder holding the RFQ package")
    ap.add_argument("--out", default=None,
                    help="write to this file instead of printing")
    args = ap.parse_args(argv)

    corpus_path = os.path.join(os.path.abspath(args.folder), "output",
                               ".work", "corpus.json")
    if not os.path.exists(corpus_path):
        print("I haven't read the documents yet - there's nothing to show.",
              file=sys.stderr)
        return 2

    with open(corpus_path, encoding="utf-8") as fh:
        corpus = json.load(fh)
    text = format_corpus(corpus.get("filesContents", []))

    if args.out:
        out_path = os.path.abspath(args.out)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"Wrote {len(corpus.get('filesContents', []))} document(s), "
              f"{len(text):,} characters, to {out_path}")
    else:
        print(text)
    return 0


def cli_merge(argv=None) -> int:
    from rfq.figures import run_merge

    ap = argparse.ArgumentParser(description="Fold transcriptions into the corpus.")
    ap.add_argument("folder", help="the folder holding the RFQ package")
    args = ap.parse_args(argv)

    result = run_merge(args.folder)
    if result is None:
        print("Nothing to add - I haven't read the documents yet.",
              file=sys.stderr)
        return 0

    print(f"Added what {result['added']} picture(s) show to the text.")
    if result["missing"]:
        print(f"{len(result['missing'])} picture(s) had nothing saved and "
              f"are marked as unread in the report.")
    if result["record"]["images_unresolved"]:
        print(f"{len(result['record']['images_unresolved'])} picture(s) "
              f"couldn't be matched back to the document they came from; "
              f"the report lists them.")
    return 0


def cli_claims(argv=None) -> int:
    from rfq.verification import write_claims

    ap = argparse.ArgumentParser(description="Harvest claims to verify.")
    ap.add_argument("folder", help="the folder holding the RFQ package")
    args = ap.parse_args(argv)

    work = os.path.join(os.path.abspath(args.folder), "output", ".work")
    analysis_path = os.path.join(work, "analysis.json")
    if not os.path.exists(analysis_path):
        # A resume lands here often. A bare FileNotFoundError traceback
        # tells a salesperson nothing and looks like a crash.
        print("A checkpoint is missing - I haven't got an analysis to "
              "check yet.", file=sys.stderr)
        return 2
    claims = write_claims(args.folder)

    print(f"{len(claims)} statement(s) to double-check.")
    return 0


def cli_apply(argv=None) -> int:
    from rfq.verification import REFUTING, run_apply

    ap = argparse.ArgumentParser(description="Apply verify-pass verdicts.")
    ap.add_argument("folder", help="the folder holding the RFQ package")
    ap.add_argument("--mode", default="subagent",
                    choices=("subagent", "in-thread"),
                    help="how the verify pass was run (recorded in the report)")
    args = ap.parse_args(argv)

    work = os.path.join(os.path.abspath(args.folder), "output", ".work")
    analysis_path = os.path.join(work, "analysis.json")
    claims_path = os.path.join(work, "claims.json")
    if not (os.path.exists(analysis_path) and os.path.exists(claims_path)):
        # A resume lands here often. A bare FileNotFoundError traceback
        # tells a salesperson nothing and looks like a crash. A missing
        # verdicts.json is different - that is the sub-analysis having
        # produced nothing, and it is already recorded in the report below.
        print("A checkpoint is missing - I can't apply the double-check "
              "from here.", file=sys.stderr)
        return 2
    record = run_apply(args.folder, mode=args.mode)

    if record["status"] == "error":
        print("I couldn't run the double-check, so I've carried on without "
              "it. The report records that.")
    else:
        # Refuted and ambiguous verdicts become V1 / V2 deductions on their
        # sections (rfq/verification.py apply_verdicts).
        sections = sorted({claim["section"] for claim in record["claims"]
                           if claim.get("verdict") in REFUTING})
        print(f"Double-checked {len(record['claims'])} statement(s); "
              + (f"reviewer deductions (V1/V2) in section(s) "
                 f"{', '.join(map(str, sections))}." if sections
                 else "no reviewer deductions."))
    return 0


def cli_plan_input(argv=None) -> int:
    from rfq.planning import write_plan_input

    ap = argparse.ArgumentParser(description="Build the slide-plan input.")
    ap.add_argument("folder", help="the folder holding the RFQ package")
    args = ap.parse_args(argv)

    work = os.path.join(os.path.abspath(args.folder), "output", ".work")
    corpus_path = os.path.join(work, "corpus.json")
    analysis_path = os.path.join(work, "analysis.json")
    if not (os.path.exists(corpus_path) and os.path.exists(analysis_path)):
        # A resume lands here often. A bare FileNotFoundError traceback
        # tells a salesperson nothing and looks like a crash.
        print("A checkpoint is missing - I can't prepare the deck plan "
              "from here.", file=sys.stderr)
        return 2
    payload = write_plan_input(args.folder)

    print(f"Prepared {len(payload['answers'])} section(s) for the deck plan.")
    return 0


def cli_validate(argv=None) -> int:
    from rfq.validation import (RUNNER_CODES, check_analysis, check_corpus,
                                check_plan)

    checks = {"corpus": check_corpus, "analysis": check_analysis, "plan": check_plan}

    ap = argparse.ArgumentParser(description="Validate one stage output.")
    group = ap.add_mutually_exclusive_group(required=True)
    for name in checks:
        group.add_argument(f"--{name}", metavar="PATH",
                           help=f"validate a {name} JSON file")
    ap.add_argument("--with-corpus", metavar="CORPUS_JSON",
                    help="with --analysis: also check every source against "
                         "this corpus.json")
    args = ap.parse_args(argv)

    kind = next(k for k in checks if getattr(args, k))
    path = getattr(args, kind)
    if not os.path.exists(path):
        print(f"Not found: {path}", file=sys.stderr)
        return 1
    try:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
    except json.JSONDecodeError as exc:
        print(f"{os.path.basename(path)} is not valid JSON: {exc}",
              file=sys.stderr)
        return 1

    if kind == "analysis" and args.with_corpus:
        with open(args.with_corpus, encoding="utf-8") as fh:
            problems = check_analysis(payload, corpus=json.load(fh),
                                      runner_codes=RUNNER_CODES)
    elif kind == "analysis":
        problems = check_analysis(payload, runner_codes=RUNNER_CODES)
    else:
        problems = checks[kind](payload)
    if not problems:
        print(f"{kind}: OK")
        return 0
    for problem in problems:
        print(problem, file=sys.stderr)
    return 2


def cli_evaluate(argv=None):
    from rfq.validation import format_lines, run_evaluation

    ap = argparse.ArgumentParser()
    ap.add_argument("run_json", help="the saved run report")
    ap.add_argument("--corpus", help=".work/corpus.json for the run "
                                 "(enables C2/W2 traceability checks)")
    ap.add_argument("--images", help=".work/images.json for the run "
                                 "(enables CP1)")
    args = ap.parse_args(argv)

    manifest = None
    if args.images:
        with open(args.images, encoding="utf-8") as fh:
            manifest = json.load(fh)
    images_dir = (os.path.join(os.path.dirname(os.path.abspath(args.images)), "images")
                  if args.images else None)
    fails, warns, oks = run_evaluation(args.run_json, args.corpus, manifest, images_dir)
    for line in format_lines(fails, warns, oks):
        print(line)
    print(f"\n{len(fails)} fail / {len(warns)} warn / {len(oks)} pass")
    return 1 if fails else 0


def cli_finalize(argv=None) -> int:
    from rfq.delivery import finalize, load_checkpoints, write_outputs

    ap = argparse.ArgumentParser(description="Build the deck and run report.")
    ap.add_argument("folder", help="the folder holding the RFQ package")
    args = ap.parse_args(argv)

    folder = os.path.abspath(args.folder)
    try:
        cp = load_checkpoints(folder)
        plan, deck, report = finalize(cp["corpus"], cp["analysis"],
                                      cp["draft"], cp["verification"],
                                      cp["execution"], account=cp["account"],
                                      downgrades=cp["downgrades"],
                                      manifest=cp["manifest"],
                                      images_dir=cp["images_dir"])
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    pptx_path, report_path = write_outputs(folder, cp["corpus"], deck, report)

    slides = sum(len(q.get("slides", [])) for q in plan.get("questions", []))
    print(f"Wrote the deck ({len(plan['questions'])} sections, {slides} "
          f"slides) to {pptx_path}")
    print(f"Wrote the report to {report_path}")
    for action in report["run"]["sanitizer"]:
        print(f"  adjusted: {action}")
    return 0


def cli_render(argv=None) -> int:
    from rfq.delivery import render_report

    ap = argparse.ArgumentParser(description="Re-render a saved run report or bare slide plan.")
    ap.add_argument("report", help="the saved report or slide-plan JSON")
    ap.add_argument("output", nargs="?", help="preview PowerPoint output path")
    args = ap.parse_args(argv)
    if not os.path.exists(args.report):
        print(f"Not found: {args.report}")
        return 1
    try:
        result = render_report(args.report, args.output)
    except ValueError as exc:
        print(str(exc))
        return 1
    print(f"Rendered {result['sections']} sections / {result['slides']} "
          f"content slides -> {result['pptx']} ({result['bytes']:,} bytes)")
    return 0


def cli_lookup(argv=None) -> int:
    from rfq import guidance

    ap = argparse.ArgumentParser(description="Query the Guidance Document.")
    sub = ap.add_subparsers(dest="command", required=True)
    acc = sub.add_parser("account", help="candidate Salesforce accounts")
    acc.add_argument("name")
    acc.add_argument("--country")
    acc.add_argument("--site")
    acc.add_argument("--limit", type=int, default=10)
    res = sub.add_parser("resolve", help="the account a run would pick, "
                         "with the reason for every candidate")
    res.add_argument("--customer", required=True)
    res.add_argument("--site", help="the customer's own address")
    res.add_argument("--text-file", help="the RFQ text (corpus_text.txt)")
    lst = sub.add_parser("list", help="one official vocabulary")
    lst.add_argument("kind", choices=guidance.VOCABULARIES)
    args = ap.parse_args(argv)

    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
    except (ValueError, OSError):
        pass
    if args.command == "account":
        result = guidance.search_accounts(args.name, country=args.country,
                                          site=args.site, limit=args.limit)
    elif args.command == "resolve":
        text = ""
        if args.text_file:
            with open(args.text_file, encoding="utf-8") as fh:
                text = fh.read()
        result = guidance.resolve_account(args.customer, text,
                                          site=args.site)
    else:
        result = guidance.vocabulary(args.kind)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


PUBLIC_TOOLS = {"lookup": cli_lookup, "validate": cli_validate,
                "evaluate": cli_evaluate, "render": cli_render}


DEBUG_TOOLS = {
    "extract": cli_extract, "corpus": cli_corpus, "merge": cli_merge,
    "claims": cli_claims, "apply": cli_apply, "plan-input": cli_plan_input,
    "validate": cli_validate, "evaluate": cli_evaluate,
    "finalize": cli_finalize, "render": cli_render, "lookup": cli_lookup,
    "record": cli_record, "request": cli_request, "state": cli_state,
}


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in PUBLIC_TOOLS:
        result = PUBLIC_TOOLS[args[0]](args[1:])
        return 0 if result is None else result
    if args and args[0] == "debug":
        if len(args) == 2 and args[1] in ("-h", "--help"):
            print("Debug operations: " + ", ".join(DEBUG_TOOLS))
            return 0
        if len(args) < 2 or args[1] not in DEBUG_TOOLS:
            print("Choose a debug operation: " + ", ".join(DEBUG_TOOLS),
                  file=sys.stderr)
            return 2
        result = DEBUG_TOOLS[args[1]](args[2:])
        return 0 if result is None else result
    return workflow_main(args)


if __name__ == "__main__":
    sys.exit(main())
