# RFQ Insight — a plugin for Claude and Codex

Turn a folder of RFQ documents into the RFQ Insight PowerPoint deck, built
on the AVL slide master. The plugin runs a fixed workflow without questions
about the analysis (the only questions are the two of a chat upload: the
folder name, and add or replace when it exists) and without progress
narration, returns the deck link, and stops. A JSON run report is written next
to the deck for validation and recovery; it is never shown in chat.

Point it at the package exactly as the customer sent it — PDFs, Word, Excel,
PowerPoint, spreadsheets, drawings, Outlook mails with their attachments,
subfolders and all — or attach the documents in chat, and it answers the
twelve fixed sections a sales manager or chief engineer needs in order to
decide whether and how to bid, rates each section's confidence, and verifies
its own claims in an isolated pass before the deck is built.

```
You:  analyse the RFQ package in RFQs\Acme_V6
```

```
<folder>\output\Acme_V6_RFQ_Analysis.pptx    the deck (the only thing returned)
<folder>\output\Acme_V6_RFQ_Analysis.json    internal run report
<folder>\output\.work\                       checkpoints for resume and follow-ups
```

After a run, the same folder answers follow-up questions in chat, adds those
answers to a new deck on request, and compares two finished analyses into a
comparison deck. See [USAGE.md](USAGE.md).

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
(`.agents/plugins/marketplace.json`) point at it. Release notes are in
[plugins/rfq-insight/CHANGELOG.md](plugins/rfq-insight/CHANGELOG.md).

---

## Why this exists

The first version of this pipeline was a Copilot Studio agent calling an Azure
Container App: OCR over every page, a hosted model, an orchestration layer, and
a deployment to keep alive. This plugin replaces all of it with one folder of
files that runs through the user's chosen AI application.

What it buys:

- **Native extraction instead of OCR.** `python-docx`, `python-pptx`,
  `openpyxl`, `pdfplumber` and `extract-msg` read the real document
  structure, so a specification table arrives as a table instead of a
  flattened wall of text.
  Table fidelity is the single biggest quality lever in the whole pipeline.
- **Figures are read, not guessed.** Charts, process diagrams, letterheads and
  scanned pages are transcribed by a vision worker before the analysis, so
  their content is part of the corpus every later stage reads.
- **No deployment.** No container, no endpoint, no secret to rotate. The
  deterministic parts are plain Python; the judgement parts are prompts.
- **Checkpoints instead of retries.** Every stage writes to `output/.work/`,
  so a failure costs one stage rather than the whole run.
- **Confidence you can audit.** Every section carries a High / Medium / Low
  band computed by Python from the deductions the analysis declares against a
  fixed rule catalogue, and the speaker notes say exactly why.

[docs/MIGRATION_REVIEW.md](docs/MIGRATION_REVIEW.md) compares the plugin with
the original pipeline stage by stage.

## What it produces

Twelve canonical sections, in a fixed order, with fixed titles:

| # | Section | # | Section |
|---|---|---|---|
| 1 | Opportunity Info | 7 | Scope of Work and Responsibilities |
| 2 | Description | 8 | AVL Deliverables |
| 3 | Technical Product Definitions and Targets | 9 | Timing |
| 4 | Application Approach | 10 | Customer Specific Standards |
| 5 | Collaboration Approach | 11 | Risk Detection |
| 6 | Development Phases | 12 | Source Material |

The analysis answers sections 1–11; the runner builds section 12 from the
read log, fills the Opportunity Info facts (Salesforce account and key account
manager from `references/data/accounts.csv`, the Guidance vocabulary for
project type, technologies, industries, products and skills) and adds the
estimated Products (%) / Skills (%) split as its own rated slide. Each section
has a fixed slide shape (`rfq/schema.py::SECTION_SHAPES`); the renderer draws
them with the diagram layouts the deck is known for: a chevron phase process,
a hub-and-spoke collaboration model, a calendar-accurate Gantt chart, and a
colour-coded responsibility matrix.

Section 11 is the one that earns the deck. Everything else is factual; every
piece of judgement — schedule feasibility, contradictions between documents,
ambiguous ownership, unbounded scope — is routed there, each item naming the
clause that triggered it.

### Confidence

