# Prompts

Three original prompts, copied unchanged from the Azure Container App, plus
the figure-transcription instructions extracted from the shared workflow:

| File | Stage |
|---|---|
| `RFQ_QA_Extraction_Prompt_v12.md` | analysis — the 11 canonical sections |
| `RFQ_Slide_Plan_Prompt_v11.md` | slide plan |
| `RFQ_Claim_Verifier_Prompt_v2.md` | the isolated verify pass |
| `RFQ_Figure_Transcription_Prompt_v1.md` | literal image transcription |

Two things to know before editing any of them.

**They were tuned against OCR-garbled input.** The extraction is native
now, so the garbled-table reconstruction protocol and the OCR-misread
guidance are rarely-used safety nets rather than load-bearing rules. They
are kept verbatim under behavioural parity. Re-tuning them for clean input
is a known, deliberate deferral — not a bug.

**They were tuned against one model family.** v12 is 134 lines written
against recorded failure modes. It will run anywhere; whether it produces
a client-acceptable deck elsewhere is an empirical question that needs its
own test pass.

Both hosts use these same files in the shared plugin. Model and tool differences belong
in `../platforms/`, not in copies of the domain prompts. The isolated verifier
receives only its prompt, claims and the delimited corpus. The slide planner
receives only its prompt and `plan_input.json`.

After changing a prompt, run `scripts/evaluate.py` over a stored run report
for every package you have, and compare the decks by eye. The quality gates
catch structure, not judgement.
