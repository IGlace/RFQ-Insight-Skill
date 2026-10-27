# Changelog

## Unreleased

- Client requirements of 15.10.2026: Products (%) and Skills (%) moved to their own slide with their own rating (rules P1/P2); a rating is capped by what the content is (decided or inferred: Medium at best, estimated: Low); every slide's notes say whether it was extracted or inferred and whether anything had to be settled; a hidden Confidence Scoring Methodology slide closes the deck; Source Material cites "Not cited" instead of a dash; empty plain-table cells read "Info not available".
- Confidence is shown as High / Medium / Low only. The chip, the notes, the "(cont.)" notes, follow-up lines and comparisons no longer show a score such as `6/10`; the score stays internal and in the run report. Notes start with `Confidence: <Band>`, and each deduction line names the reason the rating was lowered without the points it cost. A replayed older report has its numbers removed the same way.
- Scope of Work: a task with no owner in any phase reads `N/A`; a phase the task does not run in is back to `—` (the short-lived `N/P` marker is gone and is read as `—` in older reports). The legend explains both.
- `(inferred)` is shown directly beside every inferred item, in light orange: table cells, panel items, bullets, prose, phase and party names and descriptions, the hub, timeline and Gantt steps and bars, callouts and the Opportunity Info values. A shortened phase description keeps its label.

## 1.1.0

- Codex is the primary host; the Claude adapter is unchanged in behaviour. Codex analysis runs at `high` effort, every other route at `medium`.
- Each section has a fixed mode (extracted, analysed, mixed, or built by the runner) and a confidence score out of 10 computed by Python from the deductions the analysis declares against a fixed rule catalogue. Bands: High 7–10, Medium 4–6, Low 1–3. The chip reads `Medium · 6/10`.
- Notes start with `Confidence N/10 (Band)`, one line per deduction, a `Check:` line and an optional `Shown:` line, then the sources. The free-text confidence reason is gone.
- Added a faithfulness gate: standards, dates, number+unit pairs, phase names, owner cells, deliverable ids and party names must occur in the corpus; three repairs, then V3 deductions.
- Verifier v3 checks absence, derived, stated and trigger claims (up to 48 per run, partitions of eight, in parallel); refuted verdicts become V1 deductions; an ambiguous verdict is reported on the `Check:` line only.
- Prompts: analysis v14, slide plan v14 (fallback only), verifier v3, figures v3 (one `.txt` per picture), follow-up v2 (mode and deductions per answer).
- Slides are parsed from the analysis markdown in Python; the slide worker runs only when a section does not parse. Source Material is built by the runner. `(inferred)` stays visible in amber.
- `next --completed/--failed` records worker results and advances in one call.
- Deck render time fell from about 6 s to about 0.2 s. Comparisons show section scores side by side.
- Runs made before the scoring still render with their stored notes; `add-followups` on them asks for a new analysis first.
- Rules that priced honest reporting (contradictions, evidence limits, unnamed contractor, estimated splits) were removed on the client's decision.

## 1.0.2

- Show plugin authors in the Asset Store.

## 1.0.1

- Standardize plugin information in the Asset Store.

## 1.0.0

- Merged the rewritten runtime into the repository with a ported test suite and updated documentation (2026-10-14).

- Removed client product-picture slides, moved complete file/section/page references into content-slide notes, and simplified confidence explanations without changing the section rating policy.

- Added coordinator timing, geometry-verified PDF table deduplication, balanced figure scheduling and partitioned isolated verification with checked resume receipts.
- Added current-evidence source IDs, scoped retries and an optional lossless typed slide-planning path; source page/chapter details and section notes remain preserved.
- Added exact Python evidence factoring for oversized packages while retaining the existing analysis ceiling and complete original verification corpus.
- Preserved complete verifier claim context and source risks on worker fallback; long diagram callouts now continue on readable pages with section notes only on the first page.
- Updated Codex Sol routes to 6.1; analysis and verification retain high effort.

- Added a fixed workflow that analyses an RFQ package folder (PDF, Word, Excel, PowerPoint, text, CSV and images) and answers the twelve RFQ Insight sections.
- Added literal figure transcription and isolated claim verification against the extracted corpus.
- Added generation of the AVL-branded PowerPoint deck and an internal run report with quality checks.
- Added Claude and Codex host adapters with per-stage model routing and resumable checkpoints.
- Added a one-time notice that lets the user choose auto or full-access mode for the current session instead of approving each step; the plugin itself makes no permission decisions.
