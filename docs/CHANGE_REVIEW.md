# RFQ Insight: repo plugin (HEAD 1561393, 2026-10-02) vs local zip (files 2026-10-05 … 2026-10-14)

Old = `plugins/rfq-insight/` in the repo. New = `rfq-insight/` in the zip. Both are version "1.0.0".

## 1. Change inventory

### 1.1 Packaging and manifests
| Path | Change |
|---|---|
| `.claude-plugin/plugin.json` | Author "IGlace" → "Oussama Wari, AVLI Platform Team"; `license: UNLICENSED` added; `homepage`/`repository` removed; keyword `avl`, `cowork` removed; `"hooks": "./hooks/hooks.json"` removed; `"skills": "./skills"` added. |
| `.codex-plugin/plugin.json` | Same author/license/keyword changes; longDescription "eleven" → "twelve fixed RFQ Insight questions"; `defaultPrompt` list → string; `capabilities` `["Read","Write"]` → `["skills"]`. |
| `.github/plugin/plugin.json` | New (GitHub Copilot plugin manifest), although SKILL.md refuses Copilot hosts. |
| `CHANGELOG.md` | New. One `1.0.0` entry listing three generations of changes. |
| `README.md` (plugin) | Removed. |
| `hooks/hooks.json`, `hooks/approve.py` | Removed (PreToolUse / PermissionRequest auto-approval of the plugin's own scripts). |
| `skills/rfq-insight/SKILL.md` frontmatter | `allowed-tools` list removed (Bash python/mkdir, Read, Write, Edit, Glob, Agent). Description extended with follow-up and compare triggers. |
| `skills/rfq-insight/agents/openai.yaml` | Unchanged. |
| `skills/rfq-insight/assets/word_pages.ps1` | New. PowerShell + Word COM helper that repaginates a private copy and emits block → page ranges as JSON. |
| `skills/rfq-insight/references/data/accounts.csv` | New, 2.66 MB, 26,784 Salesforce account rows (`name, base, site, country, pte_market, avl_market, kam_pte, kam_company`); 9,558 rows carry a named KAM. |
| `skills/rfq-insight/references/data/vocabularies.json` | New. Guidance Document values (6 project types, 8 technologies, 10 industries with SAP profit centre, 18 products, 10 skills with abbreviations). |
| `__pycache__/` (24 `.pyc`, incl. retired modules `compare`, `compare_render`, `confidence`, `followup_flow`, `freshness`, `fsio`, `naming`, `pictures`, `guidance_lookup`) | Shipped inside the zip. |
| Repo-level: `tests/` (20 files, 385 tests), `docs/MIGRATION_REVIEW.md`, `docs/VALIDATION.md`, `INSTALL.md`, `USAGE.md`, `examples/synthetic-rfq/`, `tools/package_plugin.py`, marketplace manifests | Not in the zip (zip is plugin-only). Against the new scripts the repo suite collects 5 of 20 modules: 57 pass, 32 fail, 15 modules cannot import. |
| Line endings | Repo files are CRLF (committed that way); zip files are LF. Every "changed" file therefore shows a whole-file diff in git until normalised. |

### 1.2 SKILL.md workflow
| Area | Old | New |
|---|---|---|
| Entry points | 14 scripts called one by one by the coordinator (`workflow_state --start/--complete`, `extract_corpus`, `merge_image_text`, `validate`, `corpus_text`, `stage_request`, `record_execution`, `extract_claims`, `apply_verdicts`, `plan_input`, `finalize`, `evaluate`, `render_run`). | Two entry points: `bootstrap.py`, `rfq_run.py`. `rfq_run.py next` runs every deterministic step and stops only to return `dispatch` / `repair` / `done` / `blocked` / `stopped`. Individual modules under `scripts/rfq/` must not be invoked. |
| Resume rules | Written out in SKILL.md (legacy checkpoint table, stage boundaries table, unread-input restart, in-thread verification restart). | Moved into `pipeline._resume_rules`; SKILL.md only says resume is automatic. |
| Restart | "only if explicitly requested"; stage names in a table. | `next --restart <stage>`; `--until <stage>` added for partial runs. |
| Repair loop | Coordinator sends validator errors back; 3 attempts. | Runner returns `repair` with a `repair_message`; 3 attempts counted in `attempts.json`; third failure → `blocked`. |
| Permission notice | None. | One mandatory notice before the first command (Claude: Shift+Tab auto mode; Codex: `/approvals`). Replaces the deleted approval hook. |
| Host check | Claude / Codex only (implicit). | Explicit: any other host incl. GitHub Copilot CLI → stop. |
| Telemetry | `record_execution.py` per stage. | `rfq_run.py event` per request (started/completed/failed, tokens, observed model); `timing` inspection command; coordinator must serialise all commands per folder. |
| Figures | One request per image; empty file = unreadable. | Up to 6 pictures per request; two outputs per picture (`.txt` + `.json` classification); unreadable picture gets no file. |
| Verification | One isolated worker. | Partitions of 6 claims when ≥ 8 claims, each its own fresh worker; receipts with run id. |
| Analysis inputs | prompt v12 + 8 knowledge files + sections.md + corpus.txt. | prompt v13 + 9 knowledge files + sections.md + corpus.txt (or `prepared_evidence.txt` ledger when > 600k chars) + `source_catalog.json` when it fits. |
| Slides | Always a worker (prompt v11). | Worker (v13) unless every answer carries a typed `presentation` that round-trips to the answer text exactly; then Python writes the plan. |
| Opportunity | Project name = folder name. | `--project` seeds the display name; `opportunity_name` from the analysis replaces it on cover/footer/end and names the file. Salesforce Account/KAM looked up by Python. |
| Delivery rules | Link to pptx only. | Same, plus: product-picture slides excluded; notes carry full references; first slide of each section explains confidence; citations never on visible slides. |
| New modes | — | "Follow-up questions" (`ask` / `answer` / `add-followups`, history in `.work/followups.json`, "Additional Information" section before Source Material) and "Compare two analyses" (`compare A B` → comparison deck, no model). |

### 1.3 Platform adapters and model routes
| File | Change |
|---|---|
| `platforms/models.json` | `followup` route added (opus / gpt-6.1-sol high). Codex analysis/verification/figures/slides `gpt-6-sol` → `gpt-6.1-sol` (efforts unchanged). Support stays haiku / gpt-6-luna. |
| `platforms/claude.md` | Rewritten around `rfq_run.py next`: permission-notice text; `event` lifecycle recording rules (only coordinator records; `started` only if observed; `--observed-at` needs timezone; tokens only when reported); bounded rolling queue for figure/verification jobs; figure batches of six with two outputs; "Follow-up stage" section. `record_execution.py` syntax removed. |
| `platforms/codex.md` | Same restructuring; `/approvals` (`/permissions`) notice; `fork_turns="none"` kept; Follow-up stage with `gpt-6.1-sol` high. |

### 1.4 Sections (`references/sections.md`, `schema.TITLES`)
| id | Old | New |
|---|---|---|
| 1 | Commercial Info | **Opportunity Info** (Opportunity-Informationen) |
| 2 | Source Material | **Description** (Beschreibung; was "Summary" id 3) |
| 3 | Summary | Technical Product Definitions and Targets (was 4) |
| 4 | Technical Product Definitions and Targets | Application Approach (was 5) |
| 5 | Application Approach | **Collaboration Approach** (Kooperationsansatz; new section, split out of old 5) |
| 6–11 | unchanged | unchanged |
| 12 | — | Source Material (moved from 2 to last) |
| 13 | — | Additional Information (follow-ups only, rendered before 12; never part of the model contract) |

### 1.5 Knowledge pack (`references/knowledge/`)
| File | Change |
|---|---|
| `10_implicit_facts_extraction.md` | Two renames only: "Commercial Info" → "Opportunity Info" (framework-agreement rule and the implicit-content table). |
| `20_key_information_selection.md` | Section bullets rewritten: Opportunity Info lists the client fields incl. Opportunity name, Project type, Products (%) and Skills (%), says every classification value comes verbatim from `90_…`, and that Account Name (Site) / KAM (PTE) are looked up by the application. "Summary" → "Description". Application Approach loses "plus the parties/interfaces". New "Collaboration Approach" bullet (customer, AVL, every named third party; verbatim "No further parties are named in the RFQ."). Customer Specific Standards: "completeness beats selectivity" → capped at one slide (13 rows), select by compliance weight, disclose counts. |
| `30_scope_and_responsibility_mapping.md` | One rename: parties list now lives in "Collaboration Approach". |
| `40_risk_flagging_guide.md`, `50_development_phases_and_milestones.md` | Unchanged. |
| `60_standards_glossary.md` | Intro changed from "List every standard… completeness beats selectivity" to "Find every standard… the section is capped at one slide (13 rows)… SELECT by compliance weight and say in confidence_reason how many were found and shown". |
| `70_rfq_document_types_and_denominators.md` | The whole inline vocabulary (Project Type, Technology, Industry, 18 Lead Product definitions) deleted and replaced by a pointer to `90_guidance_denominators.md` plus rules for Products (%) / Skills (%) (whole percentages summing to 100, >0 % only) and the new Lead-product rule ("dominant enabler… at least 5 %… not necessarily the largest share"). Worked example updated to the full Guidance names ("SOP Project w/o CSM (up to SOP or partial SOP development)", "CO2-neutral ICE"). CSM definition changed from "customer-specific modification of an existing AVL product" to "full component responsibility incl. Component Supplier Management". Off-road/Special Purpose section rewritten: Special Purpose is now defence/dual-use only; marine/rail → "Marine, Rail"; stationary power/electrolysis → "Hydrogen & Industrial Energy". "Others" → "Others (Testing facility Rentals, Manufacturing, etc)". Electrolyzer/Emerging Energy examples re-derived from the Guidance descriptions. |
| `80_avl_nomenclature_and_skill_areas.md` | Lead product definition replaced by the Guidance one; note that Skills (%) uses the Guidance skill list, never the tech-centre skill areas listed in this file. |
| `90_guidance_denominators.md` | New, generated from `Guidance Document.xlsx` (tables for Project type, Lead product rule, Technology, Industry with SAP profit centre, Products (%), Skills (%) with abbreviations and descriptions). |

### 1.6 Prompts (`references/prompts/`)
| File | Change |
|---|---|
| `README.md` | Removed (documented v12/v11 provenance and the "tuned against OCR" caveat). |
| `RFQ_Claim_Verifier_Prompt_v2.md` | Identical. |
| `RFQ_Figure_Transcription_Prompt_v1.md` → `v2.md` | Adds: legible-but-textless picture writes `[No text in this picture]`; unreadable picture writes neither output; second JSON output `{category, product_relevance, caption}` with 8 categories, 3 relevance levels, ≤ 12-word caption, non-empty caption for product_photo / cad_render / technical_drawing. |
| `RFQ_Followup_Prompt_v1.md` | New. Answers one question from `corpus.txt` only (analysis.json as context, never a source); "Not found in the RFQ documents." contract; `(inferred)` tagging; Party-B identity rule; ≈150-word limit; output `{id, answer, sources[{filename, locator}|{ref_id}], not_found}`. |
| `RFQ_QA_Extraction_Prompt_v12.md` → `v13.md` (134 → 177 lines, 5.6k → 8.4k words) | 11 → 12 sections; new "CONTRACT PARTY IDENTITY" rule (unnamed Party B ≠ AVL); determinism rules now allow materiality selection where a section states a size limit, with count disclosure; section 1 rewritten (full legal customer name, customer site address, customer short, project title, Opportunity name "<short> – <title>", Products/Skills percentages, Lead-product rule, Account/KAM = "Info not available"); section 4 loses parties; new section 5 Collaboration Approach (always answered, verbatim no-further-parties sentence); section 8 "NO SIZE CAP AND NO INVENTION (client-confirmed 14.10.2026)" replaces "Target ~10–15 entries"; section 10 "ONE SLIDE, ALWAYS": ≤ 13 rows, ≤ 10 words per cell, select by compliance weight, disclose counts; section 11 "ONE SLIDE PER GROUP": ≤ 8 items of ≤ 18 words per group (≤ 16 for very large projects), materiality selection, clause refs go to sources not text; section 12 Source Material; "Individual Requests" now handled by follow-up mode; `evidence_files` → `sources[{filename, locator}]` with locator grammar (page, page range, slide, sheet, section path, composite "p. 12; section 3.1"), no invented Word pages, one object per chapter; new `confidence_reason` (1–3 sentences, ≤ 900 chars, no rating definitions); confidence semantics changed so a confirmed absence after a full sweep is "high"; new required `opportunity` object; "VISIBLE CONTENT" rule (no citations in answer text); optional lossless `presentation` typed slides with a canonical-serialisation coverage proof (tables, prose, bullets, panel, phases, collab, ownership, gantt/timeline rules); `ref_id` catalogue citations; image transcription cites the containing page/section; DO-NOT list and quality bar updated for the caps. |
| `RFQ_Slide_Plan_Prompt_v11.md` → `v13.md` (145 → 168 lines) | "ACCURACY OUTRANKS BREVITY / no slide cap" replaced by "THE DECK IS SHORT": one slide per section, no slide of the stage-2 model's own, no cutting either; "SOURCE REFERENCES" block (no citations/page refs on slides, notes carry them); new `opportunity` layout for id 1 (app-filled); kpi / twoColumn / prosCons no longer used; per-section hints renumbered, id 5 is exactly one collab slide, id 3 forbids picture slides, id 11 forbids Salesforce text and single-slide fallback, id 12 Source Material; collab no longer capped at 6 parties (renderer paginates); new "SECTION SLIDE SHAPES" table (validator-enforced); "SLIDE COUNT PER QUESTION — no fixed maximum" removed; validation checklist updated. |

### 1.7 Schema (`scripts/rfq/schema.py`, 288 → 473 lines)
Added `OpportunityInfo` + `PercentItem`; `SourceRef{filename, locator}` replaces `EvidenceFile`; `AnswerItem` gains `confidence_reason`, `sources`, optional `presentation`; `AnalysisResult.opportunity`; `PresentationContent` (strict-then-loose validation); `PicturesSlide` and `OpportunitySlide` layouts; `PanelSlide.sourceLine/sourceDetails`; `Question.confidenceNotes/sourceLine/sourceDetails`; `number: StrictInt`; `SlidePlan` validator for canonical order; `TITLES` 12 entries; `SECTION_IDS`, named constants, `ADDITIONAL_INFO_ID=13`, `SECTION_SHAPES`, `describe_shapes`, `section_number_errors`.

### 1.8 Runtime (`scripts/`, 250 KB → 635 KB of Python)
Removed: `apply_verdicts.py`, `corpus_text.py`, `evaluate.py`, `extract_claims.py`, `extract_corpus.py`, `finalize.py`, `merge_image_text.py`, `plan_input.py`, `record_execution.py`, `render_run.py`, `stage_request.py`, `validate.py`, `workflow_state.py`, `rfq/images.py`, `rfq/preprocess.py`, `rfq/sanitize.py`.
Unchanged: `bootstrap.py`, `requirements.txt`, `rfq/assets.py`.
Changed: `rfq/dates.py` (+ `exact_calendar_date`, `numeric_exact_date`, `contains_calendar_day`, month/year "08/2027" parsing, `display_date` DD.MM.YYYY, `compact_date` DDMMYYYY); `rfq/extractors.py` (573 → 1,177 lines); `rfq/renderer.py` (1,490 → 1,787 lines); `rfq/schema.py` (above).
Added (`rfq/`): `comparison.py` (two-report diff + comparison deck), `corpus.py` (walk, sha256 per file, corpus revision, change detection, `format_corpus`, evidence chunking / deterministic receipts / ledger for > 600k packages), `delivery.py` (finalize order, file naming `RFQ Insight_<Opportunity>_<DDMMYYYY>`, exclusive writes, report replay, picture stripping), `figures.py` (filter, balanced batches of 6, classification parsing, receipts/meta, merge), `followups.py` (ask/answer/add-followups, staleness), `guidance.py` (vocabulary access, name normalisation, account candidate tiers, site-based disambiguation), `opportunity.py` (account risk lines, opportunity slide builder), `pipeline.py` (stage handlers, resume rules, attempts, blocked messages), `planning.py` (plan input, deterministic typed-plan acceptance with canonical serialisation, sanitiser, phase traceability), `sources.py` (locator grammar, `locator_exists`, reference catalogue / `ref_id`, downgrade, `format_source_details`, `attach_sources`), `state.py` (progress, history archiving, timing.json, execution.json, events), `validation.py` (corpus/analysis/plan checks, opportunity value checks, C1–C9/CP1/W1–W6 gate), `verification.py` (claim harvesting, partitions, verdict checks/apply, confidence notes, check summary), `workers.py` (routes, request/message builder, scoped repair, figure batch requests).

#### Extraction differences (`extractors.py`)
| Topic | Old | New |
|---|---|---|
| DOCX headings | None; no section markers. | `--- Section: … ---` and `--- Section Path: a > b ---` from `w:outlineLvl` (direct and basedOn chain), Title, "Heading N"/"Überschrift N", Word decimal numbering rebuilt from numbering.xml, manual "3.2 Timing" headings under an observed parent. |
| DOCX body | Top-level `w:p` / `w:tbl` only. | Also `sdt`, `customXml`, `w:ins`; merged cells de-duplicated; sha256 before/after read. |
| DOCX pages | None. | Windows only: `word_pages.ps1` through Word COM (60 s timeout, private WINWORD PID, sha check, block-count check) → `--- Page N ---`, repeated section markers on continuation pages, `[[Table spans rendered pages a-b]]`. Elsewhere `locations.status = unavailable`. |
| PDF headings | None. | From the outline (bookmarks) or typography (≥ 80 % bold, size above body, decimal sub-headings under an observed parent, TOC/table exclusion). |
| PDF tables | Text layer + every `extract_tables` result (duplicated). | Geometry-verified tables (row count, glyph containment, no overlap, cell text equality) replace their glyphs in the text; unverified tables still duplicate. `raw_extracted_text` and `extraction_metrics` kept. |
| Image ids / markers | same | same (`<key>__imgNN`, `[[EMBEDDED IMAGE … — transcription pending]]`) |
| Scans and figure crops | 300 dpi render; crops ≥ 600 pt². | Same. |

#### Figures
Old: one worker per image, `.txt` only, empty = unreadable, reuse when non-empty. New: batches of six balanced by pixel count; `.txt` + `.json` classification; `NO_TEXT_MARKER`; receipt in `figure_requests.json`, `.meta.json` on acceptance; reuse only when both files valid and meta matches image sha; max 2 rounds per image. Product-picture slides (`plan_pictures`, `L_pictures`, `CP1` check) were built and then retired in the final CHANGELOG entry; code remains.

#### Verification
Old: `extract_claims` (3/section, 20 total) → one worker → `apply_verdicts` (refuted → low; refuted/ambiguous without evidence → unchecked). New: same harvest (plus "no further parties" marker, account lines skipped) → partitions of 6 when ≥ 8 claims, each with own paths/attempts, `verification_jobs.json`, `verification_receipt.json`, `receipt_version` and `corpus_revision` in `verification.json`; resume rules re-verify on any mismatch; refuted additionally rewrites `confidence_reason` with a "Lowered to low by the independent check" note. `ambiguous` still never lowers confidence.

#### Slides, delivery and renderer
| Topic | Old | New |
|---|---|---|
| Plan validation | Titles, ids 1–11, known layouts, strict schema. | Plus `SECTION_SHAPES` (exact slide-count/layout per section), section 1 = one `opportunity` slide, section 5 = one collab with ≥ 2 parties, section 11 panels non-empty, 13 forbidden in a worker plan. |
| Speaker notes | None. | First page of a section: `CONFIDENCE: X / Reason: … / <check summary> / Sources: …`; every later page incl. "(cont.)": `Sources:` block grouped per file with Section / Page(s) / Chapter hierarchy; Source Material provenance columns moved into notes; inline "p. 12" annotations stripped from slide text into notes. |
| Visible citations | None (no evidence reached the plan). | None by design (`_source_line` exists but is never called). |
| Cover | Project name, "RFQ Insight", "Generated <ISO date>". | Opportunity name, "Update DD.MM.YYYY", AI-content disclaimer. Footer still prints the ISO date. |
| Section 1 slide | Model-written table/bullets. | App-built: 10-row table (Customer, Contact, Due date, Opportunity name, Account Name (Site), KAM (PTE), Project type, Lead product, Technology, Industry) + Products (%) + Skills (%). |
| Layouts | 12. | 14 (`pictures` retired, `opportunity` added); kpi/twoColumn/prosCons still render but no section may use them. |
| Sanitiser | `sanitize.py`. | Same logic moved into `planning.py` (ownership rows with unknown owners still vanish into an unrendered callout). |
| Output name | `<project>_RFQ_Analysis(_N).pptx/.json` | `RFQ Insight_<Opportunity name>_<DDMMYYYY>(_N).pptx/.json`, Windows-safe, path-length capped. |
| Quality gate | C1–C6, W1–W6; C5 warns. | Adds C1b (plan order incl. 13), C7 (notes start with "Sources:" or the not-found line), C8 (confidenceNotes on every rated section), C9 (strict plan + opportunity slide equals the analysis object), CP1 (pictures; trivially passes now). |
| Salesforce | — | `guidance.resolve_account`: exact-name tier only, disambiguated by the customer's own address (country, place parts, Korean/Chinese administrative suffixes, spelling table) or by a country named in the RFQ text; result → section 1 rows and a Document-Risk line; `lookup account/resolve/list` CLI. |

## 2. Verdict and scores

**Overall: the new version is the right direction and is already the better product, but it is shipped in a state I would not merge as-is.** It fixes the three things the client actually complained about (uncontrolled slide count, no traceability, Commercial Info not matching the client template) and adds real capabilities (follow-ups, comparison, account lookup). It does so at the cost of 2.5× more Python with zero tests and a Windows-only pagination path. The quality of the deck went up; the engineering hygiene went down.

### 2.1 Scores per skill / stage (1–10)

| Stage | Old | New | Why |
|---|---|---|---|
| Packaging, install, permissions | 7 | 5 | Hook removal is a client requirement (not a defect); new ships `__pycache__` with 9 retired modules; no README; `.github/plugin/plugin.json` for a host SKILL.md refuses. |
| Extraction (`extractors.py`, `corpus.py`) | 5 | 8 | New gives real section markers (31 on the sample docx vs 0), sha-per-file, revision tracking, verified PDF table de-dup. Minus: Chinese body sentences become "headings" (the body-sentence filter only knows `shall/must/is required`), Word pages only on Windows, `word-pages-*` temp dirs never deleted. |
| Figures (prompt v1→v2, `figures.py`) | 6 | 7 | Same transcription quality on the sample Gantt; v2 adds classification, batching of 6, receipts. The classification is now feeding nothing (picture slides retired) so it is cost without a consumer. |
| Analysis prompt + knowledge pack | 6 | 8 | `opportunity` object, Party-B identity rule, `confidence_reason`, `sources` with locators, confirmed-absence = high confidence, Guidance vocabulary: all correct and all visible in the sample output. Minus: 8.4k-word prompt; stage-1 caps (secs 3, 10, 11) delete content from the only deliverable (sample: 10 of 24 parameters, 3 of 16 standards, 5 of 21 risks dropped, disclosed only in notes). |
| Verification | 6 | 7 | Partitioning, run ids, receipts, resume gates are solid. Claims no longer truncated at 300 chars (old verifier complained about cut-off claims). Still: only "absence" and "inferred+digit" lines are checked; `ambiguous` never lowers confidence; stated numbers are never checked. Sample: 16/16 and 20/20 confirmed, so the check is cheap but not discriminating. |
| Slide planning (prompt v11→v13, `planning.py`) | 5 | 7 | `SECTION_SHAPES` enforced by the validator is the single most valuable change: the "Timing — TIMING BASIS" class of slide can no longer come from the model. Typed-presentation bypass is clever but the sample worker did not use it (and the canonical-serialisation proof will rarely match on real answers), so it is complexity with little expected use. |
| Renderer / deck | 5 | 7 | Notes with confidence reason, check summary and full source list on every content slide; app-built Opportunity Info; cover disclaimer; opportunity name on cover/footer. Minus: callout overflow still creates an extra "<Section> — DEPENDENCIES" page (sample slide 8), i.e. the renderer can still do what the model is forbidden to do; table pagination splits early and leaves half-empty pages (sample: Scope of Work 9 + 8 rows, Deliverables 8 + 7 rows); footer shows ISO date while cover shows DD.MM.YYYY; tiny table type (9.5 pt) unchanged. |
| Quality gate | 6 | 8 | C7/C8/C9/C1b are real gates for the new contract. C5 still only warns. |
| Workflow runtime / resume | 6 | 7 | `rfq_run.py next` removes ~30 coordinator decisions from the LLM, which is the right move. Resume rules are thorough. Minus: 28-pass loop, attempt counters, receipts and telemetry are all untested; `MSG_TOO_LARGE` dead; `event` ValueError exits 2 instead of JSON. |
| Follow-up Q&A | – | 7 | Complete, local, revision-aware, validated. Not exercised in this review. |
| Comparison decks | – | 6 | Deterministic, no model. Fuzzy pairing at 0.6 will mis-pair rows; untested. |
| Salesforce account/KAM lookup | – | 7 | Worked first time on the sample (exact name, country from text → "Hao Tong"). Exact-tier-only is the right conservatism. |
| Tests / maintainability | 8 | 2 | Old: 385 passing tests. New: none shipped; 15 of 20 old modules cannot import, 32 of the 89 that run fail. ~635 KB of Python with no safety net. |
| Data governance | – | – | `accounts.csv` stays in the package by decision (private distribution). |
| **Weighted overall** | **6.1** | **6.6** | New wins on output quality and features; loses on hygiene, test coverage and data handling. |

### 2.2 The knowledge-pack ("notes") changes, judged one by one

| Change | Verdict |
|---|---|
| `90_guidance_denominators.md` generated from the Guidance xlsx, with descriptions | Good. The old `70_` list had drifted (e.g. "Fuell Cell", a CSM definition that was simply wrong). One generated source of truth is right. Keep the generator in the repo, not only in `Backlog/`. |
| `70_`: CSM redefined as "full component responsibility incl. Component Supplier Management" | Correct; the old "customer-specific modification" definition was a misreading. |
| `70_`: Off-Road / Special Purpose rewritten (Special Purpose = defence/dual-use only) | Correct per the Guidance table, but it reverses the old "decision test". Any earlier classification made with the old rule is now wrong; nothing in the package flags that. |
| `70_`/`80_`: Lead product = "dominant enabler… ≥ 5 %… not necessarily the largest share" | Correct per Guidance, but it makes Lead product a judgement call that the validator cannot check beyond the 5 % rule. |
| `20_`/`60_`: Standards no longer "completeness beats selectivity"; 13-row cap with count disclosure | The most debatable change. Standards are the one section where a missed norm costs money. Capping the slide is a client wish; capping the *analysis* throws the data away (the dropped rows exist nowhere, not even in notes). The sample lost 3 of 16. |
| `20_`: Collaboration Approach bullet + "No further parties are named in the RFQ." sentinel | Good; the sentinel is also a verifiable claim. |
| `20_`: Account/KAM "looked up by the application, never written by you" | Good separation. |
| `10_`, `30_`: renames only | Fine. |
| `40_`, `50_`: untouched | Fine, but `50_` still describes phase handling that now feeds a table-vs-phases choice the slide prompt makes; worth a one-line note. |

### 2.3 Concerns, ranked

1. **No tests for the new runtime.** The old suite is 385 tests; the new code has none and silently breaks 15 of the 20 old modules. Everything in section 2.1 that I called "solid" is read-from-source, not proven.
3. **Caps applied at analysis time delete evidence.** Standards and Technical Targets rows dropped by stage 1 are gone; only a count survives in notes. Keep the full list in the analysis (and therefore the JSON report and notes) and let the renderer cap the visible rows.
4. **Renderer can still add slides.** Callout overflow produced "Collaboration Approach — DEPENDENCIES" in the sample; the client's exact complaint, now coming from Python instead of the model.
6. **Early pagination.** Long phase names in the ownership header leave the Scope-of-Work page half empty and push 8 rows to a continuation page. Same for Deliverables.
7. **Windows-only page numbers.** On Linux/macOS hosts (Cowork sandboxes included) every Word citation reads "Page: unavailable". The design is honest, but the client will see it on most runs.
8. **CJK heading over-capture.** Numbered Chinese sentences ("5.1 本技术协议为主合同…") become 180-char section names and then citation locators.
9. **Prompt size and dual contracts.** The analysis prompt now carries the slide-plan schema (typed presentation) plus the `ref_id` catalogue grammar. Two ways to cite and two ways to plan is more surface for a worker to get wrong, for a bypass the sample never triggered.
10. **Dead code shipped.** Picture slides (`plan_pictures`, `L_pictures`, `PICTURE_NOTES`, `RATING_GUIDE`, `CP1`), `MSG_TOO_LARGE`, `_source_line`, 9 orphan `.pyc` files.
11. **Smaller:** footer ISO date vs cover DD.MM.YYYY; `add_followups` ignores `downgrades`; verification/followup workers get the raw corpus with no 600k gate; `word-pages-*` dirs never cleaned; `_phase_traceable` docstring says 70 %, code says 55 %; `.github/plugin` manifest for a refused host.

## 3. Section-by-section: what each version produces (sample RFQ, same corpus, same models)

Run facts: both runs used Opus for analysis/verification/slides and Sonnet for figures, one attempt per stage, no repairs. Old deck: 14 plan slides → 22 physical pages, 0 notes. New deck: 14 plan slides → 20 physical pages, notes on every content page. Old gate 0 fail / 2 warn; new gate 0 fail / 1 warn. Decks: `run_old/VHE30TD/output/VHE30TD_RFQ_Analysis.pptx`, `run_new/VHE30TD/output/RFQ Insight_Aurobay – VHE30TD…_14102026.pptx` (both in the scratchpad, sent with this report).

| Section | Old (v12 / v11) | New (v13 / v13) |
|---|---|---|
| Cover / TOC / end | "VHE30TD" (folder name), "Generated 2026-10-14", 11 TOC entries. | "Aurobay – VHE30TD High Performance Engine Development and Improve", "Update 14.10.2026", AI disclaimer, 12 TOC entries. Footer still "2026-10-14". |
| 1 Commercial / Opportunity Info | Model-written 7-row table (customer, contact, due date, product type, lead product, technology, industry). "SOP Project w/o CSM" short form. | App-built 10-row table + Products (%) + Skills (%). Account "Aurobay (Ningbo) Intelligent Technology Co., Ltd.", KAM "Hao Tong" from the lookup. Full Guidance name "SOP Project w/o CSM (up to SOP or partial SOP development)". Opportunity name drives file name and cover. Note: `customer_site` came back "Info not available" although the signing address is in the document; lookup still resolved via "China" in the text. |
| 2 Source Material / Description | Source Material as section 2: file + "referenced but not in corpus" list. Summary as section 3. | Description as section 2 (five paragraphs, same substance, Party B explicitly "unnamed contractor"). Source Material moved to 12, one bullet, file-level source. |
| 3 Technical Targets | 16-row table incl. air-path boundaries, oil consumption, gasket durability, design constraints. Fits one slide. | 14-row table with a Unit column; 4 boundary-condition rows deliberately dropped and disclosed in notes. Fits one slide. |
| 4 Application Approach | One wide 5-column row (incl. "Target markets" inferred as China/Europe/USA). Parties live in the same section's answer. | 6-row key/value table, no inferred markets, parties removed to section 5. |
| 5 Application → Collaboration | Collab diagram as the second slide of Application Approach, 5 parties (incl. "Gasket supplier"), callout "Party B is left blank…". | Own section; 5 parties; callout overflowed into an extra "Collaboration Approach — DEPENDENCIES" page with four lines of prose. Notes carry 6 source locations. |
| 6 Development Phases | Chevron diagram, 5 phases, callout for JOB1 as out of scope. | Model chose a 5-column table (scope status + calendar span + HW flag) instead of chevrons; same phase names. |
| 7 Scope of Work | 10 rows × 5 short "Phase N" columns on one slide; two tasks with "—" in every column (no acceptance phase). | 17 rows × 5 full-name phase columns; header four lines tall; split 9 + 8 across two pages with the first half empty. Adds "Project management", "Joint review" (Joint ×3), failure-handling rows. |
| 8 AVL Deliverables | 14 rows on one slide, phase column "No acceptance phase assigned" for the review. | 15 rows with "Phase / Task" linkage, split 8 + 7 over two pages. |
| 9 Timing | Gantt: 6 milestones, bars Phase 1, Phase 2, Phase 4; table 10 + 9 rows over two pages. | Gantt: 6 milestones, bars Phase 1 and Phase 4 only (Phase 2 span dropped as "no stated start"); table 14 rows on one page, adds LOI/return-of-materials/extension rows. |
| 10 Standards | 12 + 11 rows over two pages, mixes emission regs, test protocols, tool requirements, IP clauses, formats, a "no ISO/IATF…" row. | 13 rows, one page, 3-column (Area / Requirement / Applies to); 3 items dropped and named in notes. W2 warning "Order of precedence" (a label, not a standard). |
| 11 Risk Detection | 21 project risks over 3 pages + 11 document risks over 2 pages, mostly half-empty panels. | 8 + 8 items on exactly two pages; 2 project risks and 3 document risks dropped and named in notes; the "schedule feasibility" item is first in both. |
| 12 Source Material | (was 2) | See above. |
| Notes | None. | First page of each section: `CONFIDENCE`, `Reason:` (the model's confidence_reason), `Check: N statements reviewed by a separate reviewer…`, `Sources:` grouped by file with section path and "Page: unavailable; find the section named above." Continuation pages: sources only. |
| Verification | 16 claims (3/section cap), 1 worker, all confirmed; verifier flagged 6 truncated claim strings. | 20 claims, 4 partitions, all confirmed; no truncation. |
| Account risk | – | None added (lookup matched). Would have been a Document Risk otherwise. |

## 4. Direction

Keep the new architecture. Do not keep developing it in a zip outside the repo. Concretely, in this order:

1. **Land the new runtime on a branch of this repo and make the test suite green again.** Port what still applies (extractors, dates, schema invariants, renderer, manifests) and write new tests for `pipeline._resume_rules`, attempts/repair, `sources.locator_exists` + `reference_catalogue`, `verification` partitions/receipts, `planning.deterministic_plan` (one positive, several negative cases), `validation.check_plan` against `SECTION_SHAPES`, `guidance.resolve_account` (the Aurobay case plus an ambiguous one), `followups` and `comparison`. Target: every stage reachable by `rfq_run.py next` has at least one offline test, and `claude plugin validate --strict` passes.
2. **Move the caps from analysis to presentation.** Stage 1 keeps every standard, target row and risk; the renderer (or `planning.sanitize_plan`) selects the visible 13 / 14 / 8 by the same materiality order and puts the rest in the notes under "Not shown on slide". Then the JSON report, follow-ups and comparisons still see the full data, and the client still gets one slide.
5. **Close the two renderer leaks that recreate the client's complaint:** callout overflow must shorten/move text into notes instead of creating "— TAG" pages; table pagination must measure the real header height (long phase names) and fill the page before breaking. Add a test that asserts the physical page count per section equals the `SECTION_SHAPES` count plus genuine overflow only.
6. **Fix extraction edges found on the sample:** reject numbered body sentences as headings for CJK text (length and punctuation heuristics, not only English cue words); delete `word-pages-*` scratch dirs; document plainly in the deck notes that Word page numbers need a Windows host, or add a LibreOffice-based pagination fallback (it is already present in Cowork-style sandboxes and converts docx → pdf, which gives real pages).
7. **Simplify the analysis contract.** Either commit to the typed `presentation` bypass (and then test it on five real RFQs to see how often it fires) or remove it and the `ref_id` grammar from the v13 prompt; a 177-line prompt with two optional sub-contracts is where the next regression will come from.
8. **Make verification discriminating.** Add stated numbers/dates (not only inferred ones) to the harvest, let `ambiguous` lower confidence to medium, and surface the "N statements were not checked" line already in the notes as a W-level gate.
9. **Delete the retired picture pipeline** (`plan_pictures`, `L_pictures`, `CP1`, `PICTURE_NOTES`, `RATING_GUIDE`, `pictures` layout) and the orphan `.pyc` files, or keep classification only if a consumer is planned.
10. **Then** run the live acceptance checklist in `docs/VALIDATION.md` on both hosts with two real packages (one PDF-heavy, one Word-only on a Windows host) and record the results in `CHANGELOG.md` before tagging 1.1.0.

What I would not do: go back to the old 14-script workflow, reintroduce the 11-section layout, or try to make the slide-plan model responsible for slide counts again. The new split (Python owns structure, model owns content) is correct.


## Decisions taken after review (2026-10-14)

- Approval hook stays removed (client requirement).
- `accounts.csv` stays in the package (private distribution).
- Still to carry over from the old repo: tests, docs, packaging script.

## Follow-up rework (2026-10-14)

What changed after the review, and why. Version 1.1.0.

- **Codex is the primary host**; Claude stays supported with the same skill. Client request.
- **Section modes** (`schema.SECTION_MODES`): 3–10 extracted, 2 and 11 analysed, 1 mixed, 12 Python. Extracted content was never checked before; now the mode decides what is allowed and what is verified.
- **Confidence scored out of 10** from a fixed rule catalogue (`schema.RULES`, `confidence.py`); bands High 7–10, Medium 4–6, Low 1–3. Nine of twelve sections came back "medium" on the sample, section 1 only for doing its job; the score now says exactly what cost points.
- **The model lists deductions, Python scores them.** The model never writes a number, so scores are comparable across runs and hosts.
- **Notes rewritten**: `Confidence N/10 (Band)`, one line per deduction with items and basis, `Check:`, optional `Shown:`, then Sources. The 900-character free-text reason is gone.
- **Chip** reads `Medium · 6/10`, same colours.
- **Faithfulness gate** (`validation.check_faithfulness`): standards, dates, number+unit pairs, phase names, owner cells, deliverable ids and party names must occur in the corpus; three repairs, then V3 deductions. Catches invented values before verification.
- **Verifier v3**: round-robin harvest of absence, derived, stated and trigger claims, up to 6 per section and 48 per run, partitions of 8 in parallel; refuted and ambiguous verdicts become V1/V2 deductions. The old harvest never looked at stated values and only "refuted" had an effect.
- **Analysis prompt v14**: numbered, non-repeating rules, the two-mode rule, fixed markdown shapes per section, deduction codes; no `tldr`, no typed `presentation`, no section 12. Shorter input and output.
- **Slides built in Python** (`planning.typed_from_markdown`) from the answers' fixed shapes; the slide worker (prompt v14) runs only when a section does not parse. The sample's slide worker took 3.8 min and the typed bypass never fired.
- **Section 12 built by the runner** from the corpus and the source catalogue (`File | Type | Read | Used by sections`, P12.1/P12.2). No model needed for a file list.
- **Section 13** carries the lowest score of its follow-ups; follow-up prompt v2 declares mode and deductions per answer, and extracted answers pass the faithfulness gate (dates, standards, number+unit).
- **`(inferred)` stays visible** on slides, in amber. Inferred content no longer looks like extracted content.
- **Coordinator round trips**: `next --completed <id> --failed <id>` records terminal events and advances in one call; `event` only for an optional `started`. One command per round on Codex instead of one plus N.
- **Figures v3**: one `.txt` per picture, no classification file. The classification fed nothing since picture slides were retired.
- **Figure outputs**: where sections 1.2, 1.6 and 1.8 above describe two outputs per picture (`.txt` + `.json` classification), that is superseded: figures now produce one `.txt` each, and the figure stage archives a leftover classification `.json` once.
- **Routes**: Codex analysis `high`, every other route `medium` (`models.json`). Knobs for the client to A/B on its account.
- **Render time** per deck from about 6 s to about 0.2 s (gradient cache).
- **Comparisons** show section scores side by side (`7/10 → 5/10`).
- **Older runs**: `render` replays their stored notes; `add-followups` on one is blocked with "The RFQ analysis predates the current scoring; run the analysis again before adding follow-ups."
- **Tests**: 1,236 (was 906).

Still open: live Codex run times were not measured here (record them with `rfq_run.py timing` per `docs/VALIDATION.md`); Word page numbers still need Windows with Word.
