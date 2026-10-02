# RFQ Insight — a plugin for Claude and Codex

Turn a folder of RFQ documents into the AVL-branded RFQ Insight PowerPoint
deck. The plugin runs a fixed workflow without questions or progress
narration, returns the deck link, and stops. A JSON run report is written next
to the deck for validation and recovery; it is never shown in chat.

Point it at the package exactly as the customer sent it — PDFs, Word, Excel,
PowerPoint, spreadsheets, drawings, subfolders and all — and it answers the
eleven fixed questions a sales manager or chief engineer needs in order to
decide whether and how to bid.

```
You:  analyse the RFQ package in RFQs\Acme_V6
```

```
<folder>\output\Acme_V6_RFQ_Analysis.pptx    the deck (the only thing returned)
<folder>\output\Acme_V6_RFQ_Analysis.json    internal run report
<folder>\output\.work\                       checkpoints for resume
```

One plugin, one skill, four hosts:

| Host | Where it runs | Install |
|---|---|---|
| Claude Desktop **Cowork** | the sandboxed Cowork VM, on the connected folder | Customize → Plugins → Add marketplace (this repository) |
| Claude Desktop Code / Claude Code | the user's machine | `claude plugin marketplace add IGlace/RFQ-Insight-Skill` |
| Codex CLI / IDE / desktop app (Codex and Work modes) | the user's machine | `codex plugin marketplace add IGlace/RFQ-Insight-Skill` |

See **[INSTALL.md](INSTALL.md)** for each host and **[USAGE.md](USAGE.md)** for
the day-to-day guide. This repository is itself the marketplace: the plugin
lives in `plugins/rfq-insight/` and both the Claude marketplace manifest
(`.claude-plugin/marketplace.json`) and the Codex one
(`.agents/plugins/marketplace.json`) point at it.

---

## Why this exists

The first version of this pipeline was a Copilot Studio agent calling an Azure
Container App: OCR over every page, a hosted model, an orchestration layer, and
a deployment to keep alive. This plugin replaces all of it with one folder of
files that runs through the user's chosen AI application.

What it buys:

- **Native extraction instead of OCR.** `python-docx`, `python-pptx`,
  `openpyxl` and `pdfplumber` read the real document structure, so a
  specification table arrives as a table instead of a flattened wall of text.
  Table fidelity is the single biggest quality lever in the whole pipeline.
- **Figures are read, not guessed.** Charts, process diagrams, letterheads and
  scanned pages are transcribed by a vision worker before the analysis, so
  their content is part of the corpus every later stage reads.
- **No deployment.** No container, no endpoint, no secret to rotate. The
  deterministic parts are plain Python; the judgement parts are prompts.
- **Checkpoints instead of retries.** Every stage writes to `output/.work/`,
  so a failure costs one stage rather than the whole run.

The deterministic half is a verbatim port of the container app's own modules —
schema, sanitizer, preprocessor, renderer, quality checks — plus one deliberate
addition (the amber `Joint` owner cell in the Scope-of-Work matrix).
[docs/MIGRATION_REVIEW.md](docs/MIGRATION_REVIEW.md) compares the plugin with
the original pipeline stage by stage.

## What it produces

Eleven canonical sections, in a fixed order, with fixed titles:

| # | Section | # | Section |
|---|---|---|---|
| 1 | Commercial Info | 7 | Scope of Work and Responsibilities |
| 2 | Source Material | 8 | AVL Deliverables |
| 3 | Summary | 9 | Timing |
| 4 | Technical Product Definitions and Targets | 10 | Customer Specific Standards |
| 5 | Application Approach | 11 | Risk Detection |
| 6 | Development Phases | | |

The renderer draws them with twelve layouts, including four diagrams: a
chevron phase process, a hub-and-spoke collaboration model, a calendar-accurate
Gantt chart, and a colour-coded single-owner responsibility matrix.

