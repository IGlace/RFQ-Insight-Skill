# Prompts

| File | Stage | Worker reads |
|---|---|---|
| `RFQ_QA_Extraction_Prompt_v14.md` | analysis — sections 1-11 with their deductions, plus the `opportunity` object (section 12 is built by the runner) | this file, `sections.md`, the nine knowledge files, `corpus.txt` (or `prepared_evidence.txt`), optionally `source_catalog.json` |
| `RFQ_Claim_Verifier_Prompt_v3.md` | isolated verification of absence, derived, stated and trigger claims, one worker per partition | this file, the partition's `claims.json`, `corpus.txt` |
| `RFQ_Figure_Transcription_Prompt_v3.md` | literal picture transcription, one `.txt` per picture | this file and up to six pictures |
| `RFQ_Slide_Plan_Prompt_v14.md` | slide plan, fallback only: runs when an answer does not parse into its fixed markdown shape | this file, `plan_input.json` |
| `RFQ_Followup_Prompt_v2.md` | one follow-up question, with its mode and deductions | this file, `corpus.txt`, `followup_question.json`, optionally `analysis.json` and `source_catalog.json` |

Things to know before editing any of them.

**The analysis prompt owns the per-section size limits and markdown shapes**
(Description 5 paragraphs, Technical Targets ~14 rows, Scope of Work ~10–18
rows, Standards 13 rows, Risks 8 per group; the fixed table headers of
sections 5, 6, 7 and 9 and the two risk panels). The runner parses those
shapes into slides; `rfq/schema.py::SECTION_SHAPES` fixes the slide shape per
section and `rfq/validation.py::check_plan` rejects anything else. Change them
together.

**The deduction catalogue is Python's.** The analysis prompt's `| code | rule
| sections |` table and the follow-up prompt's rule table list the model rules
of `rfq/schema.py::RULES` verbatim, without points; `rfq/confidence.py` scores
them. `tests/test_invariants.py` fails when the analysis prompt's table, its
section modes or its per-section rule lists drift from the schema.

**Citations are validated.** Every `sources` entry must name a corpus file and
a locator that exists in its markers (`rfq/sources.py`). The `ref_id` form
refers to `source_catalog.json`, which the runner writes next to `corpus.txt`.

**The vocabulary is generated.** Opportunity Info values are checked against
`references/data/vocabularies.json`; the prose copy for the model is
`references/knowledge/90_guidance_denominators.md`. Regenerate both from the
Guidance workbook, never edit one by hand.

**Check a prompt change on real packages.** After changing a prompt, run
`rfq_run.py evaluate` over a stored run report for every package you have and
compare the decks by eye; the tests catch table and catalogue drift only.
