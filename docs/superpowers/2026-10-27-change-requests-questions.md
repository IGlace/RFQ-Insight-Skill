# RFQ Insight change requests (K. Petinger, 23 Oct 2026): open questions

Fill in the answer lines and return the file. Each item names the request
slide it belongs to, what I found in the current plugin (1.1.0 + unreleased),
my recommended default, and the decisions only you or the use-case owner can
make. Tick the box you want or write an answer; "default" means I go with the
recommendation. Everything ships in one release.

Legend: `CR n` = slide n of "RFQ Insight_Change Requests.pptx".

---

## 0. General

**0.1 Host and scope.** The screenshots come from the Codex desktop app
(ChatGPT / Codex). Should every change work the same on Claude Code, Claude
Desktop Cowork and Codex, or is Codex the only host the owner uses?

- [ ] All hosts, same behaviour (default)
- [ ] Codex only; Claude hosts keep current behaviour where a change is host-specific
- Answer:

**0.2 Completeness.** Is this deck the full list, or are there verbal
requests or earlier feedback (14 and 15 Oct 2026 are referenced in the code)
still open that should ride along?

- Answer:

**0.3 Acceptance.** Who signs off: you from the deck on the synthetic RFQ,
or the owner on a real package? If the owner, which package (so I can keep
its characteristics in mind: German, large, scanned, ...)? Do not send the
package itself.

- Answer:

**0.4 Version.** The CHANGELOG has an "Unreleased" block from the 15.10.2026
requirements. Ship everything as 1.2.0?

- [ ] 1.2.0 (default)
- [ ] Other:

---

## 1. Deck format and wording

### CR 4 — AVL standard format

Found: the footer bar, title and gradient underline are drawn by the
renderer by hand (`rfq/renderer.py::footer`), reading `Internal · <page> |
RFQ Insight | <project> | <date> | logo`. The owner's own deck uses the real
AVL master: `Internal / <page>` left, `<author> | <department> | <date>`
right, AVL logo, gradient bar.

**1.1 Template source.** The cleanest fix is to build on the official AVL
PowerPoint template instead of drawing the frame. Can you provide the
official `.potx` (or a blank `.pptx` saved from it)? If not, I can extract
the slide master from the change-request deck you sent and use that.

- [ ] I will provide the official template (attach it with your answers)
- [ ] Use the master from the change-request deck (default if nothing arrives)
- [ ] Keep drawing by hand, only match the footer wording and fonts

**1.2 Footer content.** What should the three footer fields say on a
generated deck? The AVL master shows author | department | date.