Section 11 is the one that earns the deck. Everything else is factual; every
piece of judgement — schedule feasibility, contradictions between documents,
ambiguous ownership, unbounded scope — is routed there, each item naming the
clause that triggered it.

## Model routing

| Work | Claude | Codex |
|---|---|---|
| RFQ analysis | Opus | GPT-6 Sol, high reasoning |
| Independent claim verification | Opus | GPT-6 Sol, high reasoning |
| Slide planning | Opus | GPT-6 Sol, medium reasoning |
| Figure transcription | Sonnet | GPT-6 Sol, medium reasoning |
| Optional bounded wording/formatting | Haiku | GPT-6 Luna, low reasoning |
| Extraction, validation, rendering | Python | Python |

The single routing source is
`plugins/rfq-insight/skills/rfq-insight/references/platforms/models.json`.
Every model stage runs in a **fresh worker** (a Claude Agent or a Codex
`spawn_agent` with no inherited history) that receives only its prompt, its
input files and its output path. The configured model is requested whenever the
host lets a worker's model be chosen; where it does not (some Cowork builds,
some Codex builds), the worker runs on the host's current model and the run
report records the model as unknown rather than stopping. Isolation and the
verification pass are never dropped.

## How a run works

Eight internal steps, four of which need a model. The user receives only the
PowerPoint link after successful validation. Existing output files are preserved
with automatic numeric suffixes; saved progress resumes without a confirmation.

| Step | What runs | Kind |
|---|---|---|
| 1 | Resolve the supplied folder and resume saved progress | coordinator |
| 2 | `extract_corpus.py` — native parsing, image unpacking, filtering | script |
| 3 | Read every flagged figure, then `merge_image_text.py` | **model** |
| 4 | `corpus_text.py`, then the analysis against prompt v12 | **model** |
| 5 | `extract_claims.py`, an isolated verification pass, `apply_verdicts.py` | **model** (isolated) |
| 6 | `plan_input.py`, then the slide plan against prompt v11 | **model** |
| 7 | `finalize.py` — writes the deck and the run report | script |
| 8 | `evaluate.py` — twelve quality checks, then deliver the PowerPoint link | script/coordinator |

Two design choices are worth calling out.

**The figure pass happens before the analysis, not after.** Charts, process
diagrams and pasted standards tables routinely carry facts that exist nowhere
in the extractable text. Transcribing them first makes that content part of
the corpus everything downstream reads — including the verification pass — and
it is what makes a run reproducible.

**The verification pass is isolated.** It receives only the claims, the corpus
and its own prompt; it cannot see the reasoning that produced the claims. A
checker that can see why a claim was made will agree with it.

## Repository layout

```
.claude-plugin/marketplace.json     Claude marketplace (this repository)
.agents/plugins/marketplace.json    Codex marketplace (this repository)
plugins/rfq-insight/                the installable plugin
├── .claude-plugin/plugin.json      Claude plugin manifest
├── .codex-plugin/plugin.json       Codex plugin manifest
└── skills/rfq-insight/             the one skill
    ├── SKILL.md                    the provider-neutral procedure
    ├── agents/openai.yaml          Codex skill discovery metadata
    ├── scripts/
    │   ├── bootstrap.py            dependency setup, hash-pinned venv
    │   ├── stage_request.py        bounded worker requests and model routing
    │   ├── record_execution.py     requested/observed model history
    │   ├── workflow_state.py       resumable stages and archived prior outputs
    │   ├── extract_corpus.py       native parsing + image pipeline
    │   ├── merge_image_text.py     folds figure transcriptions into the corpus
    │   ├── corpus_text.py          lays the corpus out for reading
    │   ├── extract_claims.py       harvests the statements worth re-checking
    │   ├── apply_verdicts.py       applies the isolated pass's verdicts
    │   ├── plan_input.py           prepares the slide-plan input
    │   ├── finalize.py             writes the deck and the run report
    │   ├── evaluate.py             twelve quality checks
    │   ├── validate.py             schema + size gates between stages
    │   ├── render_run.py           re-render a stored report
    │   └── rfq/                    the deterministic core
    │       ├── extractors.py       per-format parsing
    │       ├── images.py           which figures earn a visual read
    │       ├── dates.py            the one date parser
    │       ├── schema.py           strict discriminated slide-plan union
    │       ├── sanitize.py         deterministic output guards
    │       ├── preprocess.py       corpus preparation
    │       └── renderer.py         twelve layouts, python-pptx
    └── references/
        ├── sections.md             the eleven canonical sections
        ├── prompts/                three original prompts + figure transcription
        ├── platforms/              host adapters and one model policy
        └── knowledge/              eight domain reference files

tools/package_plugin.py             zip the plugin for archive-based installs
examples/synthetic-rfq/             fictional input for acceptance runs
tests/                              regression and portability tests
docs/MIGRATION_REVIEW.md            plugin vs. original pipeline, stage by stage
docs/VALIDATION.md                  what is tested and the live acceptance checklist
INSTALL.md                          installation per host
USAGE.md                            the day-to-day guide
```

