# Validation and cross-host acceptance

## What the repository proves (2026-10-27, plugin 1.2.0)

- `pytest tests -q` passes offline: the renderer's pagination and the date
  parser; the integrity of the shipped template `assets/avl_template.pptx`
  (no slides, no slide parts, 13.333 in x 7.5 in, the "Only Title", cover and
  final-slide layouts present, no media part above 1 MB, no document metadata
  or author names); the deck frame on the master and the footer identity
  (`<author> | <department> | <date> |`) with its resolution order: argument,
  environment, config file, fallback; the slide wording and format rules
  (`Opportunity Info (cont.)`, the `Definition` header, `not available` in
  prose, truncated timeline cards with the `Milestones:` notes block, solid
  connectors with the `(inferred)` tag beside the party name, codeless
  deduction lines); the language gate on German, French, Italian, Spanish,
  English and mixed fields, and the faithfulness gate's acceptance of
  `English (Original)`; the `intake` command on a temporary root (`done`,
  `exists`, `add`, `replace`, path containment); the extractors, including
  Outlook `.msg` mails built at test time by `tests/msgfile.py` with a PDF
  attachment and a nested mail, the attachments as package documents and
  their rows beneath the mail in Source Material; the bootstrap stamp; the
  approval hook; the four plugin manifests and the two marketplace manifests;
  the invariants between the prompts and the Python catalogue (the twelve
  sections, the deduction rules of the analysis and follow-up prompts, the
  prompt files each worker reads, the eleven skill areas and their team codes
  in the knowledge file); and a smoke run that copies the plugin to an
  unrelated location and drives `rfq_run.py` on the synthetic package, with a
  cover mail added, through extraction, the figure dispatch and the analysis
  dispatch on both the Claude and the Codex route.
- `claude plugin validate --strict plugins/rfq-insight` and
  `claude plugin validate --strict .` pass (plugin manifest, marketplace
  manifest and skill frontmatter).
- The upstream project replays complete stored runs through scoring, slide
  parsing, rendering and the quality checks; those fixtures are real customer
  analyses and stay out of this repository.

None of this certifies live host or model behaviour.

## Live acceptance per host

Run this once per host (Claude Desktop Cowork, Claude Code, Codex) before
claiming equivalent findings there.

1. Install the plugin as described in `INSTALL.md`. Copy `examples/synthetic-rfq`
   into a fresh working folder per host. Never run two hosts concurrently in one
   RFQ folder.
2. Ask the host to analyse the folder and let the whole workflow finish.
   Confirm the chat contains only the PowerPoint link, that all twelve canonical
   sections appear (Source Material last, the hidden methodology slide after it), that the deck opens in PowerPoint, and that the run report
   in `output/` lists valid evidence filenames.
3. Confirm the deck finds the four-versus-six module discrepancy and the
   2024-versus-2025 standard-version discrepancy, citing the relevant clauses,
   and flags the unlimited revision obligation, the shared interface approval
   (an amber `Joint` cell) and the missing shipping owner. It must not invent a
   production volume or the contents of ETS-42.
4. Confirm timing uses the stated dates and customer phase names, that every
   slide's notes start with `Confidence: <Band>` and list the sources by file,
   that deduction lines carry no rule code, and that no slide shows a numeric
   score. Confirm every slide sits on the AVL master: the title in the
   master's title style, `Internal / <n>` on the left of the footer and
   `<author> | <department> | <date> |` with the logo on the right, using the
   author and department configured for the host. Confirm all answer text is
   English. Compare facts, citations and bands, not exact wording, slide count
   or PPTX bytes.
5. Add an invented figure with a date or number that appears nowhere in the
   text. Check that it is transcribed into `output/.work/corpus.json` and
   therefore visible to the verifier. Repeat with an unreadable figure and
   confirm the report records it as unread.
6. Run `rfq_run.py timing <folder>`: the analysis and verification requests
   name Opus (or GPT-6.1 Sol, analysis at high reasoning); figures name Sonnet
   (or GPT-6.1 Sol). Where the host reports the actual model, it must match;
   where it cannot choose a worker's model, the actual model stays null and
   the run still completes. Every verification request must name only the
   verifier prompt, its partition's `claims.json` and `corpus.txt`.
7. Interrupt after analysis, then resume in another host using the same
   folder. Verify reuse of checkpoints and figure transcriptions. Repeat after
   verification has finished but before the deck exists.
8. Exercise an unavailable image tool and an unavailable worker. Each must stop
   with one short sentence and no fallback offer.
9. Test a path containing spaces, an existing deck, an unreadable input and a
   package above the corpus-size gate. Existing outputs survive unchanged; a new
   pair gets the next numeric suffix; unreadable inputs and excessive size stop
   the run without asking to skip content; model-stage repairs stop after three
   attempts.
10. Omit the opportunity name and confirm it defaults to the folder name.
    Confirm no question, summary, report link or follow-up offer appears in
    chat at any point (the two upload questions of step 11 excepted).
11. Attach the synthetic package's files in chat without naming a folder.
    The host must ask once, "Which folder name should I use for this RFQ?",
    and nothing else; after the answer the files land in `<root>/<name>`
    (`RFQ_INSIGHT_ROOT`, `~/RFQs`, or the connected folder in Cowork) and the
    run proceeds in the same turn. Attach them again with the same name: the
    host must ask once whether to add to or replace the existing folder, and
    `add` must keep the earlier files (new copies get a numeric suffix) while
    `replace` must empty the folder, its `output/` included, before copying.
12. Put an Outlook `.msg` with a PDF attachment into the package. The mail's
    text and the attachment's content must both reach the analysis; Source
    Material must list the mail with the attachment directly beneath it,
    marked `↳ <attachment>` on the slide as well as in the table, and
    citations to the attachment must name it `<mail>.msg › <attachment>`. A mail attached to the mail must be listed as skipped
    (nested e-mail).

Accept a host after its run meets these criteria and a reviewer has checked
factual coverage and evidence against the synthetic package. A real customer
comparison can be run privately under the existing data-handling rules; never
commit a real RFQ or its outputs.
