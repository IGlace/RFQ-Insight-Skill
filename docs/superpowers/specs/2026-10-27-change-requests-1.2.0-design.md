# RFQ Insight 1.2.0: design for the change requests of 23 Oct 2026

Status: approved in conversation on 2026-10-27, written for review.
Source: "RFQ Insight_Change Requests.pptx" (K. Petinger, 23 Oct 2026, 13
slides), the two organisation announcements (CEO information 5 Sep 2025,
PTE announcement 5 Dec 2025), and the answered questionnaire
`docs/superpowers/2026-10-27-change-requests-questions.md`.

Everything ships in one release, plugin 1.2.0, on every host (Claude Code,
Claude Desktop Cowork, Codex). The repository owner accepts the release on
the synthetic package; live acceptance on real packages happens afterwards in
a separate environment.

## 1. Deck on the AVL master (CR 4, CR 3 headline format)

### 1.1 Template asset

- A new file `skills/rfq-insight/assets/avl_template.pptx` is derived from
  the change-request deck: every slide is removed, together with every
  media part that only slides referenced; the slide master, its 47 layouts,
  the theme and the media the master and layouts use (logo, layout
  backgrounds) stay. The file is produced once by a repeatable script in `tools/`
  (`tools/make_template.py <source.pptx> <out.pptx>`) so it can be rebuilt
  from a newer AVL deck.
- A test opens the shipped template and asserts: zero slides; slide size
  13.333 in × 7.5 in; a layout named "Only Title", one whose name starts
  with "1_Title_", and one whose name starts with "Final Slide"; no media
  part larger than 1 MB; no `ppt/slides/` entries.

### 1.2 Renderer frame

- `create_presentation` opens the template instead of `Presentation()`.
  Slide size is read from it; `PAGE_W`/`PAGE_H` stay as constants and a test
  asserts they equal the template's size.
- `content_slide` adds a slide on the "Only Title" layout and writes the
  heading into the title placeholder. The hand-drawn title, gradient
  underline and footer (`title`, `_grad_underbar`, `footer`) are deleted.
  The content origin (`1.4 in` from the top, the current value) is kept so
  no layout needs re-measuring; a test asserts the title placeholder's bottom
  edge plus the underline sit above that origin.
- `main_cover` uses the "1_Title_ AVL Company" layout: opportunity name in
  the title placeholder, "RFQ Insight · Update <date>" in the subtitle, the
  AI-content disclaimer as a text box above the layout's footer line.
  `end_cover` uses the "Final Slide with Backgroundimage English" layout
  with no added text beyond the opportunity name.
- Footer text: the master's right-hand footer text box (`footer_ProjectInfo`)
  is rewritten once per deck to `RFQ Insight | <opportunity name> | <date> |`
  where the date is `D Month YYYY` in English ("23 October 2026"). The
  opportunity name is cut at a word boundary to fit the box. `Internal` and
  the live slide number come from the master unchanged. The hidden
  methodology slide keeps the same frame.
- The confidence chip and the source line keep their positions.
- Comparison decks (`rfq/comparison.py`) and follow-up decks go through the
  same code and need no change beyond what the frame gives them.

### 1.3 Fonts

Verdana everywhere, as today; the template's title style is Verdana 28 pt
regular, which the title placeholder now supplies. The bold title of the
Products & Skills slide disappears with section 2.1.

## 2. Wording and small format fixes

### 2.1 Products & Skills (%) slide and the TOC (CR 3)

- The split slide is titled `Opportunity Info (cont.)` like every second
  page of a section; "Products & Skills (%)" becomes an in-body heading at
  body size, bold, above the two tables.
- The TOC lists `1 Opportunity Info` and, beneath it, an indented, unnumbered
  line `Products & Skills (%)`. Additional Information is listed when present
  (as today). The methodology slide is not listed.
- The slide keeps its own confidence chip and notes (unchanged).

### 2.2 Missing facts in prose (CR 5)

