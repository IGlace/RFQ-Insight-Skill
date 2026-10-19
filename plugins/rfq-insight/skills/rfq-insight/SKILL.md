---
name: rfq-insight
description: Analyse an AVL RFQ package in a local folder and generate the RFQ Insight PowerPoint deck. Use when the user asks to analyse an RFQ, run an RFQ analysis, or process an RFQ folder. Also use when the user asks a follow-up question about an RFQ that was already analysed, or asks to add those answers to the presentation. Also use it to compare two already analysed RFQs (two RFQ folders or two revisions) into a comparison PowerPoint.
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
- The adapter's permission notice is the only message allowed before the
  result. It informs; it is not a question. Never wait for a reply to it, and
  never change permission settings or approve commands on the user's behalf.
- Exception — follow-up mode (see "Follow-up questions"): answer the user's
  question in chat with its sources, and build a new PowerPoint only when the
  user asks to add the answers to the presentation. All other rules of this
  contract still apply: no narration, no offers, no questions.

## Runtime and host

The installed skill has two executable Python entry points:
`scripts/bootstrap.py` prepares the document toolbox, and `scripts/rfq_run.py`
runs the workflow. Files under `scripts/rfq/` are internal modules and must
not be invoked individually. Normal runs use the `next` loop; `lookup`,
`validate`, `evaluate`, `render`, `timing`, and `debug` operations are for explicit
inspection or troubleshooting.

Resolve all `scripts/` and `references/` paths against the directory containing
this installed `SKILL.md`, never the RFQ folder or current working directory.
In a Claude plugin installation that directory is
`${CLAUDE_PLUGIN_ROOT}/skills/rfq-insight`; it is read-only and changes on
update, so never write there. Quote absolute paths, including the interpreter.
On PowerShell use the call operator for a quoted executable path.

Identify the host from available capabilities. Codex is the primary host:

- Codex (CLI, IDE or desktop app): load only `references/platforms/codex.md`.
- Claude Code, Claude Desktop Code, or Claude Desktop Cowork: load only
  `references/platforms/claude.md`.
- Any other host, including GitHub Copilot CLI: stop with "RFQ Insight
  supports Claude and Codex hosts only."

Both adapters use the routes in `references/platforms/models.json`. The run
requires local command execution, file writes, image viewing and fresh workers
(subagents) with their own context; if any of these is missing, stop with one
short capability sentence. Model selection is best effort: request the
configured model when the host lets a worker's model be chosen, otherwise use
the host's current model. Never ask the user to pick a model, never narrate
routing, and never drop isolation or verification because a model differs.

Before the first command of a run, send the adapter's permission notice once,
then continue immediately. The run executes many local scripts and file
writes; the user decides, for this session only, whether to approve each one
or let them run. Skip the notice when the adapter says it does not apply.

Use an available system Python (3.10+) to run `scripts/bootstrap.py --check`.
Exit 0 prints the interpreter to use for all subsequent commands. Exit 3
requires `scripts/bootstrap.py` without flags to set up the document tools in
`~/.rfq-insight/venv` (it falls back to the system interpreter when that
already has the libraries). Run setup without narration. If setup fails, stop
with its single plain-language error; do not invent another installation
method.

## 1. Resolve the folder and name

1. Use the RFQ folder supplied in the request or already established in this
   chat. If the user says "this folder", or the host has a connected working
   folder (Cowork) and the request names no other folder, use that working
   directory. If no single folder can be resolved, stop: "An RFQ folder path
   is required."
