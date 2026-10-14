# Codex adapter (Codex CLI, IDE extension, Codex and ChatGPT Work desktop modes)

Use this adapter whenever the host is Codex, including the Codex and Work modes
of the ChatGPT desktop app. The Python scripts never call an AI API. The
coordinator uses the host's native workers and keeps script execution in its own
conversation. Model preferences are in `models.json` beside this file.

## Capability check

Before processing an RFQ, check that the host provides local command execution,
file writes, image viewing, and fresh workers (`collaboration.spawn_agent` or
the host's equivalent). The configured routes use `gpt-6.1-sol` for every RFQ
stage and `gpt-6-luna` only for optional support work; account/model
availability is determined by the host. Model selection is best effort: pass
the configured `model` and `reasoning_effort` when the worker tool exposes
them, otherwise spawn the worker without overrides so it inherits the host's
model. Do not substitute a different model family yourself.

## Permission notice

Send this once before the first command, then continue without waiting:

> RFQ Insight runs several local scripts, sets up its document tools in
> `~/.rfq-insight/venv` and writes to `<folder>/output/`. To avoid a prompt at
> each step, set this session to Auto or Full Access with `/approvals`
> (`/permissions` in newer versions); otherwise approve each step when asked.

Skip it when the session already runs with Full Access.

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
3. For `repair`, send its `repair_message` (including errors) to the same worker, with the same model (or
   a fresh worker with the request's `message` followed by the errors if the
   first one is gone).
4. Wait for every worker of the request list, then run `rfq_run.py next`
   again. Add `--actual-model <reported-id>` and
   `--actual-reasoning-effort <reported-effort>` only when the host reports
   them. Finish/close workers when the host supports it, so later stages have
   capacity.

Keep coordinator commands for a folder sequential, including lifecycle `event`
calls while workers run concurrently. Queue observations, persist each in turn,
and finish those writes before `next`, `ask`, or `answer`. Workers never invoke
these commands or write timing/progress records.

The coordinator records observed lifecycle events using
`rfq_run.py event "<folder>" --request-id <request_id> --event started|completed|failed`.
Use the ID from the corresponding returned request, including a new repair ID
when reusing a worker. Send `started` only when the host observes the worker
starting, and `completed` or `failed` when its terminal result arrives. A spawn
acknowledgment alone is not a start observation. If the host does not expose
start, send only the observed terminal event. Pass `--observed-at` only for a
host timestamp with a timezone; otherwise the command records the coordinator's
observation time. Pass `--actual-model`, `--actual-reasoning-effort`,
`--input-tokens` and `--output-tokens` only when the host reports them for that
request. Do not infer queue delay, tokens, model identity or worker start times.
Only the coordinator runs this command; do not include it in worker messages
or expand their output permissions. Event-recording failures do not stop the
`next` loop. The runner validates outputs independently and saves acceptance
separately. `rfq_run.py timing "<folder>"` reads the evidence without changing
checkpoints; null intervals mean observations were unavailable.

Figure workers may run concurrently within available capacity; each request
covers up to six pictures and names two outputs per picture: the transcription
`.work/image_text/<id>.txt` and the classification `.work/image_text/<id>.json`.
A saved result is reused only when both are valid. Verification partitions and
figure requests also run concurrently within available capacity;
each gets a separate fresh context and disjoint output paths. Analysis, slide
planning and stage transitions remain sequential. The runner merges figure text before analysis.
For a list longer than the available worker slots, use a bounded rolling queue:
launch jobs until the slots are full; as each finishes, collect its result and
record its terminal event sequentially, finish/close that worker when supported,
then launch the next queued job immediately. Do not wait for an entire wave
before replacing a finished job. Keep remaining jobs queued until capacity is
available; never reuse a worker's context for an independent job. The runner
must see every job finished before the next stage.
Verification uses
`fork_turns="none"` even if
other work elsewhere in the conversation uses inherited history. Fresh-context
isolation is a prompt/context boundary, not an OS filesystem sandbox.

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
Luna is suitable for a small, explicitly bounded wording or formatting task
whose facts have already been established. Supply only those facts and the
output destination in a fresh worker. It must not reinterpret RFQ documents,
judge claims, plan slides, or replace figure transcription. Ordinary extraction,
validation and rendering remain Python; do not add model calls for them.

## Follow-up stage

Follow-up questions use the stage `followup` (route `gpt-6.1-sol`, reasoning
effort `high`). Dispatch the request returned by `rfq_run.py ask` in a fresh worker with
`fork_turns="none"`, the request's `model`, `reasoning_effort` and `message`.
`rfq_run.py answer` records the execution itself; pass `--actual-model` and
`--actual-reasoning-effort` only when the host reports them.
For a repair from `answer`, reuse that worker with `repair_message`; a replacement
gets the full `message` followed by `repair_message`, using the same route.