- Prompt rule 3.5 is extended: inside a sentence (Description paragraphs,
  callouts, risk items, prose cells of Timing and Phases descriptions,
  follow-up answers) a missing fact reads `not available`, never
  `Info not available`; table cells and Opportunity Info values keep
  `Info not available`.
- Renderer and follow-up formatting apply the same rule defensively: in
  prose, callout, panel item, bullet and follow-up answer text, the token
  `Info not available` that is not the whole text is replaced by
  `not available`.

### 2.3 "Definition" header (CR 6)

`PRODUCTS_COLUMNS` and `SKILLS_COLUMNS` in `rfq/opportunity.py` become
`["Products (%)", "Definition"]` and `["Skills (%)", "Definition"]`. The main
Opportunity Info table keeps `Definition according to RFQ`. Validation of
stored reports accepts both headers so older reports still render.

### 2.4 Timeline cards (CR 8)

- The milestone label is limited to two measured lines (using `_wrap_count`)
  and the description to the number of lines that fit the card below the
  date; both are cut at a word boundary with an ellipsis.
- Every timeline and Gantt slide's notes get a `Milestones:` block listing
  each milestone's full label, date and description, placed before the
  sources block.

### 2.5 Inferred marker (CR 9)

- The `dashed` field is no longer set by `rfq/planning.py` and is ignored by
  the renderer (connectors, Gantt bars, phase chevrons draw solid). The
  schema keeps the field as optional so stored plans still validate.
- Collaboration diagram: when the party's name, type or the whole role cell
  carries `(inferred)`, the tag is drawn after the party name in the header
  band and removed from the role text; when `(inferred)` sits inside the
  role text after a phrase, it stays there. The planning parser records
  `name_inferred: true` on the party for the first case.

### 2.6 Deduction lines in notes (CR 7, CR 11)

- `confidence.deduction_line` prints the plain label without the code.
  Codes remain in the run report's deductions and on the methodology slide.
- Rule labels in `rfq/schema.py::RULES` are rewritten in plain English. The
  analysis and follow-up prompts list the same labels (the invariant test
  enforces it). The new labels:

| Code | Label |
|---|---|
| G3 | {count} item(s) not stated in the RFQ, inferred from context |
| S2.1 | {count} sentence(s) not backed by a statement in the RFQ |
| S3.1 | {count} value(s) estimated or converted from other units |
| S5.2 | {count} role(s) or interface(s) inferred |
| S6.1 | the RFQ names no phases; phase names were assigned by the analysis |
| S6.2 | phase durations calculated, not stated in the RFQ |
| S6.3 | the timing chart was unreadable; phase membership was reconstructed |
| S7.1 | {count} owner cell(s) assigned by inference |
| S7.2 | {count} task(s) with conflicting owners in the RFQ, assigned to one party |
| S7.3 | owner carried over to other phases for a task tied to a deliverable |
| S8.1 | {count} deliverable(s) implied by the scope but not listed in the RFQ |
| S8.2 | the phase of a deliverable was inferred |
| S9.1 | {count} milestone date(s) corrected from their dependencies |
| S9.2 | milestones assigned to phases by inference |
| S10.1 | {count} standard designation(s) completed from context |
| S10.2 | {count} standard(s) the RFQ mentions only indirectly |
| S11.1 | {count} risk(s) whose triggering clause could not be located |
| S11.2 | the schedule assessment rests on no stated date |
| P1 | percentage split estimated; the RFQ states none |
| P2 | percentage split calculated from proportions the RFQ states |
| V1 | contradicted by the independent check |
| V3 | not found in the documents |

- `confidence.unscored` (replay of older reports) also strips a leading rule
  code from deduction lines so replayed decks read the same way.

## 3. English output (CR 10)

### 3.1 Prompts