Each section is **extracted** (copied from what the documents state),
**analysed** (reasoned over them) or **mixed**. The analysis declares its
deductions per section from the rule catalogue in `rfq/schema.py::RULES`
(inferred items, estimated values, cells placed by inference, risks without a
locatable trigger, and so on); the runner adds its own for claims the
verifier refuted or that do not occur in the corpus, and caps the score by
provenance: content the analysis had to settle or infer is Medium at best, an
estimated split is Low. The internal score out of 10 becomes the band on the
slide's chip (High 7–10, Medium 4–6, Low 1–3); no slide shows the number.
Every slide's notes start with `Confidence: <Band>`, the basis, one line per
deduction in plain English (the rule codes stay in the run report), the
contradictions found, the verifier's `Check:` line and the
complete source references grouped by file. A hidden Confidence Scoring
Methodology slide closes the deck. `(inferred)` is shown in light orange beside
every inferred item; connectors and bars are always drawn solid.

Answers are written in English whatever the language of the documents. A
phase, milestone, document or role the customer names in another language is
translated with the original in brackets on first use, e.g.
`Concept Freeze (Konzept-Freeze)`.

## Model routing

| Work | Claude | Codex |
|---|---|---|
| RFQ analysis | Opus | GPT-6.1 Sol, high reasoning |
| Independent claim verification | Opus | GPT-6.1 Sol, medium reasoning |
| Figure transcription | Sonnet | GPT-6.1 Sol, medium reasoning |
| Slide planning (fallback only) | Opus | GPT-6.1 Sol, medium reasoning |
| Follow-up questions | Opus | GPT-6.1 Sol, medium reasoning |
| Optional bounded wording/formatting | Haiku | GPT-6 Luna, low reasoning |
| Extraction, scoring, validation, slide plan, rendering | Python | Python |

Codex is the primary host. The single routing source is
`plugins/rfq-insight/skills/rfq-insight/references/platforms/models.json`.
Every model stage runs in a **fresh worker** (a Claude Agent or a Codex
`spawn_agent` with no inherited history) that receives only its prompt, its
input files and its output path. The configured model is requested whenever the
host lets a worker's model be chosen; where it does not (some Cowork builds,
some Codex builds), the worker runs on the host's current model and the run
report records the model as unknown rather than stopping. Isolation and the
verification pass are never dropped.

## Permissions

