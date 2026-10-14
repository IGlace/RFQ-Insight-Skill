# RFQ Insight — a plugin for Codex and Claude

Turn a folder of RFQ documents into the AVL-branded RFQ Insight PowerPoint
deck. The plugin runs a fixed workflow without questions or progress
narration, returns the deck link, and stops. A JSON run report is written next
to the deck for validation and recovery; it is never shown in chat.

Point it at the package exactly as the customer sent it — PDFs, Word, Excel,
PowerPoint, spreadsheets, drawings, subfolders and all — and it answers the
twelve fixed sections a sales manager or chief engineer needs in order to
decide whether and how to bid. Every section carries a confidence score out
of 10 with the reasons in the speaker notes. Afterwards it answers follow-up
questions from the saved corpus and can compare two analysed RFQs.

```
You:  analyse the RFQ package in RFQs\Acme_V6
```

```
<folder>\output\RFQ Insight_<Opportunity name>_<DDMMYYYY>.pptx   the deck (the only thing returned)
<folder>\output\RFQ Insight_<Opportunity name>_<DDMMYYYY>.json   internal run report
<folder>\output\.work\                                          checkpoints, corpus, follow-up history
```

One plugin, one skill. Codex is the primary host; Claude is supported with
the same skill:

| Host | Where it runs | Install |
|---|---|---|
| Codex CLI / IDE / desktop app (Codex and Work modes) | the user's machine | `codex plugin marketplace add IGlace/RFQ-Insight-Skill` |
| Claude Desktop Code / Claude Code | the user's machine | `claude plugin marketplace add IGlace/RFQ-Insight-Skill` |
| Claude Desktop **Cowork** | the sandboxed Cowork VM, on the connected folder | Customize → Plugins → Add marketplace (this repository) |

See **[INSTALL.md](INSTALL.md)** for each host and **[USAGE.md](USAGE.md)** for
the day-to-day guide. This repository is itself the marketplace: the plugin
lives in `plugins/rfq-insight/` and both the Codex marketplace manifest
(`.agents/plugins/marketplace.json`) and the Claude one
(`.claude-plugin/marketplace.json`) point at it.

---

## What it produces

Twelve canonical sections, in a fixed order, with fixed titles, one slide
each (the renderer adds continuation pages only when a table or list really
overflows). Follow-up answers, when added, form a thirteenth section,
Additional Information, before Source Material.

| # | Section | Mode | # | Section | Mode |
|---|---|---|---|---|---|
| 1 | Opportunity Info | mixed | 7 | Scope of Work and Responsibilities | extracted |
| 2 | Description | analysed | 8 | AVL Deliverables | extracted |
| 3 | Technical Product Definitions and Targets | extracted | 9 | Timing | extracted |
| 4 | Application Approach | extracted | 10 | Customer Specific Standards | extracted |
| 5 | Collaboration Approach | extracted | 11 | Risk Detection | analysed |
| 6 | Development Phases | extracted | 12 | Source Material | built by the runner |

- **Extracted** sections copy every value, name, designation, date string,
  cell and deliverable from the documents. Wording may be condensed; content
  may not change. The only inference allowed is the kind the section names
  (an entailed deliverable, a derived phase span, a corrected garbled
  pairing), and it stays tagged `(inferred)` on the slide, in amber.
- **Analysed** sections (Description, Risk Detection) are written from stated
  facts; each item names the clause it rests on. Section 11 is the one that
  earns the deck: schedule feasibility, contradictions, ambiguous ownership
  and unbounded scope all go there.
- **Section 1** is mixed: identity fields (customer, site, contact, due date,
  title) are extracted; project type, lead product, technology, industry,
  Products (%) and Skills (%) are classified in the AVL Guidance vocabulary.
  The slide is built by the application from the analysis' `opportunity`
  object and the Salesforce account list in `references/data/accounts.csv`
  (Account Name (Site) and KAM (PTE)).
- **Section 12** is built by the runner from the corpus and the source
  catalogue, with no model: one row per file, `File | Type | Read | Used by
  sections`.
- **Section 13** answers declare their own mode, extracted or analysed.

## Confidence

Each section starts at 10. The analysis lists its deductions, each by rule
code from a fixed catalogue (`rfq/schema.py::RULES`); Python checks the code
is allowed for that section, applies the per-rule points and caps, adds the
reviewer's and the faithfulness gate's deductions, and computes the score
(floor 1). The model never writes a number.

| Band | Score |
|---|---|
| High | 7–10 |
| Medium | 4–6 |
| Low | 1–3 |

- General rules apply everywhere: G1 contradiction between documents (−4
  each), G2 unreadable picture or table (−2), G3 inferred item, extracted
  sections only (−1), G4 lower-priority source (−1), G5 partly readable file
  (−2).
