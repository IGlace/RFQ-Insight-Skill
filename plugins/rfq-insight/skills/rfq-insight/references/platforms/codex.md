# Codex adapter (Codex CLI, IDE extension, Codex and ChatGPT Work desktop modes)

Codex is the primary host of RFQ Insight. Use this adapter whenever the host is
Codex, including the Codex and Work modes of the ChatGPT desktop app. The
Python scripts never call an AI API. The coordinator uses the host's native
workers and keeps script execution in its own conversation. Model routes are in
`models.json` beside this file.

## Capability check

Before processing an RFQ, check that the host provides local command execution,
file writes, image viewing, and fresh workers (`collaboration.spawn_agent` or
the host's equivalent). Every request carries the `model` and
`reasoning_effort` of its route: analysis runs at `high`, verification,
figures, slides and follow-up at `medium`, and the support route only for
optional support work. Account and model availability is determined by the
host. Model selection is best effort: pass the request's `model` and
`reasoning_effort` when the worker tool exposes them, otherwise spawn the
worker without overrides so it inherits the host's model. Do not substitute a
different model family yourself.

## Permission notice

Send this once before the first command, then continue without waiting:

> RFQ Insight runs several local scripts, sets up its document tools in
> `~/.rfq-insight/venv` and writes to `<folder>/output/`. To avoid a prompt at
> each step, set this session to Auto or Full Access with `/approvals`
> (`/permissions` in newer versions); otherwise approve each step when asked.

Skip it when the session already runs with Full Access.

## Attached documents

Attached files are the paths Codex lists with the message. Pass them to
`intake` unchanged (SKILL.md, "Attached documents"); never read them into
chat.

## Dispatch each model stage

The installed runtime has two executable Python files: `bootstrap.py` and
`rfq_run.py`. Keep normal processing in the `next` loop. Public `lookup`,
`validate`, `evaluate`, `render`, `timing`, and `debug` commands are inspection tools;
do not invoke internal files under `scripts/rfq/` individually.

1. Run `scripts/rfq_run.py next "<folder>" --host codex` with the bootstrap
   interpreter (SKILL.md step 2). For `dispatch` and `repair`, every entry in
   `requests` is one worker job.
2. Dispatch **only** each request's `message`, never this chat or the complete
   shared skill. Where the host exposes `collaboration.spawn_agent`, pass a
   unique `task_name`, `fork_turns="none"`, the request's `model`,
   `reasoning_effort` and `message`. Some Codex versions expose a different
   native worker interface: use it only if it supports the same explicit model
   selection and a fresh context. Do not invent parameters or fork full history.
3. For `repair`, send its `repair_message` (including errors) to the same
   worker, with the same model (or a fresh worker with the request's `message`
   followed by the errors if the first one is gone).
4. Wait for every worker of the request list, then run `rfq_run.py next`
   again with one `--completed <request_id>` per worker whose result arrived
   and one `--failed <request_id>` per worker that ended without a result. Use
   the ID of the returned request, including a new repair ID when reusing a
   worker. Add `--actual-model <reported-id>` and
   `--actual-reasoning-effort <reported-effort>` only when the host reports
   them. Finish/close workers when the host supports it, so later stages have
   capacity.

That one `next` call records the terminal observations and advances the run;
no separate command per worker is needed. `rfq_run.py event "<folder>"
--request-id <request_id> --event started` is optional and only for a start the
host actually observes (a spawn acknowledgment is not one). Pass
`--observed-at` only for a host timestamp with a timezone, and
`--input-tokens` / `--output-tokens` only when the host reports them. Do not
infer queue delay, tokens, model identity or worker start times. Only the
coordinator runs these commands, one at a time per folder; workers never run
them or write timing/progress records, and worker messages never mention them.
A telemetry failure does not stop the `next` loop; the runner validates outputs
independently. `rfq_run.py timing "<folder>"` reads the evidence without
changing checkpoints; null intervals mean observations were unavailable.

Figure requests cover up to six pictures each and name one output per picture,
the transcription `.work/image_text/<id>.txt`; a saved transcription is reused
when valid. Figure requests and verification partitions run concurrently
within available capacity, each in a separate fresh context with disjoint
output paths. Analysis, slide planning and stage transitions remain
sequential. The runner merges figure text before analysis.
For a list longer than the available worker slots, use a bounded rolling queue:
launch jobs until the slots are full; as each finishes, collect its result,
finish/close that worker when supported, then launch the next queued job
immediately. Do not wait for an entire wave before replacing a finished job.
Never reuse a worker's context for an independent job. The runner must see
every job finished before the next stage.
Verification uses `fork_turns="none"` even if other work elsewhere in the
conversation uses inherited history. Fresh-context isolation is a
prompt/context boundary, not an OS filesystem sandbox.

## When the host cannot honor a route

Use the configured model and reasoning effort exactly when the host accepts
them. If the worker tool rejects or hides the overrides, spawn the fresh worker
without them and record the actual model only if the host reports it. If fresh
workers or image viewing are unavailable at all, stop with one short capability
error. Do not ask the user to select a model, offer a weaker workflow, or
verify in-thread. Do not change global configuration or launch an API-backed
workaround.

A request is not proof that the host used a model: record actual values only
when reported. Unknown observation metadata alone is not a routing failure.
Keep routine routing details internal and follow the shared interaction
contract: no narration and only the PowerPoint link on success.

## Optional support work

Do not add optional support tasks to a normal RFQ run. If separately requested,
the support route suits a small, explicitly bounded wording or formatting task
whose facts have already been established. Supply only those facts and the
output destination in a fresh worker. It must not reinterpret RFQ documents,
judge claims, plan slides, or replace figure transcription. Ordinary extraction,
validation and rendering remain Python; do not add model calls for them.

## Follow-up stage

Follow-up questions use the stage `followup` (reasoning effort `medium`).
Dispatch the request returned by `rfq_run.py ask` in a fresh worker with
`fork_turns="none"`, the request's `model`, `reasoning_effort` and `message`.
`rfq_run.py answer` records the execution itself; pass `--actual-model` and
`--actual-reasoning-effort` only when the host reports them.
For a repair from `answer`, reuse that worker with `repair_message`; a replacement
gets the full `message` followed by `repair_message`, using the same route.