## Tests

```bash
python -m pip install -r requirements-dev.txt
pytest tests -q
claude plugin validate --strict plugins/rfq-insight
claude plugin validate --strict .
```

Tests cover the renderer's layout and pagination behaviour, the extractors,
the image filter, the schema and sanitizer guards, the date parser, quality
checks, routing boundaries, the plugin manifests, relocation of the installed
plugin and checkpoint reuse across hosts.

The upstream project also carries a **golden-run regression suite** that
replays two complete stored analyses and asserts the ported schema, sanitizer,
renderer and evaluator reproduce the container app's output exactly. Those
fixtures are real customer RFQ analyses, so they are **not** in this
repository — see [Confidentiality](#confidentiality).

## Confidentiality

An RFQ package is commercially sensitive: customer requirements, named
contacts, pricing, scope, and usually an NDA.

- `RFQs/`, `**/output/` and `**/.work/` are gitignored. Never commit a real
  package or its generated deck — the deck carries the same content in
  condensed form.
- The golden-run fixtures and the one test that consumes them are excluded
  from this repository because they contain real analyses, including customer
  email addresses and programme names.
- Every example and test fixture here uses invented names (`Acme`,
  `Northwind`). If you fork this and add fixtures, keep it that way.

## Configuration worth knowing

The tuning surfaces are deliberately small and documented in place:

- `rfq/images.py` — four constants decide which figures earn a visual read: a
  minimum size, a repeat threshold for page furniture, and a cap per run. They
  are set conservatively, because a missed chart is a wrong answer while a
  transcribed logo is a few wasted seconds.
- `rfq/extractors.py` — `RENDER_DPI` and the PDF figure floor. Both were
  raised after measurement: 150 dpi rendered equipment tags illegible, and the
  floor had to come down to label size to catch a standard's version number
  rendered as a picture.
- `references/prompts/` — the three prompts. They are versioned, and
  `tests/test_invariants.py` fails if a prompt and the code disagree about the
  canonical sections or the corpus format.
- `references/platforms/models.json` — model assignments per host. Bump the
  plugin version in both manifests after changing it so installed copies update.

## Status

The deterministic pipeline is in use. The plugin passes its offline test suite
and both manifest validators. Live acceptance in each host with representative
RFQs (see [docs/VALIDATION.md](docs/VALIDATION.md)) remains necessary before
claiming equivalent findings across hosts. Known limitations:

- `.msg` (Outlook) files are skipped by design.
- A figure below the page-area floor is not read; the corpus says so
  explicitly rather than dropping it silently.
- The Scope-of-Work matrix supports more phase columns than it can render
  comfortably: past roughly five phases the column headers wrap.
- The first run on a machine (or a fresh Cowork sandbox) installs the document
  libraries from PyPI, which needs package-index access.

## Licence

No licence file is included — add the one your organisation requires before
publishing.