2. Pass a project name already supplied as `--project`; it seeds the run's
   display name (shown on the deck's cover, footer and end slide) until the
   analysis has an opportunity name, which then replaces it, and never
   renames the deck file, which is named from the analysis's own
   `opportunity_name` field instead. Otherwise leave
   `--project` out and the runner uses the folder's name. Treat "same" as
   the folder's name. On resume the runner keeps the saved name.

## 2. Run the pipeline loop

`scripts/rfq_run.py` does every deterministic step of the run itself. That
covers progress records, extraction, figure merging, validation, the
confidence scores, claim harvesting, verification bookkeeping, the Salesforce
account lookup, the Source Material section, the slide plan, the deck build,
the quality check and execution records. It stops only when a model worker is
needed. Run it with the bootstrap interpreter:

    "<python>" "<skill>/scripts/rfq_run.py" next "<folder>" --host <codex|claude> [--project "<name>"] [--completed <request_id> ...] [--failed <request_id> ...]

It prints one JSON object. Act on its `status`:

| `status` | What the coordinator does |
|---|---|
| `dispatch` | Start one fresh worker per entry in `requests`, through the adapter. Figure jobs and independent verification partitions run concurrently in the adapter's bounded rolling queue. Other model stages have one request. Wait for all jobs, then run `next` again with `--completed <request_id>` for each worker whose result arrived and `--failed <request_id>` for each that ended without one. |
| `repair` | Send the request's `repair_message` to the worker that wrote the output and wait for its corrected file. If that worker is gone, start a fresh one with the request's full `message` followed by `repair_message`. Then run `next` again with `--completed` or `--failed` for the repair's request ID. The runner counts attempts: the third failure comes back as `blocked`. |
| `done` | Deliver (step 3). |
| `blocked` | Reply with `message` exactly as given, as the only reply, and stop. Progress is saved. |

If `rfq_run.py` exits with a nonzero code and prints no JSON, stop with one
short factual sentence built from its stderr line; progress is saved. Do not
run the individual scripts to work around it.

When the host reports which model a worker actually used, add
`--actual-model <id>` to the next `next` call (Codex also
`--actual-reasoning-effort <effort>`); the runner records it. Never invent
it. Do not narrate statuses, stages or counts.

`--completed` and `--failed` record each worker's terminal observation in the
same command that advances the run; the separate `event` command is only for
an optional `started` observation (see the adapter). Observations are
telemetry, never permission for a worker to write additional files or proof
that its result passed validation. A missing observation stays unavailable;
telemetry errors do not interrupt a correct run. Use `timing` only for
explicit inspection.

The runner enforces the run's rules, so the coordinator does not repeat them:

- Resume is automatic. A later `next` continues at the saved stage. The runner:
  - re-reads the folder when inputs were unread;
  - redoes a failed or in-thread verification;
  - delivers a finished deck again without rebuilding it;
  - rebuilds missing deliverables.
- Unreadable inputs, an oversized package, three failed attempts and a
  failed quality check all come back as `blocked` with the sentence to send.
- Existing presentations and reports are never overwritten.
- Figures remain analysis evidence. Product-picture slides are excluded from
  client presentations, including replay and follow-up rebuilding.
- Verification always runs in a fresh, isolated worker that never sees the
  parent chat or the analysis reasoning; dispatch it as given.
- During a normal run, do not run the individual scripts in `scripts/`
  (extraction, validation, merging, finalizing). They exist for debugging
  only.
- Restart an earlier stage only when the user explicitly asks for it, or after
  a `blocked` message that asks for an explicit stage: run `next` once with
  `--restart <stage>` (`extract`, `figures`, `analysis`, `verification`,
  `slides`, `finalize` or `evaluate`). Later stages then run again.
- Only one run may write an RFQ folder at a time.
- The coordinator serializes every `event`, `next`, `ask`, and `answer` command
  for a folder. Concurrent workers write only their disjoint requested outputs;
  they never write progress or timing records. Collect the workers' terminal
  observations and pass them to the next `next` call.

Workers get only the request's `message`. They read the instruction and input
files it names completely and write only the output paths it names:

- **figures**: transcribe visible labels, dates, phase names, numbers, table
  cells, arrows and connections without interpretation. Each picture has one
  output, the transcription `.work/image_text/<id>.txt`; a saved
  transcription is reused when valid. An illegible picture gets no output and
  the run continues. Missing image-viewing capability is a blocker, not
  evidence that a picture is unreadable.
- **analysis**: answers sections 1-11 from its supplied original corpus or
  exact prepared evidence ledger, lists each section's deductions from the
  rule catalogue, and fills the structured Opportunity Info object with the
  Guidance vocabulary (`references/knowledge/90_guidance_denominators.md`).
  It never writes the Salesforce account or KAM, a confidence score, or
  section 12 (Source Material); the runner builds those.
- **verification**: judges the listed claims against `corpus.txt` only.
- **slides**: normally no worker runs. The runner builds the slide plan from
  the answers' fixed markdown shapes; only when an answer does not parse does
  this worker turn the plan input into the slide plan, without reopening the
  source documents or changing the fixed sections and presentation rules.

Oversized inputs first undergo exact Python evidence factoring. Every original
character and repeated occurrence retains its file/page/chapter anchors. The
prepared representation must fit the existing analysis limit; unique packages
that still exceed it remain blocked. Preparation never substitutes a summary,
adds worker calls, or changes the original corpus used by verification.

Source references retain the file name, verified page or page range, and the
chapter/section path from the source document. Word page numbers are available
only when native Word pagination succeeds; otherwise cite chapter headings and
state that rendered pages are unavailable. A table spanning several pages has
the verified table range, not an invented exact row page. Never guess a page or
chapter, and never treat a valid locator as proof of the claim itself.

Every content slide has complete source references in its speaker notes,
including continuations. Group them by exact file name and label the section,
page or page range, slide, and sheet so the reader can find the original text.
Never invent a page or a more precise content-to-source mapping than recorded.
Source citations do not appear on visible slides.

The notes of the first slide of each section start with its confidence band,
which the runner derives from an internal score that is never shown: a line
`Confidence: <band>`, a `Basis:` line, then one line per reason the rating was
lowered (rule code, the specific items and the file or clause they rest on,
never the points it cost), or `No deductions: ...` when there are none, a
`Not rated High: ...` line when the content's provenance held the band down,
a `Contradictions:` line, then one `Check:` line with the actual verification
results and, for a trimmed section, one `Shown:` line. Nothing else precedes
the sources. The visible chip reads `<band>` alone (High, Medium or Low); no
slide shows a number such as `6/10`. Never claim all statements were checked.
Each follow-up slide carries its own references and confidence in notes.

## 3. Deliver

On `done`, confirm that the `pptx` path exists and is non-empty. Return exactly
one link with label `PowerPoint` and that absolute `.pptx` path (in Cowork,
the path inside the connected folder). Stop immediately. Do not add any other
message, artifact, question, offer, or action. Never link the JSON report.

## Follow-up questions

Use this mode when the user asks a question about an RFQ folder that already
has `<folder>/output/.work/corpus.json`, or asks to add follow-up answers to
the presentation. Never start it in the middle of a normal run. Use the same
host adapter, interpreter and quoting rules as the normal run.

1. Run `scripts/rfq_run.py ask "<folder>" --host <host> --question "<the
   user's question, verbatim>"`.
   - `dispatch`: start one fresh worker for the single request, exactly as for
     the other model stages (see the adapter's "Follow-up stage").
   - `stale`: the RFQ files changed since the run, or reading was interrupted.
     Tell the user in one sentence that the documents are re-read and that the
     existing PowerPoint reflects the older files. Then repeat
     `scripts/rfq_run.py next "<folder>" --host <host> --until figures`,
     dispatching its figure requests as in a normal run, until it returns
     `stopped`, and run `ask` again. If `next` returns `blocked`, tell the
     user its message and stop.
   - `blocked`: stop with its message.
2. When the worker has finished, run `scripts/rfq_run.py answer "<folder>"
   --host <host>` (add `--actual-model` only when the host reports it).
   - `stale`: the documents changed while the worker was answering. Repeat
     step 1's extraction/figure refresh loop until `stopped`, run `ask` for
     the same question again, dispatch its fresh worker, and run `answer`
     to validate the new answer. If refresh returns `blocked`, stop with
     its message.
   - `repair`: send its request's `repair_message` to the same worker (or full
     `message` followed by `repair_message` to a replacement), then run `answer`
     again. Three attempts in total.
   - `blocked`: stop with its message.
   - `answered`: reply with the answer text, then one line `Sources:` listing
     each source as file and locator. Nothing else.
3. Only when the user asks to add the answer(s) to the presentation, run
   `scripts/rfq_run.py add-followups "<folder>"` (or `--ids <n> ...` for
   specific answers). On `done`, return exactly one link labelled
   `PowerPoint` to its `pptx` path. The earlier PowerPoint stays untouched;
   the new one adds an "Additional Information" section before Source
   Material. When the RFQ documents changed since the latest presentation,
   `add-followups` is blocked until the RFQ analysis has run again.
   Default addition includes only current-revision answers; explicitly
   selected older answers are blocked and their IDs are named.

Every question, answer and source list is kept in
`<folder>/output/.work/followups.json` next to the extracted documents, so
follow-up questions keep working in any later session. Storage is
local to the RFQ folder only: there is no central or shared store, and
deleting the `output/` folder deletes the history. Older answers remain
local history and are excluded from automatic addition after a refresh.

## Compare two analyses

Use this when the user asks to compare two RFQ analyses: two different RFQs,
or two revisions of the same RFQ in two folders. Both folders must already
hold a finished run; do not run or resume the analysis pipeline for it.

1. Resolve both folders as in step 1. If either cannot be resolved, stop:
   "Two RFQ folders are required for a comparison."
2. Run `scripts/bootstrap.py --check` as in "Runtime and host" and use the
   interpreter it prints.
3. Run `scripts/rfq_run.py compare "<folder A>" "<folder B>"`. It reads each
   folder's `output/.work/deliverables.json` and never needs a model worker.
4. Parse the printed JSON. For `"status": "blocked"`, stop with its `message`
   and nothing else. For `"status": "done"`, return exactly one link labelled
   `PowerPoint` to the `pptx` path and stop.

The interaction contract applies unchanged: no narration, no summary of the
differences in chat, and no offer to re-run either analysis. The comparison
JSON in folder A's `output/.work/comparison.json` is internal.
