---
name: rfq-insight
description: >-
  Analyse an AVL RFQ package in a local folder and generate the RFQ Insight
  PowerPoint deck. Use when the user asks to analyse an RFQ, run an RFQ
  analysis, or process an RFQ folder.
---

# RFQ Insight

Generate the AVL-branded PowerPoint in `<folder>/output/` using the fixed
workflow below. The run report and `.work/` checkpoints are internal artifacts.

## Interaction contract

- Do not ask questions, offer choices, or request routine confirmation. This
  workflow has no interactive intake or preference collection.
- Use the defaults below. Do not invite changes to models, verification,
  sections, layout, naming, output format, skipped files, or restart behavior.
- Work silently. Do not narrate setup, stages, tool calls, document counts,
  findings, warnings, repairs, or model routing. Do not relay script summaries,
  analysis reasoning, verification verdicts or quality-check results.
- On success, return exactly one clickable link to the generated `.pptx` and
  stop. No introduction, completion summary, report link, preview, extra export,
  follow-up offer, or further action after delivery.
- On a blocking failure, stop with one short factual sentence stating the
  blocker and required correction, if known. Do not turn it into a question,
  offer a weaker workflow, or claim a deck was generated. Preserve checkpoints.
- Follow higher-priority host requirements for mandatory notices or permissions
  using the minimum required wording. Do not create additional approval steps.

## Runtime and host

Resolve all `scripts/` and `references/` paths against the directory containing
this installed `SKILL.md`, never the RFQ folder or current working directory.
In a Claude plugin installation that directory is
`${CLAUDE_PLUGIN_ROOT}/skills/rfq-insight`; it is read-only and changes on
update, so never write there. Quote absolute paths, including the interpreter.
On PowerShell use the call operator for a quoted executable path.

Identify the host from available capabilities:

- Claude Code, Claude Desktop Code, or Claude Desktop Cowork: load only
  `references/platforms/claude.md`.
- Codex (CLI, IDE or desktop app): load only `references/platforms/codex.md`.

Both adapters use the routes in `references/platforms/models.json`. The run
requires local command execution, file writes, image viewing and fresh workers
(subagents) with their own context; if any of these is missing, stop with one
short capability sentence. Model selection is best effort: request the
configured model when the host lets a worker's model be chosen, otherwise use
the host's current model. Never ask the user to pick a model, never narrate
routing, and never drop isolation or verification because a model differs.

Use an available system Python (3.10+) to run `scripts/bootstrap.py --check`.
Exit 0 prints the interpreter to use for all subsequent commands. Exit 3
requires `scripts/bootstrap.py` without flags to set up the document tools in
`~/.rfq-insight/venv` (it falls back to the system interpreter when that
already has the libraries). Run setup without narration. If setup fails, stop
with its single plain-language error; do not invent another installation
method.

## 1. Resolve inputs and progress

1. Use the RFQ folder supplied in the request or already established in this
   chat. If the user says "this folder", or the host has a connected working
   folder (Cowork) and the request names no other folder, use that working
   directory. If no single folder can be resolved, stop: "An RFQ folder path
   is required." If it does not exist, stop: "The RFQ folder could not be
   found; correct the path."
2. Use an opportunity name already supplied; otherwise use the folder's name.
   Treat "same" as the folder's name. On resume, keep the saved project name.
3. Run `scripts/workflow_state.py "<folder>" --resume` and continue at its
   pending stage automatically. An invalid progress record is a blocker.
   Do not ask whether to resume or restart. Start at `extract` when there are
   no checkpoints. Restart an earlier stage only if already explicitly requested
   or required by the recovery rules below; its downstream stages must run again.
4. Existing presentations and reports must be preserved. The finalizer selects
   the next unused pair of filenames automatically, adding `_2`, `_3`, etc.
   when necessary. Never ask to overwrite or delete an old output.

### Resume rules

