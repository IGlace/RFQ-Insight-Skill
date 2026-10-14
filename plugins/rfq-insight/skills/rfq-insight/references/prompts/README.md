# Prompts

| File | Stage | Worker reads |
|---|---|---|
| `RFQ_QA_Extraction_Prompt_v13.md` | analysis — the 12 canonical sections plus the `opportunity` object | this file, `sections.md`, the nine knowledge files, `corpus.txt` (or `prepared_evidence.txt`), optionally `source_catalog.json` |
| `RFQ_Claim_Verifier_Prompt_v2.md` | isolated verification, one worker per partition | this file, the partition's `claims.json`, `corpus.txt` |
| `RFQ_Figure_Transcription_Prompt_v2.md` | literal picture transcription plus classification | this file and up to six pictures |
| `RFQ_Slide_Plan_Prompt_v13.md` | slide plan (skipped when the analysis supplies a complete typed `presentation`) | this file, `plan_input.json` |
| `RFQ_Followup_Prompt_v1.md` | one follow-up question | this file, `corpus.txt`, `followup_question.json`, optionally `analysis.json` and `source_catalog.json` |

Things to know before editing any of them.

**The analysis prompt owns the per-section size limits** (Description 5
paragraphs, Technical Targets ~14 rows, Scope of Work ~10–18 rows, Standards
13 rows, Risks 8 per group). Stage 2 presents what it is given and may not
cut; `rfq/schema.py::SECTION_SHAPES` fixes the slide shape per section and
`rfq/validation.py::check_plan` rejects anything else. Change the three
together.

**Citations are validated.** Every `sources` entry must name a corpus file and
a locator that exists in its markers (`rfq/sources.py`). The `ref_id` form
refers to `source_catalog.json`, which the runner writes next to `corpus.txt`.

**The vocabulary is generated.** Opportunity Info values are checked against
`references/data/vocabularies.json`; the prose copy for the model is
`references/knowledge/90_guidance_denominators.md`. Regenerate both from the
Guidance workbook, never edit one by hand.

**They were tuned against one model family and OCR-era input.** The
garbled-table protocol in the analysis prompt is a safety net now that
extraction is native. After changing a prompt, run `rfq_run.py evaluate`
over a stored run report for every package you have and compare the decks
by eye; `tests/test_invariants.py` only catches section-table drift.