- Analysis prompt v15 (renamed file, `workers.PROMPTS` updated): a new rule
  in part 3, "Language": all answer text, table cells, deductions `items`
  and `basis` are English. A phase, milestone, document, department or
  role the customer names in another language is written as its English
  translation followed by the original in brackets on its first use in
  each section, e.g. `Concept Freeze (Konzept-Freeze)`; later uses in the
  same section may use the English form alone. Standard designations,
  deliverable ids, product names, part numbers, e-mail addresses, personal
  names, company names and date strings stay verbatim (rule 3.3). Quoted
  clauses, risk triggers and the Description are translated with no
  original text.
- Follow-up prompt v3: the same rule; answers are always English whatever
  the question's language.
- Slide-plan prompt: unchanged (it never writes new text).

### 3.2 Gate changes

- `rfq/validation.py` faithfulness checks for phase names, party names,
  timing cells and free text accept a token of the form `A (B)` when `A`
  or `B` occurs in the corpus; a bare token must occur as today.
- A new deterministic check `validation.check_language(answer_texts)`
  computes, per field (each table cell, paragraph, list item, deduction
  item), the share of tokens that are function words of German, French,
  Italian or Spanish from small built-in lists, after removing bracketed
  originals, standard designations and tokens with digits. A field with at
  least six tokens and a share above 0.25 is a problem. The check returns
  the first ten problems as "Section N, <field>: not English: <excerpt>".
- `pipeline._after_analysis` and `followups.answer` run the check after
  the schema and faithfulness checks; problems go through the existing
  repair path (three attempts, then `blocked`). It is a gate, not a
  deduction.

## 4. Skill areas (CR 12)

### 4.1 Knowledge file

`references/knowledge/80_avl_nomenclature_and_skill_areas.md` keeps its
nomenclature part and replaces the skill-area part with the structure in
force since 1 Nov 2025, written from the two announcements:

- The eleven skill areas with code and one-line responsibility:
  Functional Development (DS), Digital Product Development (DD),
  Validation & Industrialization (DM), Calibration (DC), E/E, Software &
  Controls (DJ), Test & Data Factory (DF), Commercial Driveline & Vehicle
  (DK), Program & Project Management (DP), Project Quality, Process, Methods
  & Tools (DO), Research & Technology Development (DR), Intellectual
  Property (DI).
- Under each area its skill teams with code and lead groups (DSV, DSC, DSP,
  DSA, DSS, DSD, DSG, DSR, DSF; DDE, DDI, DDM, DDC, DDD, DDT, DDP; DMB, DMM,
  DMV, DMC, DMI, DML; DCX, DCO, DCP, DCC, DCS; DJF, DJS, DJT, DJV; DFD, DFM,
  DFO, DFS, DFT; DKC, DKD, DKS, DKT; DPP; DOP, DOI) and, per team, the RFQ
  task wording that maps to it (e.g. DMC: FMEA, purchasing, supplier
  nomination, cost breakdown, PPAP, change management; DCO: OBD, diagnostics;
  DJF: functional safety, SOTIF, cybersecurity, ADAS/AD simulation).
- Mapping rules: one row per area in scope; the description may name the
  skill team when the RFQ is specific enough; commercial-vehicle scope goes
  to DK; project management to DP only when the RFQ states or clearly
  implies it; DR and DI rarely carry RFQ scope and get no row unless the
  RFQ names research or IP work.
- No people's names, no reporting lines.

### 4.2 Prompt and tests

- Rule 7.7.2 of the analysis prompt names the eleven codes and the
  optional skill-team mention. Row granularity and the prefix form
  `<Area> (<code>): <task>` are unchanged.
- `tests/test_invariants.py` asserts the eleven area codes in the prompt
  equal those in the knowledge file, and that every team code in the file
  starts with its area's code.

## 5. Upload via the chat window (CR 2)

### 5.1 Runner command

`rfq_run.py intake --root <root> --name <name> [--mode add|replace] <file> ...`

- Creates `<root>/<name>` (the name is sanitised like deck file names) and
  copies every file, preserving names; a file given as a directory is
  copied recursively.
