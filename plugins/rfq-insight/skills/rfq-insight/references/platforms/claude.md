# Claude adapter (Claude Code, Claude Desktop Code, Claude Desktop Cowork)

Use this adapter whenever the host is a Claude application: Claude Code in a
terminal or IDE, the Code experience in Claude Desktop, or a Cowork session in
Claude Desktop. All three run the same skill; the Python engine never calls an
AI API and needs no API key. The run needs local command execution, file
writes, image reading and fresh native Agents (subagents).

## Permission notice

In Claude Code and Claude Desktop Code, send this once before the first
command, then continue without waiting:

> RFQ Insight runs several local scripts and writes to `<folder>/output/`. To
> avoid a prompt at each step, switch this session to auto mode (Shift+Tab);
> otherwise approve each step when asked.

Skip it when the session already runs without per-command approval. Cowork
grants folder access once and needs no notice.

## Dispatch each model stage

The installed runtime has two executable Python files: `bootstrap.py` and
`rfq_run.py`. Keep normal processing in the `next` loop. Public `lookup`,
`validate`, `evaluate`, `render`, `timing`, and `debug` commands are inspection tools;
do not invoke internal files under `scripts/rfq/` individually.

1. Run `scripts/rfq_run.py next "<folder>" --host claude` with the bootstrap
   interpreter (SKILL.md step 2). For `dispatch` and `repair`, every entry in
   `requests` is one worker job.
2. For each request, start a **fresh** native Agent with
   `subagent_type="general-purpose"`, `model` set to the request's `model`,
   and a prompt containing **only** its `message`. Do not pass the parent
   chat, analysis reasoning or full skill. For `repair`, send its
   `repair_message` (including errors) to the same Agent instead (or to a
   fresh Agent after the `message` if the first one is gone).
3. The request's `model` is the alias of its route in
   `references/platforms/models.json`; the support route is only for optional
   support tasks. Pass the alias as the Agent's `model` where the host accepts
   one. If the host offers no per-worker model choice (some Cowork builds), run
   the worker on the host's current model instead of stopping. Never ask the
   user to choose a model and never mention routing in chat.
4. Wait for every Agent of the request list, then run `rfq_run.py next` again
   with one `--completed <request_id>` per Agent whose result arrived and one
   `--failed <request_id>` per Agent that ended without a result (use the
   returned request's ID, including a new repair ID when reusing an Agent).
   When the host reports the resolved model, add `--actual-model <reported-id>`
   to that call; otherwise leave it out. A configured alias is a request, not
   proof of the resolved model version. Verification always starts in a fresh
   Agent, never by resuming the analysis worker.

That one `next` call records the terminal observations and advances the run.
`rfq_run.py event "<folder>" --request-id <request_id> --event started` is
optional and only for a start the host actually observes (a spawn
acknowledgment is not one). Pass `--observed-at` only for a host timestamp with
a timezone, and `--input-tokens` / `--output-tokens` only when reported. Never
infer model versions, usage, queue delay or start time. Only the coordinator
runs these commands, one at a time per folder; Agents never run them or write
timing/progress records, and Agent prompts never mention them. A telemetry
failure does not stop the `next` loop; output validation records acceptance
separately. `rfq_run.py timing "<folder>"` is read-only inspection; null
intervals mean observations were unavailable.

The coordinator runs scripts; the workers read inputs and write their result.
Figure requests cover up to six pictures each and name one output per picture,
the transcription `.work/image_text/<id>.txt`; a saved transcription is reused
when valid. Figure requests and verification partitions run concurrently
within host capacity, each in a fresh Agent with disjoint output paths.
Analysis, slide planning and stage transitions remain sequential. The runner
merges the figure text before analysis.
For a list longer than the available worker slots, use a bounded rolling queue:
launch jobs until the slots are full; as each finishes, collect its result,
finish/close that worker when supported, then launch the next queued job
immediately. Do not wait for an entire wave before replacing a finished job.
Never reuse a worker's context for an independent job. The runner must see
every job finished before the next stage.
Verification must use a fresh Agent context. This is a context boundary, not
an operating-system filesystem sandbox.

If fresh Agents or image-reading capability is unavailable, stop with one
short capability error. Isolated verification is required; do not verify
in-thread, skip pictures, or ask the user to accept weaker execution. Keep
routine routing details internal and follow the shared interaction contract:
no narration and only the PowerPoint link on success.

## Cowork notes

- The connected working folder is the RFQ folder unless the request names a
  folder inside it. Outputs land in `<folder>/output/` as usual.
- Scripts run through the sandbox's shell; the document toolbox is provisioned
  into the sandbox user's home on first use and reused while it persists.
- Cowork may show the produced file on its own; still end with the single
  PowerPoint link and nothing else.

Do not add optional support tasks to a normal RFQ run. If separately requested,
the support route is limited to already-established facts supplied by the
coordinator, such as a bounded wording task. It does not analyze documents,
verify claims, plan slides or transcribe RFQ figures. Python continues to handle
mechanical operations without model calls.

## Follow-up stage

Follow-up questions use the stage `followup`. Dispatch the request returned by
`rfq_run.py ask` in one fresh `general-purpose` Agent with only the request's
`message` and the request's `model`. `rfq_run.py answer` records the execution
itself; pass `--actual-model` only when the host reports it.
For a repair from `answer`, reuse that Agent with `repair_message`; a replacement
gets the full `message` followed by `repair_message`, using the same route.
