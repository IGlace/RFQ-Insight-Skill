# Migration review: plugin versus the original pipeline

This compares the RFQ Insight plugin with the system it replaces — the
Copilot Studio agent (`RFQ_Agent/`) plus the Azure Container App
(`RFQ_Container_App/`) — stage by stage, and records what was carried over
verbatim, what improved, what changed, and what was deliberately dropped.
Dated 2026-10-02.

## Stage by stage

| Stage | Original pipeline | Plugin | Verdict |
|---|---|---|---|
| Intake | Copilot Studio topic asks folder name and opportunity name; SharePoint job list queues the run; email on completion | The chat request names the folder (or the Cowork working folder); opportunity name defaults to the folder name; one link in chat | Simpler by design; no email, no queue |
| File discovery | SharePoint recursive listing, nine extensions | Recursive local walk, the same nine extensions, `output/` excluded | Parity |
| Text extraction | AI Builder OCR on PDFs and images; Word/PowerPoint converted to PDF then OCR'd; Excel via an Office Script | Native parsers: `python-docx`, `python-pptx`, `openpyxl`, `pdfplumber`; tables arrive as pipe tables; speaker notes and sheet names kept | **Upgrade.** Tables were the weakest part of the old corpus |
| Figures and scans | OCR read whatever text the picture contained | Pages without a text layer are rendered at 300 dpi; embedded figures down to label size are cut out; every flagged picture is transcribed by a vision worker before analysis, and the transcription is folded back at the figure's position | **Upgrade** (charts, letterheads, pasted standards tables), with one cap: `rfq/images.py` reads at most 90 figures per run and records what it set aside |
| Unreadable files | Counted in the email, otherwise silent; a lost SOW still produced a confident deck | A named unreadable input stops the run with the filenames | **Upgrade** |
| Corpus preparation | `preprocess.py`, 600 000-character size gate | Same module byte for byte, same gate and message | Parity |
| Analysis | One Opus call; prompt v12 as system prompt, eight knowledge files as cached system blocks, corpus in the user turn; adaptive thinking; up to 64k output tokens; JSON validated against Pydantic with three attempts | One fresh Opus worker (GPT-6 Sol high on Codex) given prompt v12, the eight knowledge files, the section list and the delimited corpus as files; `validate.py` enforces the same schema with three attempts | Parity in inputs and contract. The worker now has to read the corpus through tools, so its request insists on reading every file to the end |
| Claim verification | Sonnet, claims plus full corpus, confidence capped to low on refutation | Opus (GPT-6 Sol high on Codex) in a fresh worker that never sees the analysis reasoning; same `extract_claims` and verdict rules, plus a guard that rejects a refutation without a verbatim quote | **Upgrade** (stronger model, enforced isolation) |
| Slide plan | Opus, prompt v11 | Opus, prompt v11 (routed to Sonnet in the previous packaging; corrected in this release). GPT-6 Sol medium on Codex | Parity restored |
| Sanitizer, schema, renderer | `sanitize.py`, `schema.py`, `renderer.py` | Same modules; the renderer's date parser moved to `rfq/dates.py` so the evaluator uses the same one; the `Joint` owner cell was added to the matrix, the prompts and the sanitizer together | Parity plus one deliberate improvement |
| Quality checks | `experiments/evaluate.py`, C1–C6 and W1–W6 | `scripts/evaluate.py`, same checks; a FAIL now blocks delivery | Parity, stricter gate |
| Run report | `run / analysis / slidePlan / verification`, token usage and cost per call | Same shape; `run.usage` reads "not measured"; `run.extraction` and `run.execution` (requested and observed models) added | Parity minus cost accounting, which a hosted session cannot measure |
| Output naming | `<folder>_RFQ_Analysis.{pptx,json}` on SharePoint, overwritten on requeue | `<opportunity>_RFQ_Analysis.{pptx,json}` in `<folder>/output/`, never overwritten (numeric suffixes) | Parity with safer overwrite behaviour |
| Resume | None (a failed job was requeued from scratch) | Checkpoints per stage in `output/.work/`, automatic resume, prior model outputs archived | **Upgrade** |

## What was deliberately dropped

Confirmed out of scope before the port and still out of scope:

- The deck re-cut journey (`ModifyRFQPresentation`, `GenerateFollowupPPT`),
  which was already broken against the live backend.
- `Mode` (compact/detailed) and `OptionalQuestions`, which the backend never
  read.
- The follow-up Q&A journey (`DiscussRFQAnalysis`, `AnswerRFQfollowup`). The
  run report stays in `output/` for anyone who wants to ask about it in a new
  chat, but the plugin itself ends at the deck link.
- SharePoint storage, the job state machine, requeue dialogue, completion
  emails, the chunked upload transport, the FastAPI app and the Foundry/APIM
  gateway client with its keepalive and buffered-read workarounds.

## What is genuinely different, and the risks that come with it

1. **Model calls go through the host, not an SDK.** The original pipeline
   controlled `max_tokens`, adaptive thinking and retries directly. The
   plugin asks the host for a fresh worker with a named model; the worker's
   reasoning effort and output budget are whatever the host gives it. The
   request text and the validators compensate (read everything, write the
   complete output, three attempts), but a host that quietly truncates a long
   worker response would surface as a validation failure, not a wrong deck.
2. **Prompt caching is gone.** The knowledge pack was a cached system prefix;
   now each worker reads it afresh. Cost moves from an API bill to the host's
   subscription; there is nothing to tune.
3. **Model availability varies by host.** The configured routes are Opus and
   Sonnet (Claude) and GPT-6 Sol (Codex). Where a host cannot choose a worker's
   model — some Cowork or Codex builds — the worker runs on the host's model
   and `run.execution` records the model as unknown. The previous packaging
   stopped the run in that case; this release continues, because an undelivered
   deck helps nobody and the deterministic guards still apply.
4. **Figure cap.** OCR read every page; the plugin reads every scanned page and
   every embedded figure above a small floor, but `rfq/images.py` caps the
   number of figures per run at 90. Packages with more will have the excess
   listed in the run report rather than transcribed.
5. **Cowork sandboxes may be fresh.** The document libraries install into the
   sandbox user's home on first use; a sandbox without package-index access
   cannot run until that is allowed or the host's Python already carries the
   libraries.

## Changes made in this release (2026-10-02)

- Repackaged as a marketplace plugin (`plugins/rfq-insight/` with Claude and
  Codex manifests; marketplace manifests at the repository root). The manual
  ZIP packager, PowerShell cleaner, installer runtime marker and host-specific
  skill copies are gone; one skill serves every host.
- Slide planning routed back to Opus, as in production.
- Model selection made best-effort instead of a hard stop; isolation,
  verification and image reading remain mandatory.
- Worker requests now require reading every instruction and input file to
  the end and writing the complete output, because workers read through tools
  rather than receiving the corpus in one message.
- Bootstrap accepts the host's own Python when it already has the libraries
  and the venv cannot be provisioned.
- Cowork and ChatGPT Work are named as supported hosts in the skill and docs.
- Long corpus lines are soft-wrapped so a worker reading through a file tool
  never loses the end of a paragraph or table row.
- An approval hook ships with the plugin so Claude Code and Codex do not stop
  at a permission prompt for every script; the hook approves only the
  plugin's own scripts and checkpoint writes.

## Still to confirm live

The offline suite proves the deterministic half and the contracts. The
model-driven half needs one acceptance run per host on a representative
package, using the checklist in [VALIDATION.md](VALIDATION.md), before the
plugin is declared equivalent to the original pipeline for a given host.

## Runtime rewrite (2026-10-14)

The stage-by-stage comparison above describes the first plugin release. The
runtime was then rewritten: one `rfq_run.py` state machine replaced the
fourteen coordinator-driven scripts, the deck moved to twelve sections with a
fixed one-slide shape each, source references and confidence reasons moved
into the speaker notes, the Opportunity Info slide is built from a structured
object plus the Salesforce account list, and follow-up questions and
comparison decks were added. The deliberately dropped follow-up journey listed
above is therefore back, in local form. The full change inventory, scores and
the sample-run comparison are in [CHANGE_REVIEW.md](CHANGE_REVIEW.md).