The skill's `allowed-tools` frontmatter pre-approves Python, `mkdir`, file
reads and writes and worker Agents for the turn that invokes it in Claude Code,
and the plugin ships an approval hook (`plugins/rfq-insight/hooks/`) that
pre-approves its two entry points (`bootstrap.py`, `rfq_run.py`) and
checkpoint writes in Claude Code and, after a one-time hook-trust review, in
Codex. Cowork grants folder access once and never prompts per command. The
per-host details, and the user-side settings that make a Codex run fully
silent, are in [INSTALL.md](INSTALL.md#permissions-running-without-prompts).

## How a run works

One script, `scripts/rfq_run.py`, does every deterministic step; the host's
agent only coordinates. When the documents arrive as chat attachments instead
of a folder, the skill first asks for a folder name and runs
`rfq_run.py intake --name <name> <file> ...`, which copies them into
`<root>/<name>` (root `RFQ_INSIGHT_ROOT`, else `~/RFQs`; the connected folder
in Cowork). When that folder already exists it asks once more, add or replace,
and reruns `intake` with `--mode add` or `--mode replace`. Those are the only
two questions the workflow asks. It then calls `rfq_run.py next <folder>` and
acts on the JSON status it prints:

| `status` | Meaning |
|---|---|
| `dispatch` | Start one fresh worker per request (figure jobs and verification partitions run concurrently), then call `next` again with `--completed` / `--failed` per worker. |
| `repair` | Send the request's repair message to the worker that wrote the output; the third failure comes back as `blocked`. |
| `done` | Return the PowerPoint link and stop. |
| `blocked` | Reply with the message as given and stop; progress is saved. |

Seven stages, three of which need a model:

| Stage | What runs | Kind |
|---|---|---|
| `extract` | native parsing, image unpacking and filtering, source catalogue; an Outlook `.msg` is read as its headers and body, and its attachments join the package as `<mail>.msg › <attachment>` | script |
| `figures` | every flagged picture transcribed, up to six per worker, one `.txt` each; merged back at the figure's position | **model** |
| `analysis` | sections 1–11 with their deductions and the Opportunity Info object, against prompt v15; a faithfulness gate checks that standards, dates, number+unit pairs, phase names, owners, deliverable ids and party names occur in the corpus (an English name with its original in brackets passes when either occurs), and a language gate sends any field that reads as German, French, Italian or Spanish back for repair | **model** |
| `verification` | up to 48 claims in partitions of eight, each judged in an isolated worker against `corpus.txt` only; refuted claims become deductions | **model** (isolated) |
| `slides` | the slide plan is parsed from the answers' fixed markdown shapes in Python; a worker runs only when a section does not parse | script (model fallback) |
| `finalize` | confidence scores, Salesforce account, Source Material (attachments listed beneath their mail), the deck on the AVL master and the run report | script |
| `evaluate` | quality checks over the report; a failure blocks delivery | script |

Oversized packages first undergo exact evidence factoring in Python so the
prepared representation fits the analysis limit without summarising; the
verifier always reads the original corpus. Existing output files are preserved
with numeric suffixes; saved progress resumes without a confirmation.

Two design choices are worth calling out.

**The figure pass happens before the analysis, not after.** Charts, process
diagrams and pasted standards tables routinely carry facts that exist nowhere
in the extractable text. Transcribing them first makes that content part of
the corpus everything downstream reads — including the verification pass — and
it is what makes a run reproducible.

**The verification pass is isolated.** It receives only the claims, the corpus
and its own prompt; it cannot see the reasoning that produced the claims. A
checker that can see why a claim was made will agree with it.

### After the run

- `rfq_run.py ask` / `answer` answer a follow-up question from the saved
  corpus in one fresh worker, in English, with sources and its own
  confidence; the history is kept in `output/.work/followups.json`.
  `add-followups` builds a new deck with an "Additional Information" section
  before Source Material.
- `rfq_run.py compare <folder A> <folder B>` compares the last finished runs
  of two folders (two RFQs or two revisions) into a comparison deck, section
  by section with the bands side by side, without a model worker.
- `rfq_run.py timing`, `validate`, `evaluate`, `render` and `lookup` are
  read-only inspection commands; `debug` exposes the internal steps.

## Repository layout

```
.claude-plugin/marketplace.json     Claude marketplace (this repository)
.agents/plugins/marketplace.json    Codex marketplace (this repository)
plugins/rfq-insight/                the installable plugin
├── .claude-plugin/plugin.json      Claude plugin manifest
├── .codex-plugin/plugin.json       Codex plugin manifest
├── .github/plugin/plugin.json      GitHub plugin manifest
├── asset.json                      Asset Store listing
├── CHANGELOG.md                    release notes
├── hooks/                          approval hook for the plugin's own scripts
└── skills/rfq-insight/             the one skill
    ├── SKILL.md                    the provider-neutral procedure
    ├── agents/openai.yaml          Codex skill discovery metadata
    ├── assets/avl_template.pptx    the AVL slide master every deck is built on (no slides)
    ├── assets/word_pages.ps1       native Word pagination (Windows, optional)
    ├── scripts/
    │   ├── bootstrap.py            dependency setup, hash-pinned venv
    │   ├── rfq_run.py              the runner: intake / next / ask / answer / add-followups / compare
    │   └── rfq/                    internal modules, never run individually
    │       ├── pipeline.py         the stage machine behind `next`
    │       ├── state.py            progress, attempts and archived outputs
    │       ├── intake.py           documents attached in chat copied into an RFQ folder
    │       ├── workers.py          worker requests and model routing
    │       ├── corpus.py           corpus layout, soft-wrapping, evidence factoring
    │       ├── extractors.py       per-format parsing, Outlook mails and their attachments
    │       ├── figures.py          which pictures earn a visual read
    │       ├── sources.py          source catalogue and citation checks
    │       ├── verification.py     claim harvesting, partitions, verdicts
    │       ├── confidence.py       scores and bands from the rule catalogue
    │       ├── schema.py           sections, rules, slide shapes, slide-plan model
    │       ├── validation.py       stage gates and quality checks
    │       ├── language.py         the English-output gate
    │       ├── planning.py         slide plan parsed from the answers
    │       ├── opportunity.py      Opportunity Info and the percentage split
    │       ├── guidance.py         Salesforce accounts and Guidance vocabularies
    │       ├── delivery.py         Source Material, file names, deck and report
    │       ├── followups.py        follow-up questions and answers
    │       ├── comparison.py       comparison of two finished runs
    │       ├── dates.py            the one date parser
    │       ├── branding.py         the AVL template, footer author / department / date
    │       └── renderer.py         the layouts, python-pptx
    └── references/
        ├── sections.md             the twelve canonical sections
        ├── prompts/                analysis v15, verifier v3, figures v3, slide plan v14, follow-up v3
        ├── platforms/              host adapters and one model policy
        ├── knowledge/              nine domain reference files
        └── data/                   Salesforce accounts and Guidance vocabularies

tools/package_plugin.py             zip the plugin for archive-based installs
tools/make_template.py              rebuild assets/avl_template.pptx from a newer AVL deck
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

Tests cover the renderer's pagination and date parsing, the shipped template
(no slides, page size, the layouts the renderer uses, no large media), the
deck frame and footer identity with its resolution order, the extractors and
Outlook `.msg` mails with their attachments (built at test time by
`tests/msgfile.py`, so no real mail is committed), the language gate, the
`intake` command (`done`, `exists`, `add`, `replace`), the bootstrap stamp,
the approval hook, the four plugin manifests and the two marketplace
manifests, the invariants between the prompts and the Python catalogue
(sections, deduction rules, prompt files, the eleven skill areas), and a smoke
run that copies the plugin to an unrelated location and drives `rfq_run.py`
on the synthetic package, with a cover mail added, through extraction, the
figure dispatch and the analysis dispatch on both host routes.

The upstream project also carries a **golden-run regression suite** that
replays complete stored analyses and asserts the scoring, slide parsing,
renderer and evaluator reproduce their decks exactly. Those fixtures are real
customer RFQ analyses, so they are **not** in this repository — see
[Confidentiality](#confidentiality).

## Confidentiality

An RFQ package is commercially sensitive: customer requirements, named
contacts, pricing, scope, and usually an NDA.

- `RFQs/`, `**/output/` and `**/.work/` are gitignored. Never commit a real
  package or its generated deck — the deck carries the same content in
  condensed form, and `output/.work/followups.json` carries the questions
  asked about it.
- The golden-run fixtures and the tests that consume them are excluded from
  this repository because they contain real analyses, including customer
  email addresses and programme names.
- Every example and test fixture here uses invented names (`Acme`,
  `Northwind`). If you fork this and add fixtures, keep it that way.

## Configuration worth knowing

The tuning surfaces are deliberately small and documented in place:

- `rfq/figures.py` — the constants that decide which pictures earn a visual
  read: a minimum size, a repeat threshold for page furniture, and a cap of 90
  per run. They are set conservatively, because a missed chart is a wrong
  answer while a transcribed logo is a few wasted seconds.
- `rfq/extractors.py` — `RENDER_DPI` (300) and the PDF figure floor. Both were
  set after measurement: 150 dpi rendered equipment tags illegible, and the
  floor had to come down to label size to catch a standard's version number
  rendered as a picture.
- `rfq/verification.py` — how many claims are checked per section and per
  run (48), and the partition size (eight) that bounds the parallel verifiers.
- `rfq/schema.py` — the deduction catalogue (`RULES`, with points, caps and
  provenance) and the slide shape of every section (`SECTION_SHAPES`). The
  analysis and follow-up prompts list the model rules verbatim;
  `tests/test_invariants.py` fails when they drift.
- `references/prompts/` — the five prompts, versioned; the README there says
  what each worker reads and which prompt owns which limit.
- `references/data/` — `accounts.csv` and `vocabularies.json` are generated
  from the Guidance workbook; regenerate them, never edit by hand.
- `references/platforms/models.json` — model assignments per host. Bump the
  plugin version in every manifest after changing it so installed copies
  update.
- Author and department on the deck footer — `rfq_run.py next --author ...
  --department ...`, else `RFQ_INSIGHT_AUTHOR` / `RFQ_INSIGHT_DEPARTMENT`,
  else `author` / `department` in `~/.rfq-insight/config.json`, else the
  operating-system account name and `RFQ Insight` (`rfq/branding.py`).
- `RFQ_INSIGHT_ROOT` — where `intake` creates folders for documents attached
  in chat (default `~/RFQs`; `--root` overrides it).
- `assets/avl_template.pptx` — the AVL master; rebuild it from a newer AVL
  deck with `tools/make_template.py <source.pptx> <out.pptx>` rather than
  editing it.

## Status

The pipeline is in use. The plugin passes its offline test suite and both
manifest validators. Live acceptance in each host with representative RFQs
(see [docs/VALIDATION.md](docs/VALIDATION.md)) remains necessary before
claiming equivalent findings across hosts. Known limitations:

- Outlook `.msg` mails are read with their attachments one level deep; a
  mail attached to a mail is listed as skipped. `.eml` files are not read.
- A figure below the page-area floor is not read; Source Material says so
  explicitly rather than dropping it silently.
- Word page numbers are available only where native Word pagination succeeds
  (Windows with Word installed); elsewhere citations use chapter headings.
- The Scope-of-Work matrix supports more phase columns than it can render
  comfortably: past roughly five phases the column headers wrap.
- The first run on a machine (or a fresh Cowork sandbox) installs the document
  libraries from PyPI, which needs package-index access.
