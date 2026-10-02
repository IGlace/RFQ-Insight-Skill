# Claude adapter (Claude Code, Claude Desktop Code, Claude Desktop Cowork)

Use this adapter whenever the host is a Claude application: Claude Code in a
terminal or IDE, the Code experience in Claude Desktop, or a Cowork session in
Claude Desktop. All three run the same skill; the Python engine never calls an
AI API and needs no API key. The run needs local command execution, file
writes, image reading and fresh native Agents (subagents).

## Dispatch each model stage

1. Run `scripts/stage_request.py "<folder>" --host claude --stage
   <stage>` with the bootstrap interpreter. Stages are `analysis`,
   `verification`, `slides`, and `figures`; figures also need `--image-id <id>`.
2. Parse the JSON. Retain an existing figure transcription when
   `reuse_existing` is true. Otherwise create the output's parent directory
   and start a **fresh** native Agent with `subagent_type="general-purpose"`,
   `model` set to the request's `model`, and a prompt containing **only** its
   `message`. Do not pass the parent chat, analysis reasoning or full skill.
3. The routes in `references/platforms/models.json` are `opus` for analysis,
   verification and slides, `sonnet` for figures, and `haiku` only for optional
   support tasks. Pass the alias as the Agent's `model` where the host accepts
   one. If the host offers no per-worker model choice (some Cowork builds), run
   the worker on the host's current model instead of stopping, and leave the
   actual model unknown in the record. Never ask the user to choose a model and
   never mention routing in chat.
4. Wait for completion and validate the checkpoint using the shared workflow.
   Send only validation errors back to that stage's worker, keeping its model.
   Count the first attempt toward the shared three-attempt limit. Verification
   starts in a fresh Agent, never by resuming the analysis worker.
5. Record completion with `scripts/record_execution.py`. A configured model
   alias is a request, not proof of the resolved model version. Leave the
   actual model unknown unless the host reports it.

Record syntax: `scripts/record_execution.py "<folder>" --host claude --stage
<stage> --mode isolated`, adding `--actual-model <reported-id>` only when
observed, and `--image-id <id>` for figures. A recording failure is a reporting
limitation; retain its error in `.work/execution_error.txt`, preserve checkpoints
and continue without chat narration. Never invent observed model metadata.

The coordinator runs scripts; the workers read inputs and write their result.
Figures may run concurrently within host capacity, each with one image and one
text output. Merge them all before analysis. Other stages run sequentially.
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
Haiku support is limited to already-established facts supplied by
the coordinator, such as a bounded wording task. It does not analyze documents,
verify claims, plan slides or transcribe RFQ figures. Python continues to handle
mechanical operations without model calls.
