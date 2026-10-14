# Validation and cross-host acceptance

## What the repository proves (2026-10-14)

- `pytest tests -q` passes offline: the extractors (incl. Word chapter
  markers and PDF table de-duplication), corpus format and source catalogue,
  the figure filter, batching and merge, the claim harvest and verdict
  application, source locators, the slide-plan contract (`SECTION_SHAPES`)
  and sanitiser, the renderer's layouts, pagination and speaker notes,
  delivery and file naming, the quality gate, the stage machine with its
  resume and attempt rules, verification partitions and receipts, the
  Salesforce account lookup, follow-ups, comparison decks, the plugin and
  marketplace manifests, and an end-to-end smoke run that copies the plugin to
  an unrelated location and drives `rfq_run.py next` through every stage with
  canned worker outputs.
- `claude plugin validate --strict plugins/rfq-insight` and
  `claude plugin validate --strict .` pass (plugin manifest, marketplace
  manifest and skill frontmatter).

None of this certifies live host or model behaviour.

## Live acceptance per host

Run this once per host (Claude Desktop Cowork, Claude Code, Codex) before
claiming equivalent findings there.

1. Install the plugin as described in `INSTALL.md`. Copy `examples/synthetic-rfq`
   into a fresh working folder per host. Never run two hosts concurrently in one
   RFQ folder.
2. Ask the host to analyse the folder and let the whole workflow finish.
   Confirm the chat contains the permission notice and the PowerPoint link
   and nothing else, that all twelve canonical sections appear once each in
   order, that the deck opens in PowerPoint, that every content slide has
   speaker notes starting with the confidence rating (first slide of a
   section) or `Sources:` (later pages), and that the Opportunity Info slide
   shows the Guidance vocabulary values and the Salesforce account/KAM (or
   "Info not available" with a Document Risk explaining why).
3. Confirm the deck finds the four-versus-six module discrepancy and the
   2024-versus-2025 standard-version discrepancy (named in the notes'
   sources), and flags the unlimited revision obligation, the shared interface
   approval (an amber `Joint` cell) and the missing shipping owner. It must not
   invent a production volume or the contents of ETS-42. Collaboration
   Approach must list Northwind and AVL and state that no further parties are
   named.
4. Confirm timing uses the stated dates and customer phase names. Compare
   facts, citations and confidence, not exact wording or PPTX bytes. Confirm
   no section has more plan slides than its row in the Slide prompt's
   SECTION SLIDE SHAPES table.
5. Add an invented figure with a date or number that appears nowhere in the
   text. Check that it is transcribed into `output/.work/corpus.json`, that
   `output/.work/image_text/<id>.json` carries a classification, and that the
   fact reaches the verifier. Repeat with an unreadable figure and confirm the
   report records it as unread.
6. Inspect `output/.work/execution.json` and `rfq_run.py timing <folder>`:
   analysis, verification, slides and follow-ups request Opus (or GPT-6.1 Sol);
   figures request Sonnet (or GPT-6.1 Sol). Where the host reports the actual
   model, it must match; where it cannot choose a worker's model, the actual
   model stays null and the run still completes. Each verification partition
   must have run in a fresh worker whose request named only the verifier
   prompt, its claims subset and `corpus.txt`.
7. Interrupt after analysis, then resume in another host using the same
   folder (`rfq_run.py next` with the other `--host`). Verify reuse of
   checkpoints and figure transcriptions. Repeat after `plan_input.json`
   exists but before `slide_plan.json` exists, and once after deleting
   `verification_receipt.json` (verification must run again).
8. Exercise an unavailable image tool and an unavailable worker. Each must stop
   with one short sentence and no fallback offer.
9. Test a path containing spaces, an existing deck, an unreadable input and a
   package above the corpus-size gate. Existing outputs survive unchanged; a new
   pair gets the next numeric suffix; unreadable inputs stop the run without
   asking to skip content; an oversized package is either factored into the
   evidence ledger or blocked with the exact sentence; model-stage repairs stop
   after three attempts.
10. Omit `--project` and confirm the cover shows the analysis' opportunity
    name. Ask a follow-up question and confirm the chat shows the answer plus
    a `Sources:` line only; ask to add it and confirm a second deck with an
    "Additional Information" section before Source Material. Run a comparison
    of two folders and confirm the comparison deck. Confirm no question,
    summary, report link or follow-up offer appears in chat at any point.
11. On a Windows host with Word installed, confirm Word sources in the notes
    carry page numbers; on any other host confirm they say "Page: unavailable;
    find the section named above."

Accept a host after its run meets these criteria and a reviewer has checked
factual coverage and evidence against the synthetic package. A real customer
comparison can be run privately under the existing data-handling rules; never
commit a real RFQ or its outputs.