- Returns `{"status": "done", "folder": ...}`; when the folder exists and
  `--mode` is absent, returns `{"status": "exists", "folder": ...,
  "files": [...]}` without touching it; `--mode add` copies into it
  (existing names get a numeric suffix), `--mode replace` empties it first
  except `output/`, which is deleted only in replace mode.
- Root resolution: `--root` if given, else `RFQ_INSIGHT_ROOT`, else
  `~/RFQs`. The root is created when missing.

### 5.2 Skill procedure

- SKILL.md step 1 gains "Attached documents": when the request carries
  files the host attached and names no folder, ask exactly one question,
  "Which folder name should I use for this RFQ?", and wait. Then run
  `intake`. On `exists`, ask exactly one more question: add the attached
  files to the existing folder or replace its contents; run `intake` again
  with the chosen `--mode`. Then start the normal run in the same turn. In
  Cowork the connected working folder is the root.
- The interaction contract lists these two questions as the only permitted
  questions.
- Each adapter gets one paragraph saying where attached files are found on
  that host (the paths the host places in the message; Claude Code's
  upload paths; Codex attachment paths) and that the files are passed to
  `intake` by absolute path.
- The approval hook keeps approving `rfq_run.py` calls; copying is done by
  the runner, so no new tool permission is needed.

## 6. E-mail input (CR 13)

- `.msg` joins `SUPPORTED_EXTENSIONS`; `extract-msg` is added to
  `requirements.txt` (pinned) and the bootstrap stamp re-provisions.
- `extractors.extract_msg(path, key)` returns as text: a header block
  (`From:`, `To:`, `CC:`, `Date:`, `Subject:`) and the plain-text body (HTML
  body converted to text when no plain body exists). Inline images follow
  the existing `RawImage` path.
- Attachments are written to `output/.work/mail/<mail basename>/<attachment
  name>` and reported by the extractor; `corpus.walk_supported` expands a
  `.msg` into itself plus its supported attachments, each with filename
  `<mail>.msg › <attachment>` and the same relative path form. A `.msg`
  attachment is expanded one level deep; deeper mails are listed as
  skipped with the reason "nested e-mail".
- Corpus change detection hashes the `.msg` file; attachments inherit it.
- Source Material lists the mail as one row and its attachments as rows
  directly beneath it, their names indented with two spaces.
- Citations, locators and the faithfulness gate see attachments as
  ordinary files.

## 7. Versioning, documentation, tests

- Version 1.2.0 in `.claude-plugin`, `.codex-plugin`, `.github/plugin`,
  `asset.json` and the two marketplace manifests. CHANGELOG: the
  "Unreleased" block becomes part of "## 1.2.0" with the items above.
- README, USAGE, INSTALL, the prompts README and the knowledge README
  updated (template asset, intake, e-mail input, language rule, plain note
  labels, eleven areas).
- Tests added or changed: template integrity (1.1); frame geometry and
  footer text (1.2); TOC lines and `(cont.)` title (2.1); prose wording
  (2.2); headers (2.3); timeline truncation and notes block (2.4); solid
  connectors and tag placement (2.5); label table and codeless lines, replay
  stripping (2.6); language check on canned German/English/mixed fields and
  gate acceptance of `A (B)` (3); knowledge and prompt code invariants (4);
  intake on a temporary root including `exists`, `add`, `replace` (5);
  `.msg` extraction from a synthetic mail with a PDF and a nested mail (6);
  the runner smoke test extended with a `.msg` in the synthetic package.
- The synthetic example gains `03_cover_mail.msg` built by a test helper,
  not committed as a binary, so no real mail enters the repository.

## 8. Out of scope

Skill-team rows in the matrix, a "Skill area" column, business units on
slides, aligning the Skills (%) vocabulary to the areas, `.eml` input, and
deriving the folder name from the attachments. The questionnaire records
these as declined.