The helper's pending stage is authoritative even when older downstream files
exist. Legacy checkpoints without a progress record use these mappings (the
newest checkpoint wins; later rows break timestamp ties):

| Newest checkpoint | Resume at |
|---|---|
| `corpus.json` or `images.json` | `figures` |
| `corpus.txt` | `analysis` |
| `analysis.json` or `claims.json` | `verification` |
| `verification.json` or `plan_input.json` | `slides` |
| `slide_plan.json` | `finalize` |

Before resuming downstream of extraction, inspect `corpus.json`. If
`extraction.skipped` contains unread inputs, restart at `extract` automatically
and apply step 2 to the fresh result. This lets corrected files be read without
reusing an incomplete corpus or staying blocked on an obsolete failure record.
A stored verification with
`mode: in-thread` or `status: error` requires restarting at `verification`
before any later stage, including delivery of a previously completed run.

For pending `evaluate` or `done`, read `.work/deliverables.json`, written by
the finalizer, for the actual `pptx` and `report` paths. Require both files to
exist inside this RFQ folder's `output/`. If the record or either output is
missing, restart at `finalize` to create a new pair from valid checkpoints.
Malformed records or paths outside `output/` are blockers. For `done` with
valid outputs, run step 8 again and deliver the recorded deck without rebuilding.

Image folders, execution records, history files, delivery records and stage
requests are not progress markers. A `verdicts.json` without
`verification.json` resumes at verification; obtain fresh verdicts for the
current claims. Preserve checkpoint content when switching supported hosts.
Only one run may write an RFQ folder at a time.

After re-extraction, always rerun the figure stage and merge: extraction replaces
the corpus, although saved nonempty figure transcriptions remain reusable.

### Stage boundaries

Before each stage, run `scripts/workflow_state.py "<folder>" --start <stage>`.
This records progress and archives old model outputs under `.work/history/`.
If it fails, stop before modifying outputs. Do not repeat `--start` between
validation repairs by the same worker.

After the stage and its validation/merge/application succeed, run
`scripts/workflow_state.py "<folder>" --complete <stage>`. Never complete a
failed stage. These are the fixed stage names:

| Step | Stage | Complete after |
|---|---|---|
| 2 | `extract` | extraction succeeds with no unread inputs |
| 3 | `figures` | all figure attempts finish and text is merged, or no images exist |
| 4 | `analysis` | analysis validates |
| 5 | `verification` | isolated verdicts are applied, or there are no claims |
| 6 | `slides` | slide plan validates |
| 7 | `finalize` | deck, internal report and delivery record are written |
| 8 | `evaluate` | quality check exits 0; warnings are retained internally |

## 2. Extract the documents

Run `scripts/extract_corpus.py "<folder>" --project "<name>"`.
Inspect its result and `corpus.json`; do not relay the summary.

- If `extraction.skipped` names inputs that could not be read, stop:
  "Cannot read <filenames>; provide readable copies to generate the PowerPoint."
  Do not ask to exclude them or continue with a partial package.
- Unsupported extensions in `extraction.ignored`, including `.msg`, remain
  excluded by the existing extraction policy and recorded internally.
- Exit 1 with no readable files is a blocker: "The RFQ folder contains no
  readable supported documents."

## 3. Transcribe figures

Open `<folder>/output/.work/images.json`. For every listed image, use the
adapter to dispatch a `figures` request with that image's `id`. Retain saved
nonempty transcriptions when the request permits reuse. Otherwise the worker
views `.work/images/<file>` and writes `.work/image_text/<id>.txt`.

Transcribe visible labels, dates, phase names, numbers, table cells, arrows and
connections without interpretation. If an individual image is illegible, leave
its transcription empty; the merger records it as unread and the run continues.
Missing image-viewing capability is a blocker, not evidence that the image
itself is unreadable. Figure workers may run concurrently within host capacity.

Run `scripts/merge_image_text.py "<folder>"` after all attempts. This must
precede analysis so both analysis and verification use the transcribed corpus.
Do not announce picture counts or request permission to skip the stage.

