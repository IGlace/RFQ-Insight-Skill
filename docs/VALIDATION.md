# Validation and cross-host acceptance

## What the repository proves (2026-10-14)

- `pytest tests -q` passes offline (about 1,100 tests): the extractors (incl.
  Word chapter markers and PDF table de-duplication), corpus format and
  source catalogue, the figure filter, batching and merge, the section modes
  and rule catalogue, scoring, bands and the notes format, the faithfulness
  gate and its V3 fallback, the claim harvest and verdict deductions, source
  locators, the markdown-to-slide parser and its round trip, the slide-plan
  contract (`SECTION_SHAPES`) and sanitiser, section 12, the renderer's
  layouts, chip, pagination and speaker notes, delivery and file naming, the
  quality gate, the stage machine with its resume and attempt rules and the
  `next --completed/--failed` bookkeeping, verification partitions and
  receipts, the Salesforce account lookup, follow-ups (mode, deductions,
  the pre-scoring block), comparison decks, the plugin and marketplace
  manifests, and an end-to-end smoke run that copies the plugin to an
  unrelated location and drives `rfq_run.py next` through every stage with
  canned worker outputs.
- `claude plugin validate --strict plugins/rfq-insight` and
  `claude plugin validate --strict .` pass (plugin manifest, marketplace
  manifest and skill frontmatter).

None of this certifies live host or model behaviour, and no live run time
was measured here.

## Live acceptance per host

Run this once per host (Codex first, then Claude Code and Claude Desktop
Cowork) before claiming equivalent findings there.

1. Install the plugin as described in `INSTALL.md`. Copy `examples/synthetic-rfq`
   into a fresh working folder per host. Never run two hosts concurrently in one
   RFQ folder.
2. Ask the host to analyse the folder and let the whole workflow finish.
   Confirm the chat contains the permission notice and the PowerPoint link
   and nothing else, that all twelve canonical sections appear once each in
   order, and that the deck opens in PowerPoint. Confirm that the
   Opportunity Info slide shows the Guidance vocabulary values and the
   Salesforce account/KAM (or "Info not available" with a Document Risk
   explaining why).
3. Confirm the confidence on every section: the chip reads `<Band> · N/10`
   and the first slide's notes start with `Confidence N/10 (<Band>)`,
   followed only by deduction lines (`-<points>  <code>  <rule>: <items> (<basis>)`)
   or one `No deductions: …` line, one `Check:` line, an optional `Shown:`
   line, and then `Sources:`. Later pages of a section carry `Sources:` only.
   Check that each score equals 10 minus the listed points (floor 1) and that
   section 1 is not lowered for its classifications or splits.
4. Confirm section 12 (Source Material) was built by the runner: one row per
   file with `File | Type | Read | Used by sections`, and P12.1/P12.2 lines in
   its notes for partly read or skipped files.
5. Confirm the deck finds the four-versus-six module discrepancy and the
   2024-versus-2025 standard-version discrepancy (as G1 deductions or Document
   Risks with sources), and flags the unlimited revision obligation, the
   shared interface approval (an amber `Joint` cell) and the missing shipping
   owner. It must not invent a production volume or the contents of ETS-42.
   Collaboration Approach must list Northwind and AVL and state that no
   further parties are named. Inferred items in extracted sections keep an
   amber `(inferred)` tag.
6. Confirm timing uses the stated dates and customer phase names. Compare
   facts, citations and scores, not exact wording or PPTX bytes. Confirm no
   section has more plan slides than its row in `SECTION_SHAPES`.
7. Confirm no slide worker ran: `output/.work/execution.json` has no `slides`
   request. Plant a section that breaks its markdown shape (e.g. a ragged
   section 7 table) in a copy and confirm the slide worker then runs as the
   fallback.
8. Plant an invented standard in section 10 and an invented date in section 9
   of a stored analysis and run `next` again: the faithfulness gate must send
   a repair; after three attempts the misses must appear as V3 deductions.
9. Add an invented figure with a date or number that appears nowhere in the
   text. Check that it is transcribed into `output/.work/image_text/<id>.txt`
   (one file per picture, no classification file), merged into
   `output/.work/corpus.json`, and that the fact reaches the verifier. Repeat
   with an unreadable figure and confirm the report records it as unread.
10. Inspect `output/.work/execution.json`: on Codex, analysis requests effort
    `high` and verification, figures and follow-up `medium`. Where the host
    reports the actual model, it must match the route; where it cannot choose
    a worker's model, the actual model stays null and the run still
    completes. Each verification partition (at most eight claims, at most 48
    claims in all) must have run in a fresh worker whose request named only
    the verifier prompt, its claims subset and `corpus.txt`. Confirm the
    coordinator advanced with `next --completed/--failed` and no separate
    `event` call per worker.
11. Record the timing table from `rfq_run.py timing <folder>` per host:

    | Host | figures | analysis | verification | slides | finalize + evaluate | total |
    |---|---|---|---|---|---|---|
    | Codex | | | | | | |
    | Claude Code | | | | | | |
    | Cowork | | | | | | |

    Null intervals mean the host reported no `started` observation; write
    "not observed", never an estimate.
12. Interrupt after analysis, then resume in another host using the same
    folder (`rfq_run.py next` with the other `--host`). Verify reuse of
    checkpoints and figure transcriptions. Repeat after `plan_input.json`
    exists but before `slide_plan.json` exists, and once after deleting
    `verification_receipt.json` (verification must run again).
13. Exercise an unavailable image tool and an unavailable worker. Each must
    stop with one short sentence and no fallback offer.
14. Test a path containing spaces, an existing deck, an unreadable input and a
    package above the corpus-size gate. Existing outputs survive unchanged; a
    new pair gets the next numeric suffix; unreadable inputs stop the run
    without asking to skip content; an oversized package is either factored
    into the evidence ledger or blocked with the exact sentence; model-stage
    repairs stop after three attempts.
15. Omit `--project` and confirm the cover shows the analysis' opportunity
    name. Ask a follow-up question and confirm the chat shows the answer plus
    a `Sources:` line only; ask to add it and confirm a second deck with an
    "Additional Information" section before Source Material whose chip carries
    the lowest score of its answers and whose notes list each answer's
    deductions. Run `add-followups` on a run made before the scoring and
    confirm it stops with "The RFQ analysis predates the current scoring; run
    the analysis again before adding follow-ups." Run a comparison of two
    folders and confirm the comparison deck shows the scores side by side.
    Confirm no question, summary, report link or follow-up offer appears in
    chat at any point.
16. On a Windows host with Word installed, confirm Word sources in the notes
    carry page numbers; on any other host confirm they say "Page: unavailable;
    find the section named above."

Accept a host after its run meets these criteria and a reviewer has checked
factual coverage and evidence against the synthetic package. A real customer
comparison can be run privately under the existing data-handling rules; never
commit a real RFQ or its outputs.
