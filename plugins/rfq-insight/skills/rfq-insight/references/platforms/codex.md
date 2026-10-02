# Codex adapter (Codex CLI, IDE extension, Codex and ChatGPT Work desktop modes)

Use this adapter whenever the host is Codex, including the Codex and Work modes
of the ChatGPT desktop app. The Python scripts never call an AI API. The
coordinator uses the host's native workers and keeps script execution in its own
conversation. Model preferences are in `models.json` beside this file.

## Capability check

Before processing an RFQ, check that the host provides local command execution,
file writes, image viewing, and fresh workers (`collaboration.spawn_agent` or
the host's equivalent). The configured routes use `gpt-6-sol` for every RFQ
stage and `gpt-6-luna` only for optional support work; account/model
availability is determined by the host. Model selection is best effort: pass
the configured `model` and `reasoning_effort` when the worker tool exposes
them, otherwise spawn the worker without overrides so it inherits the host's
model. Do not substitute a different model family yourself.

## Dispatch each model stage

1. Run `scripts/stage_request.py "<folder>" --host codex --stage <stage>`
   with the bootstrap interpreter. Stages are `analysis`, `verification`,
   `slides`, and `figures`; figures also need `--image-id <id>`.
2. Parse its JSON. If `reuse_existing` is true, retain that figure transcription.
   Otherwise create the output's parent directory and dispatch **only** the
   returned `message`, not this chat or the complete shared skill.
3. Where the host exposes `collaboration.spawn_agent`, pass a unique `task_name`,
   `fork_turns="none"`, the request's `model`, `reasoning_effort`, and `message`.
   Some Codex versions expose a different native worker interface: use it only
   if it supports the same explicit model selection and a fresh context. Do not
   invent parameters or fork full history.
4. Wait for completion. Validate the checkpoint using the shared workflow;
   send only the specific validation errors back to that worker, with the same
   model. The shared three-attempt limit includes the initial attempt.
5. Record the completed attempt with `scripts/record_execution.py`, including
   the actual model only if reported by the host. Finish/close workers when
   the host supports it so subsequent stages have capacity.

Record syntax: `scripts/record_execution.py "<folder>" --host codex --stage
<stage> --mode isolated`, adding `--actual-model <reported-id>` and
`--actual-reasoning-effort <reported-effort>` only when observed. For figures add
`--image-id <id>`. A recording failure is a reporting limitation; retain its
error in `.work/execution_error.txt`, preserve checkpoints and continue without
chat narration. Never invent observed model metadata.

Figure workers may run concurrently within available capacity; each gets one
image and a distinct text output. All other stages are sequential. Merge all
figure text before analysis. Verification uses `fork_turns="none"` even if
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