- Section rules cover what is specific to each section, for example S7.1
  cells placed by inference (−1, −2 or −4 by count), S6.1 phase names
  assigned because the RFQ names none (−3), S11.1 a risk without a locatable
  trigger (−2 each).
- Python adds V1 refuted by the reviewer (−4), V2 found ambiguous (−2), V3 not
  found in the corpus (−3), and for section 12 P12.1 partly read / P12.2
  skipped files.
- Never a deduction: a confirmed absence after a full sweep, rows trimmed for
  the slide (the count is shown), a `Joint` or `—` cell that mirrors the RFQ,
  an unmatched Salesforce account, mapping RFQ tasks onto AVL skill rows.

The visible chip reads `Medium · 6/10` in the band's colour. The first slide
of each section starts its speaker notes with exactly this:

```
Confidence 6/10 (Medium)
-2  S7.1  4 cells placed by inference: PM, design review, cooling jacket, failure handling (Technical Agreement 3.3.2 gives no phase for them)
-2  S7.2  2 RASIC conflicts resolved to one executing party: test bench setup, calibration sign-off (Table 2 lists Aurobay and Party B as R)
Check: 6 statements reviewed by a separate reviewer: 6 confirmed.
Shown: 13 of 16 standards.

Sources:
File: …
```

With no deductions the second line is `No deductions: every item is stated
in the documents.` `Shown:` appears only when a section was trimmed. The
complete source references (file, chapter path, page or page range) follow on
every content slide, continuations included. Visible slides never show
citations. Section 13 carries the lowest score of its follow-up answers.

## How a run works