- Left label ("Internal / page" today): ____________________
- Right field 1 (author today "RFQ Insight"): ____________________
- Right field 2 (department / project): ____________________
- Date format (`2026-10-20` today, owner's deck `23 Oktober 2026`): ____________________

**1.3 Fonts and title style.** The renderer uses Verdana throughout. The AVL
deck uses a different family (looks like Inter/Arial). Match the template's
fonts everywhere, including tables and diagrams?

- [ ] Yes, template fonts everywhere (default)
- [ ] Titles only; keep Verdana in tables for fit
- Answer:

**1.4 Classification label.** Keep "Internal" as the document class, or
should it be configurable per run?

- [ ] Always "Internal" (default)
- Answer:

### CR 3 — Products & Skills (%) in the table of contents, headline format

Found: the Products & Skills (%) slide is the second slide of section 1
(shape `opportunity + split`). The TOC lists the twelve sections only. Its
title is drawn bold, unlike the other section titles (that is the "different
font format" the owner means; the template work in CR 4 fixes the style).

**1.5 TOC entry.** How should it appear?

- [ ] As its own numbered entry after "Opportunity Info", renumbering the rest 3–13 on the TOC only (section ids stay 1–12 internally)
- [ ] As a sub-entry "1a Products & Skills (%)" under Opportunity Info (default)
- [ ] Make it a real section 2 everywhere (changes the section contract, the prompts and the comparison deck; largest change)
- Answer:

**1.6 Other missing entries.** Should "Additional Information" (follow-up
decks) and the hidden "Confidence Scoring Methodology" slide be listed in
the TOC too?

- [ ] Additional Information yes, methodology no (default)
- Answer:

### CR 5 — "Info not available" in text areas

Found: the analysis prompt makes every missing field exactly "Info not
available" (rule 3.5); in tables that is right, in prose it yields "The
quotation due date is Info not available."

**1.7 Prose wording.** What should a sentence say when a fact is missing?

- [ ] "... is not available." (owner's suggestion)
- [ ] "... is not stated in the RFQ." (default; says why it is missing)
- Answer:

**1.8 Where.** Apply to prose only (Description, callouts, risk items,
follow-up answers) and keep "Info not available" in table cells and the
Opportunity Info values?

- [ ] Yes (default)
- Answer:

### CR 6 — "Definition according to RFQ" column header

Found: `rfq/opportunity.py` sets the header for the Opportunity Info,
Products (%) and Skills (%) tables.

**1.9 Scope.** Change the header to "Definition" on the Products (%) and
Skills (%) tables only, keep "Definition according to RFQ" on the main
Opportunity Info table?

- [ ] Yes (default)
- [ ] Change it on all three tables
- Answer:

### CR 8 — Timing format

Found: the screenshot shows a milestone card where the bold description text
overlaps the step label and the "Concept documentation submission" text. That
is a layout defect in the timeline layout (long label plus long description
in one card), not a date-format problem.

**1.10 Confirm.** Is the request the overlap only, or also the date
format / the way milestones are labelled?

- [ ] Overlap only (default)
- Answer:

**1.11 Long descriptions.** When a milestone description does not fit its
card, which is preferred?

- [ ] Shorten the description to the card and keep the full text in the notes (default)
- [ ] Shrink the type size down to 9 pt before shortening
- [ ] Fewer milestones per slide, continuation slide
- Answer:

### CR 9 — Dotted line and "(inferred)" in the collaboration diagram

Found: a party whose cell contains "(inferred)" gets a dashed connector
(`rfq/planning.py`), and the tag is appended to the end of its description.

**1.12 Dashed line.** Remove the dashed style for inferred parties
everywhere (collaboration diagram, Gantt bars, phase chevrons), so the amber
"(inferred)" tag is the only marker?

- [ ] Yes, remove it (default)
- [ ] Keep it in addition to the tag
- Answer:

**1.13 Tag placement.** Put "(inferred)" beside the specific thing that is
inferred: after the party name when the party or its role is inferred, after
the inferred phrase inside a description when only part of it is inferred?

- [ ] Yes (default)
- [ ] Always after the party name
- Answer:

### CR 11 — "entailed deliverables" and CR 7 — G3, P1 in the notes

Found: these are the literal labels and codes of the deduction catalogue
(`rfq/schema.py::RULES`), printed into every slide's notes as
`S8.1  8 entailed deliverables: ...`. The hidden methodology slide explains
the codes, but the owner did not find it.

**1.14 Codes in notes.** How should a deduction line read?

- [ ] Plain words only, no code: "8 deliverables implied by the scope but not listed: ..." (default; codes stay in the run report)
- [ ] Plain words with the code at the end in brackets: "... [S8.1]"
- [ ] Keep the code first, add the plain phrase
- Answer:

**1.15 Methodology slide.** Keep it hidden at the end, make it a visible
last slide, or drop it?

- [ ] Keep hidden (default)
- [ ] Visible
- [ ] Drop
- Answer:

**1.16 Labels to rewrite.** I will rewrite every rule label in plain English
(for example "entailed" → "implied by the scope but not listed", "derived"
→ "calculated from stated values"). Any terms the owner uses that I should
prefer? Any phrase that must stay?

- Answer:

---

## 2. Result always in English (CR 10)

Found: German RFQs leak German into prose ("Fahrsystem", "Projektstart",
"Konzept-Freeze") and whole table rows. The prompt has no language rule. A
rule alone is not enough: the faithfulness gate requires phase names,
standards, party names and deliverable ids to occur verbatim in the corpus,
so a translated phase name would cost points.

**2.1 Customer-named items.** Phases, milestones, documents and departments
that the customer names in German (e.g. "Konzept-Freeze", "Lastenheft",
"Fahrversuch"): how should they appear?

- [ ] English translation with the original in brackets on first use: "Concept Freeze (Konzept-Freeze)" (default; the gate accepts the bracketed original)
- [ ] Original only, as the customer wrote it
- [ ] English only, no original
- Answer:

**2.2 Standards and ids.** Customer standard designations (e.g. "VW 80000",
"Werksnorm 123") and deliverable ids stay verbatim. Agree?

- [ ] Yes (default)
- Answer:

**2.3 Quotations.** When the deck quotes a clause (risk triggers, Check lines
in notes), quote the original and add an English translation, or translate
only?

- [ ] Original quote plus translation in the notes; translated on the slide (default)
- Answer:

**2.4 Enforcement.** I plan a Python language check after the analysis
(share of German function words per field) that sends the answer back for
repair, like the other gates. Any other languages to expect beyond German
and English (French, Chinese, Korean, Japanese packages exist in the
account list)?

- Answer:

**2.5 Follow-up answers.** Always English too, even when the question is
asked in German?

- [ ] Always English (default)
- [ ] Answer in the language of the question
- Answer:

---

## 3. Skill-area allocation in Scope of Work (CR 12 and the two PDFs)

Found: the knowledge file `80_avl_nomenclature_and_skill_areas.md` lists ten
areas with codes that no longer exist (DD-D, DD-S, DM-V / DM-I). The PDFs
give the structure effective 1 Nov 2025: eleven skill areas (DS, DD, DM, DC,
DJ, DF, DK, DP, DO, DR, DI) and about forty skill teams with lead groups.
Today each Scope-of-Work row starts with the area, e.g. "Functional
Development (DS): module system engineering ...".

**3.1 Granularity.** What should one Scope-of-Work row be?

- [ ] One row per skill area in scope, as today, with the new eleven areas (default)
- [ ] One row per skill team in scope (e.g. "Vehicle Integration & Structure (DSV)"), grouped under the area
- [ ] Area rows, with the skill team named in the description when it is clear
- Answer:

**3.2 Presentation.** Keep the area as a prefix in the task cell, or add a
dedicated "Skill area" column to the matrix?

- [ ] Prefix in the task cell, as today (default)
- [ ] Separate first column "Skill area"
- Answer:

**3.3 Content of the knowledge file.** I will rewrite it as a mapping aid:
every area and team, its lead groups, and the kinds of RFQ tasks that belong
to it (e.g. FMEA, purchasing and product quality → Component, Cost &
Supplier Engineering DMC; OBD → DCO; cybersecurity and SOTIF → DJF). People's
names stay out. Agree? Anything the PDFs do not say that the owner applies
in practice (typical mis-assignments, areas that never appear in RFQs)?

- Answer:

**3.4 Business units.** The CEO information also defines four business
units (L1 ICE-based Powertrain, L2 Fuel Cell & Energy, L3 Electrification,
L4 Vehicle). Should the deck name the responsible business unit anywhere,
for example in Opportunity Info?

- [ ] No (default)
- [ ] Yes, in Opportunity Info as: ____________________
- Answer:

**3.5 Project management and quality rows.** DP and DO almost always apply
to a project. Should the matrix always carry a DP row (and DO) even when the
RFQ does not spell out project management, marked "(inferred)"?

- [ ] Only when the RFQ states or clearly implies it (default)
- [ ] Always, tagged inferred
- Answer:

**3.6 Products and Skills (%).** The Skills (%) table uses the Guidance
Document's skill list (Functional Development, Simulation, Design, ...),
not the organisation's areas. Keep that list as is, or align it to the
eleven areas?

- [ ] Keep the Guidance list (default; it comes from the Guidance workbook)
- [ ] Align to the eleven areas
- Answer:

---

## 4. Upload RFQ documents via the chat window (CR 2)

Found: today the request must name a folder (or Cowork's connected folder).
The interaction contract forbids questions, so "ask for folder name" is a
deliberate exception. Where attached files land differs per host: Codex and
Claude Code put chat attachments in a temporary location only the agent
sees; Cowork works on the connected folder.

**4.1 Target area.** Where should the new folder be created?

- [ ] A fixed RFQ root per machine, configured once (e.g. `RFQ_INSIGHT_ROOT` or `~/RFQs`): ____________________
- [ ] Inside the current working folder of the session
- [ ] Ask the user for the full path every time
- Answer:

**4.2 Folder name.** Ask for the name, or default to something and only
ask when it cannot be derived?

- [ ] Always ask once: "Which folder name should I use for this RFQ?" (owner's wording)
- [ ] Derive from the attachments (first document's name or the customer name on the cover) and ask only if that fails
- Answer:

**4.3 Existing folder.** If the folder already exists: add the files
(and let resume detect the change), refuse, or ask?

- [ ] Add the files, re-read on the next run (default)
- [ ] Refuse with one sentence
- Answer:

**4.4 Then run.** After copying, start the analysis immediately in the same
turn, or confirm the folder first?

- [ ] Start immediately (default)
- [ ] Reply with the folder path and wait
- Answer:

**4.5 Hosts.** Which hosts must support this? Codex desktop is the one in
the screenshot; Claude Code attachments arrive as file paths too; Cowork
has no attachment flow outside the connected folder.

- Answer:

---

## 5. E-mail as an input (CR 13)

Found: Outlook `.msg` is skipped by design; `.eml` is not read either.
Cover e-mails often carry the deadline, contacts and attachments.

**5.1 Formats.** Which e-mail formats arrive in practice?

- [ ] Outlook `.msg` (default)
- [ ] `.eml`
- [ ] Both
- Answer:

**5.2 Attachments.** Extract the attachments inside the e-mail and treat
them as package documents (PDF, Word, Excel inside the mail), including
nested e-mails?

- [ ] Yes, attachments become documents cited as "mail.msg › Appendix.pdf" (default)
- [ ] Body text only
- Answer:

**5.3 Headers.** Put From, To, CC, date and subject into the corpus (they
feed the contact sweep in Opportunity Info)?

- [ ] Yes (default)
- Answer:

**5.4 Source Material.** List the e-mail as one source with its
attachments indented under it?

- [ ] Yes (default)
- Answer:

**5.5 Dependency.** Reading `.msg` needs one more library in the toolbox
venv (`extract-msg`, pure Python). Any objection, or a preferred library?

- Answer:

---

## 6. Anything else

- Things in the owner's deck I misread:
- Requests not in the deck:
- Order of priority if something has to slip:
