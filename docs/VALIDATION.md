# Validation and cross-host acceptance

## What the repository proves (2026-10-02)

- `pytest tests -q` passes offline: the ported renderer, sanitizer, schema,
  preprocessor and date parser; the extractors and image filter; the stage
  scripts, validators and quality checks; routing boundaries; the plugin and
  marketplace manifests; and an end-to-end smoke run that copies the plugin to
  an unrelated location, starts a fictional RFQ on the Claude route and
  resumes it on the Codex route through verification, deck generation and
  evaluation with canned model responses.
- `claude plugin validate --strict plugins/rfq-insight` and
  `claude plugin validate --strict .` pass (plugin manifest, marketplace
  manifest and skill frontmatter).
- The prompts, knowledge files, schema, sanitizer, preprocessor and renderer
  are byte-equivalent to the container app's, apart from the documented
  `Joint` ownership addition and the renderer's date parser living in
  `rfq/dates.py`.

None of this certifies live host or model behaviour.

## Live acceptance per host

Run this once per host (Claude Desktop Cowork, Claude Code, Codex) before
claiming equivalent findings there.

1. Install the plugin as described in `INSTALL.md`. Copy `examples/synthetic-rfq`
   into a fresh working folder per host. Never run two hosts concurrently in one
   RFQ folder.
2. Ask the host to analyse the folder and let the whole workflow finish.
   Confirm the chat contains only the PowerPoint link, that all eleven canonical
   sections appear, that the deck opens in PowerPoint, and that the run report
   in `output/` lists valid evidence filenames.
3. Confirm the deck finds the four-versus-six module discrepancy and the
   2024-versus-2025 standard-version discrepancy, citing the relevant clauses,
   and flags the unlimited revision obligation, the shared interface approval
   (an amber `Joint` cell) and the missing shipping owner. It must not invent a
   production volume or the contents of ETS-42.
4. Confirm timing uses the stated dates and customer phase names. Compare
   facts, citations and confidence, not exact wording, slide count or PPTX
   bytes.
5. Add an invented figure with a date or number that appears nowhere in the
   text. Check that it is transcribed into `output/.work/corpus.json` and
   therefore visible to the verifier. Repeat with an unreadable figure and
   confirm the report records it as unread.
6. Inspect `output/.work/execution.json`: analysis, verification and slides
   request Opus (or GPT-6 Sol); figures request Sonnet (or GPT-6 Sol). Where the
   host reports the actual model, it must match; where it cannot choose a
   worker's model, `actual_model` stays null and the run still completes.
   Verification must have run in a fresh worker whose request named only the
   verifier prompt, `claims.json` and `corpus.txt`.
7. Interrupt after analysis, then resume in another host using the same
   folder. Verify reuse of checkpoints and figure transcriptions. Repeat after
   `plan_input.json` exists but before `slide_plan.json` exists.
8. Exercise an unavailable image tool and an unavailable worker. Each must stop
   with one short sentence and no fallback offer.
9. Test a path containing spaces, an existing deck, an unreadable input and a
   package above the corpus-size gate. Existing outputs survive unchanged; a new
   pair gets the next numeric suffix; unreadable inputs and excessive size stop
   the run without asking to skip content; model-stage repairs stop after three
   attempts.
10. Omit the opportunity name and confirm it defaults to the folder name.
    Confirm no question, summary, report link or follow-up offer appears in
    chat at any point.

Accept a host after its run meets these criteria and a reviewer has checked
factual coverage and evidence against the synthetic package. A real customer
comparison can be run privately under the existing data-handling rules; never
commit a real RFQ or its outputs.