`scripts/rfq_run.py next <folder>` does every deterministic step itself and
stops only when a model worker is needed. The coordinator (the host's agent)
starts the requested workers, then calls `next` again with `--completed <id>`
or `--failed <id>` for each, which records the result and advances the run in
one command, until the runner reports `done`.

| Stage | What happens | Kind |
|---|---|---|
| extract | native parsing (`python-docx`, `python-pptx`, `openpyxl`, `pdfplumber`), chapter and page markers, image unpacking and filtering | Python |
| figures | each picture is transcribed literally by a vision worker, up to six per request, one `.txt` per picture, then merged into the corpus | **model** |
| analysis | one fresh worker answers sections 1–11, their deductions and the Opportunity object from prompt v14 plus the knowledge pack; oversized packages are first factored into an exact evidence ledger | **model** |
| faithfulness gate | standards, dates, number+unit pairs, phase names, owner cells, deliverable ids and party names must occur in the corpus; misses go back to the analysis worker (three attempts), what remains becomes V3 deductions | Python |
| verification | up to 48 claims, harvested round-robin across sections (absences, derived, stated values, risk triggers), judged in isolated workers, eight claims per partition, in parallel; the Salesforce account is looked up | **model** (isolated) |
| slides | the runner parses each answer's fixed markdown shape into the typed slides; the slide worker (prompt v14) runs only when a section does not parse | Python (model fallback) |
| finalize | section 12 is built, scores and notes are attached, the deck, the run report and `deliverables.json` are written; existing outputs are never overwritten | Python |
| evaluate | the quality gate (structure, titles, phases, ownership cells, notes, sources); a failure blocks delivery | Python |

Three design choices are worth calling out.

**The figure pass happens before the analysis.** Charts, process diagrams and
pasted standards tables routinely carry facts that exist nowhere in the
extractable text. Transcribing them first makes that content part of the
corpus everything downstream reads, including the verification pass.

**The verification pass is isolated.** It receives only the claims, the corpus
and its own prompt; it cannot see the reasoning that produced the claims.

**The deck shows the analysis answer.** Slides are parsed from the answers,
not rewritten by a second model, so what the notes score is what the slide
shows.

## Follow-up questions and comparisons

- `rfq_run.py ask` / `answer` answer one question at a time from the saved
  corpus (re-reading the documents first when they changed) and keep the
  history in `output/.work/followups.json`. Each answer declares its mode and
  deductions; extracted answers pass the same faithfulness gate (dates,
  standards, number+unit). `add-followups` rebuilds the deck with an
  "Additional Information" section before Source Material.
- `rfq_run.py compare <A> <B>` diffs two finished runs section by section,
  sets the scores side by side (`7/10 → 5/10`) and writes a comparison deck.
  No model is involved.

## Model routing

Routes and efforts live in one file,
`plugins/rfq-insight/skills/rfq-insight/references/platforms/models.json`.

| Route | Work | Codex reasoning effort |
|---|---|---|
| analysis | RFQ analysis | high |
| verification | independent claim verification | medium |
| figures | figure transcription | medium |
| slides | slide plan, fallback only | medium |
| followup | follow-up questions | medium |
| support | optional bounded wording/formatting | low |

On Claude each route names a model alias in the same file. Extraction,
validation, scoring, section 12, slide parsing, rendering and the account
lookup are Python. Every model stage runs in a **fresh worker** that receives
only its prompt, its input files and its output paths. Where a host cannot
choose a worker's model, the worker runs on the host's configured model and
the run report records the model as unknown rather than stopping.

## Permissions

The plugin ships no approval hook (removed at the client's request). Before
the first command of a run the skill sends one notice telling the user how to
let the session run without a prompt per step (`/approvals` in Codex, auto
mode in Claude Code); Cowork grants folder access once and never prompts
per command. Details per host are in [INSTALL.md](INSTALL.md#permissions).

## Repository layout

```
.agents/plugins/marketplace.json    Codex marketplace (this repository)
.claude-plugin/marketplace.json     Claude marketplace (this repository)
plugins/rfq-insight/                the installable plugin
├── .codex-plugin/plugin.json       Codex plugin manifest
├── .claude-plugin/plugin.json      Claude plugin manifest
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
    │       ├── planning.py, schema.py, validation.py   slide plan and markdown parser, contracts and rule catalogue, faithfulness and quality gates
    │       ├── confidence.py                           scores, bands, deduction lines, notes
    │       ├── renderer.py, delivery.py                deck, report, section 12
    │       ├── guidance.py, opportunity.py             Guidance vocabulary, Salesforce lookup
    │       ├── followups.py, comparison.py             follow-up mode, comparison decks
    │       └── dates.py, assets.py
    └── references/
        ├── sections.md             the twelve canonical sections
        ├── prompts/                analysis v14, slide plan v14 (fallback), verifier v3, figures v3, follow-up v2
        ├── platforms/              host adapters (codex.md, claude.md) and one route file (models.json)
        ├── knowledge/              nine domain reference files
        └── data/                   Guidance vocabulary and the Salesforce account list

tools/package_plugin.py             zip the plugin for archive-based installs
examples/synthetic-rfq/             fictional input for acceptance runs
tests/                              regression and portability tests
docs/CHANGE_REVIEW.md               review of the runtime rewrite and the follow-up rework (2026-10-14)
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

About 1,100 tests cover the extractors and corpus format, the figure filter
and merge, the rule catalogue and scoring, the faithfulness gate, the claim
harvest and verification bookkeeping, source locators and the reference
catalogue, the markdown-to-slide parser, the slide-plan contract and
sanitiser, section 12, the renderer's layout and pagination, delivery and
file naming, the quality gate, the stage machine and resume rules, the
Salesforce lookup, follow-ups, comparisons, the plugin manifests, and an
end-to-end smoke run of `rfq_run.py next` with canned worker outputs.

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
- `rfq/schema.py` — `SECTION_MODES` (extracted / analysed / mixed / python
  per section) and `RULES`, the deduction catalogue: code, label, points or
  tiers, cap, sections.
- `rfq/confidence.py` — the score (10 minus deductions, floor 1), the bands
  and the notes format.
- `rfq/validation.py` — the corpus size limit (600,000 characters), the
  faithfulness gate and the quality gate.
- `rfq/verification.py` — the claim caps (6 per section, 48 per run) and the
  partition size (8).
- `references/prompts/` — the prompts; `tests/test_invariants.py` fails if a
  prompt and the code disagree about the canonical sections, the section
  modes or the rule catalogue.
- `references/platforms/models.json` — routes and efforts per host. Bump the
  plugin version in the manifests after changing it so installed copies update.
- `references/data/vocabularies.json` and
  `references/knowledge/90_guidance_denominators.md` — the Guidance Document
  vocabulary; both are generated from the same workbook and must stay in sync.

## Status

The runtime rewrite and the follow-up rework of 2026-10-14 are reviewed in
[docs/CHANGE_REVIEW.md](docs/CHANGE_REVIEW.md). In a normal run no slide
worker starts, figures produce one output per picture, and a deck renders in
about 0.2 s (was about 6 s). Live run times on Codex have not been measured
here; record them with `rfq_run.py timing` per
[docs/VALIDATION.md](docs/VALIDATION.md).

Known limitations:

- Word page numbers need a Windows host with Word installed; elsewhere the
  notes cite chapters and say that rendered pages are unavailable.
- Runs made before the scoring keep their old notes: `render` replays them,
  and `add-followups` on such a run stops with "The RFQ analysis predates the
  current scoring; run the analysis again before adding follow-ups."
- `.msg` (Outlook) files are skipped by design (P12.2 in section 12).
- A figure below the page-area floor is not read; the corpus says so
  explicitly rather than dropping it silently.
- Long phase names make the Scope-of-Work header tall, which can push rows to
  a continuation page earlier than necessary.
- The first run on a machine (or a fresh Cowork sandbox) installs the document
  libraries from PyPI, which needs package-index access.