## 4. Analyse the package

Run `scripts/validate.py --corpus "<folder>/output/.work/corpus.json"`.
If the size gate fails, stop: "The RFQ package exceeds the supported size;
provide a smaller package." Never truncate or selectively omit documents.

Run `scripts/corpus_text.py "<folder>" --out
"<folder>/output/.work/corpus.txt"`, then dispatch an `analysis` request in
a fresh worker through the adapter. Its prescribed inputs are:

- `references/prompts/RFQ_QA_Extraction_Prompt_v12.md`;
- all eight files in `references/knowledge/`;
- the eleven exact section titles in `references/sections.md`;
- `.work/corpus.txt` with its `=== FILE: <name> ===` delimiters, preserving
  those filenames in evidence citations.

The worker reads every instruction and input file completely (the request's
message says so) and writes `.work/analysis.json`. Run `scripts/validate.py
--analysis "<folder>/output/.work/analysis.json"`. Send only reported errors back for
repair. Three attempts maximum, including the initial attempt. If still
invalid, stop: "The analysis could not be validated; progress is saved."

## 5. Verify claims

Run `scripts/extract_claims.py "<folder>"`. If it reports zero claims,
complete verification and continue to slides without a model call.

Otherwise regenerate `corpus.txt` with `scripts/corpus_text.py` before preparing
the adapter's `verification` request. Launch an isolated fresh worker with only:

- `references/prompts/RFQ_Claim_Verifier_Prompt_v2.md`;
- `.work/claims.json`;
- `.work/corpus.txt`.

The worker must not see the parent chat or the analysis reasoning. It writes
`.work/verdicts.json` as
`{"verdicts": [{"id": 1, "verdict": "confirmed", "evidence": ""}]}`.
Never reuse old verdicts for a new attempt. Isolated verification is required;
do not use an in-thread fallback or offer a weaker check.

Run `scripts/apply_verdicts.py "<folder>"` in its default `subagent` mode.
Inspect `.work/verification.json` as well as the exit code: the helper can
record `status: error` while returning 0. Treat that status as a blocker and
do not complete verification. Retain genuine uncertain findings in the report
and deck rather than asking the user to resolve them.

## 6. Plan the deck

Run `scripts/plan_input.py "<folder>"`, then dispatch a fresh `slides` worker.
It follows `references/prompts/RFQ_Slide_Plan_Prompt_v11.md`, reads only
`.work/plan_input.json` and writes `.work/slide_plan.json`. It must not reopen
the source documents or change the fixed sections and presentation rules.

Run `scripts/validate.py --plan "<folder>/output/.work/slide_plan.json"`.
Repair only reported errors, with three attempts maximum including the first.
On exhaustion stop with one short failure sentence and keep the checkpoints.

## 7. Build the PowerPoint

Run `scripts/finalize.py "<folder>"`. It writes the PowerPoint, internal JSON
run report and `.work/deliverables.json`. It preserves existing outputs by
choosing unused filenames. Use only its printed or recorded absolute paths;
never construct output filenames from the opportunity name.

Retain adjustments, extraction details, confidence and execution metadata in
the internal artifacts. Do not print them in chat or link the JSON report.
If file generation fails, stop with a short error and preserve progress.

## 8. Check and deliver

Run `scripts/evaluate.py` on the actual report path from step 7, with
`--corpus "<folder>/output/.work/corpus.json"`. Save its output to
`.work/evaluation.txt` without echoing it to the user. Exit 0 allows delivery;
warnings stay internal. A nonzero exit blocks delivery: "The PowerPoint did
not pass validation; progress is saved." Do not claim a failed check passed.

After completing the evaluation stage, verify the recorded PowerPoint exists
and is nonempty. Return exactly one link with label `PowerPoint` and that
absolute `.pptx` path (in Cowork, the path inside the connected folder). Stop
immediately. Do not add any other message, artifact, question, offer, or action.
