# RFQ Insight — a plugin for Claude and Codex

Turn a folder of RFQ documents into the AVL-branded RFQ Insight PowerPoint
deck. The plugin runs a fixed workflow without questions or progress
narration, returns the deck link, and stops. A JSON run report is written next
to the deck for validation and recovery; it is never shown in chat.

Point it at the package exactly as the customer sent it — PDFs, Word, Excel,
PowerPoint, spreadsheets, drawings, subfolders and all — and it answers the
twelve fixed sections a sales manager or chief engineer needs in order to
decide whether and how to bid. Afterwards it answers follow-up questions from
the saved corpus and can compare two analysed RFQs.

```
You:  analyse the RFQ package in RFQs\Acme_V6
```

```
<folder>\output\RFQ Insight_<Opportunity name>_<DDMMYYYY>.pptx   the deck (the only thing returned)
<folder>\output\RFQ Insight_<Opportunity name>_<DDMMYYYY>.json   internal run report
<folder>\output\.work\                                          checkpoints, corpus, follow-up history
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

## What it produces

Twelve canonical sections, in a fixed order, with fixed titles, one slide
each (the renderer adds continuation pages only when a table or list really
overflows):

| # | Section | # | Section |
|---|---|---|---|
| 1 | Opportunity Info | 7 | Scope of Work and Responsibilities |
| 2 | Description | 8 | AVL Deliverables |
| 3 | Technical Product Definitions and Targets | 9 | Timing |
| 4 | Application Approach | 10 | Customer Specific Standards |
| 5 | Collaboration Approach | 11 | Risk Detection |
| 6 | Development Phases | 12 | Source Material |

Section 1 is built by the application from the analysis' structured
`opportunity` object (customer, contact, due date, opportunity name, Project
type, Lead product, Technology, Industry, Products (%) and Skills (%) in the
AVL Guidance vocabulary) and the Salesforce account list in
`references/data/accounts.csv` (Account Name (Site) and KAM (PTE)).

Every content slide carries speaker notes: the section's confidence rating
with the analyst's reason, what the independent check covered, and the
complete source references (file, chapter path, page or page range). Visible
slides never show citations.

Section 11 is the one that earns the deck. Everything else is factual; every
piece of judgement — schedule feasibility, contradictions between documents,
ambiguous ownership, unbounded scope — is routed there, each item naming the
clause that triggered it.

## How a run works

`scripts/rfq_run.py next <folder>` does every deterministic step itself and
stops only when a model worker is needed. The coordinator (the host's agent)
starts the requested workers, records their completion, and calls `next`
again until the runner reports `done`.

| Stage | What happens | Kind |
|---|---|---|
| extract | native parsing (`python-docx`, `python-pptx`, `openpyxl`, `pdfplumber`), chapter and page markers, image unpacking and filtering | Python |
| figures | each picture is transcribed and classified by a vision worker, up to six per request, then merged into the corpus | **model** |
| analysis | one fresh worker answers the twelve sections and the Opportunity object from prompt v13 plus the knowledge pack; oversized packages are first factored into an exact evidence ledger | **model** |
| verification | the harvested claims are judged against the corpus in isolated workers (partitions of six when there are eight or more claims); the Salesforce account is looked up | **model** (isolated) |
| slides | a fresh worker turns the answers into the slide plan from prompt v13; the validator enforces the fixed slide shape of every section | **model** |
| finalize | the deck, the run report and `deliverables.json` are written; existing outputs are never overwritten | Python |
| evaluate | the quality gate (structure, titles, phases, ownership cells, notes, sources); a failure blocks delivery | Python |

Two design choices are worth calling out.

**The figure pass happens before the analysis, not after.** Charts, process
diagrams and pasted standards tables routinely carry facts that exist nowhere
in the extractable text. Transcribing them first makes that content part of
the corpus everything downstream reads, including the verification pass.

**The verification pass is isolated.** It receives only the claims, the corpus
and its own prompt; it cannot see the reasoning that produced the claims.

## Follow-up questions and comparisons

- `rfq_run.py ask` / `answer` answer one question at a time from the saved
  corpus (re-reading the documents first when they changed) and keep the
  history in `output/.work/followups.json`; `add-followups` rebuilds the deck
  with an "Additional Information" section before Source Material.
- `rfq_run.py compare <A> <B>` diffs two finished runs section by section and
  writes a comparison deck. No model is involved.

## Model routing

| Work | Claude | Codex |
|---|---|---|
| RFQ analysis | Opus | GPT-6.1 Sol, high reasoning |
| Independent claim verification | Opus | GPT-6.1 Sol, high reasoning |
| Slide planning | Opus | GPT-6.1 Sol, medium reasoning |
| Figure transcription | Sonnet | GPT-6.1 Sol, medium reasoning |
| Follow-up questions | Opus | GPT-6.1 Sol, high reasoning |
| Optional bounded wording/formatting | Haiku | GPT-6 Luna, low reasoning |
| Extraction, validation, rendering, account lookup | Python | Python |

The single routing source is
`plugins/rfq-insight/skills/rfq-insight/references/platforms/models.json`.
Every model stage runs in a **fresh worker** that receives only its prompt,
its input files and its output paths. Where a host cannot choose a worker's
model, the worker runs on the host's current model and the run report records
the model as unknown rather than stopping.

## Permissions

The plugin ships no approval hook (removed at the client's request). Before
the first command of a run the skill sends one notice telling the user how to
let the session run without a prompt per step (auto mode in Claude Code,
`/approvals` in Codex); Cowork grants folder access once and never prompts
per command. Details per host are in [INSTALL.md](INSTALL.md#permissions).

## Repository layout

```
.claude-plugin/marketplace.json     Claude marketplace (this repository)
.agents/plugins/marketplace.json    Codex marketplace (this repository)
plugins/rfq-insight/                the installable plugin
├── .claude-plugin/plugin.json      Claude plugin manifest
├── .codex-plugin/plugin.json       Codex plugin manifest
├── .github/plugin/plugin.json      GitHub plugin manifest (metadata only)
├── CHANGELOG.md
└── skills/rfq-insight/             the one skill
    ├── SKILL.md                    the provider-neutral procedure
    ├── agents/openai.yaml          Codex skill discovery metadata
    ├── assets/word_pages.ps1       Word page numbers through Word (Windows only)
    ├── scripts/
    │   ├── bootstrap.py            dependency setup, hash-pinned venv
    │   ├── rfq_run.py              the runner: next / ask / answer / add-followups / compare / event / timing / lookup / validate / evaluate / render / debug
    │   └── rfq/                    internal modules (never invoked directly)
    │       ├── pipeline.py, state.py, workers.py       stage machine, checkpoints, worker requests
    │       ├── extractors.py, corpus.py, figures.py    parsing, corpus, pictures
    │       ├── sources.py, verification.py             citations, claim checking
    │       ├── planning.py, schema.py, validation.py   slide plan, contracts, quality gate
    │       ├── renderer.py, delivery.py                deck and report
    │       ├── guidance.py, opportunity.py             Guidance vocabulary, Salesforce lookup
    │       ├── followups.py, comparison.py             follow-up mode, comparison decks
    │       └── dates.py, assets.py
    └── references/
        ├── sections.md             the twelve canonical sections
        ├── prompts/                analysis v13, slide plan v13, verifier v2, figures v2, follow-up v1
        ├── platforms/              host adapters and one model policy
        ├── knowledge/              nine domain reference files
        └── data/                   Guidance vocabulary and the Salesforce account list

tools/package_plugin.py             zip the plugin for archive-based installs
examples/synthetic-rfq/             fictional input for acceptance runs
tests/                              regression and portability tests
docs/CHANGE_REVIEW.md               review of the runtime rewrite (2026-10-14)
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

Tests cover the extractors and corpus format, the figure filter and merge,
the claim harvest and verification bookkeeping, source locators and the
reference catalogue, the slide-plan contract and sanitiser, the renderer's
layout and pagination behaviour, delivery and file naming, the quality gate,
the stage machine and resume rules, the Salesforce lookup, follow-ups,
comparisons, the plugin manifests, and an end-to-end smoke run of
`rfq_run.py next` with canned worker outputs.

## Confidentiality

An RFQ package is commercially sensitive: customer requirements, named
contacts, pricing, scope, and usually an NDA.

- `RFQs/`, `**/output/` and `**/.work/` are gitignored. Never commit a real
  package or its generated deck — the deck carries the same content in
  condensed form.
- `references/data/accounts.csv` is AVL's Salesforce account list with the
  KAM per account. This repository and the plugin are distributed privately
  for that reason; do not publish either.
- Every example and test fixture here uses invented names (`Acme`,
  `Northwind`). If you fork this and add fixtures, keep it that way.

## Configuration worth knowing

- `rfq/figures.py` — the constants that decide which pictures earn a visual
  read (minimum size, repeat threshold, cap of 90 per run) and the batch size.
- `rfq/extractors.py` — `RENDER_DPI`, the PDF figure floor, and heading
  detection for Word and PDF.
- `rfq/validation.py` — the corpus size limit (600,000 characters), the
  confidence-reason length limits and the quality gate.
- `references/prompts/` — the prompts; `tests/test_invariants.py` fails if a
  prompt and the code disagree about the canonical sections.
- `references/platforms/models.json` — model assignments per host. Bump the
  plugin version in the manifests after changing it so installed copies update.
- `references/data/vocabularies.json` and
  `references/knowledge/90_guidance_denominators.md` — the Guidance Document
  vocabulary; both are generated from the same workbook and must stay in sync.

## Status

The runtime rewrite of 2026-10-14 is reviewed in
[docs/CHANGE_REVIEW.md](docs/CHANGE_REVIEW.md). Known limitations:

- Word page numbers need a Windows host with Word installed; elsewhere the
  notes cite chapters and say that rendered pages are unavailable.
- `.msg` (Outlook) files are skipped by design.
- A figure below the page-area floor is not read; the corpus says so
  explicitly rather than dropping it silently.
- Long phase names make the Scope-of-Work header tall, which can push rows to
  a continuation page earlier than necessary.
- The first run on a machine (or a fresh Cowork sandbox) installs the document
  libraries from PyPI, which needs package-index access.
