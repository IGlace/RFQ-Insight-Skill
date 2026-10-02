# Scope of Work separation and single-owner responsibility mapping

Our report uses a deliberately simplified ownership model: **one task, one
primary owner, per development phase** — a single-owner table, NOT a
multi-letter RACI/RASI/RASIC matrix, even when the source contains one.
This file explains how to build it correctly from whatever the corpus offers.

**Cell fidelity is the governing rule (client-mandated):** the table's
empty/filled pattern MIRRORS the source. A task×phase cell is filled only when
the corpus assigns a party to that task in that phase; a cell the corpus
leaves unassigned stays empty ("—"). The transformation this file describes is
purely mechanical — translating the source's own notation (RASIC letters,
prose assignments) into one owner name per assigned cell. It never adds
assignments the source doesn't make, never extends an owner into phases the
source doesn't cover, and never resolves a gap by judgement. A reader holding
only the RFQ files must be able to reproduce the exact same pattern.

## The source formats you will meet

- **RACI**: Responsible (does the work), Accountable (single ultimate owner —
  exactly one A per task), Consulted (two-way input), Informed (one-way).
- **RASI**: RACI variant with S = Support instead of Consulted.
- **RASIC (dominant in automotive SOWs)**: R = Responsible (executes/owns),
  A = **Approve** (signs off/releases — NOT "accountable"), S = Support,
  I = Inform, C = Consult.
  ⚠ Trap: in RACI the owner is the **A**; in automotive RASIC the owner is the
  **R** and A is the customer's sign-off authority. Misreading this inverts
  ownership. Always read the table's own legend — some documents redefine the
  letters non-standardly.
- Plain prose ("The Supplier shall…", "McLaren-style: Customer provides…") and
  deliverable tables with "agreed with / approved by Customer" phrasing.

## Deriving the single owner

1. Owner = the party that EXECUTES the task (RASIC "R"; RACI "R" as well —
   for our table, the doer wins over the sign-off authority).
2. Customer approval rights (RASIC "A", "subject to Customer release") are NOT
   ownership — do not move the row to the customer. But an approval step on the
   critical path is a schedule dependency: if approvals gate design releases or
   payments, note it (Timing or Risk, wherever it bites).
3. "S"/"C"/"I" roles never appear in our table. If the supplier is only S on a
   customer-owned task, the row stays with the customer — but supplier Support
   effort is unpriced work: if it looks substantial, flag it in Risk Detection.
4. Multiple R's on one row, or the same task assigned differently in two
   documents: record ONE primary owner ONLY if the source itself singles one
   out (the more specific/primary document, or the party the deliverables
   list names as producer). If the source does not, write **"Joint"** in the
   cell and raise the dual assignment as a Document Risk. Never split the row,
   never name both parties in the cell, never silently pick, and never choose
   by plausibility.
   **"Joint" is a flag, not a fourth owner.** It says the source assigns this
   task to two or more parties and settles nothing; the risk entry is what
   names them and what a reader acts on. The deck colours it amber, away from
   the party colours, so it cannot be mistaken for an answer — the client
   rejected a multi-letter RASIC matrix, and this must not smuggle one back.
5. Empty cells mean nothing by themselves — some matrices imply "not involved",
   others imply "informed". Do not infer obligations from blank cells, and do
   not FILL blank cells either: a task×phase the source leaves unassigned
   stays "—" in our table, even when every other phase of that row has the
   same owner.
   Keep "—" and "Joint" apart. They were once the same glyph, which made the
   matrix lose a fact it was holding: "the RFQ assigns nobody to this" and
   "the RFQ assigns two parties to this" are different findings with different
   actions — chase a gap, versus split an overlap before contract. A merely
   TBD or unclear owner is a gap, so it is "—", not "Joint".

## Party normalization

Exactly three owner values name a party in the table: **AVL** (or the engineering
partner if the RFQ addresses a generic supplier — map "the Supplier",
"engineering partner", "Auftragnehmer" to AVL when AVL is the bidder),
**the customer** (use the established abbreviation — VF, MAL, etc.), and
**Supplier** (= any third party: sub-supplier, component supplier, tooling
maker, single-source partner). If several distinct third parties matter, keep
them distinct in the Application Approach parties list, but the ownership table
still says "Supplier" — the table shows who AVL faces, not the whole network.

Two further cell values are not parties: **"Joint"** (the source assigns the
task to two or more parties and singles none out) and **"—"** (the source
assigns nobody). See rules 4 and 5 above.

## Phase columns

- Columns = ONLY the phases in the scope of this RFQ/SOW (from the Development
  Phases answer). Phases mentioned as future/adjacent work get no column.
- Responsibility can shift between phases (supplier designs in A-phase,
  customer industrializes from C-phase) — that shift is exactly what the
  per-phase columns exist to show; never flatten it away.
- If the source is not phase-structured, use a single Owner column
  (Task | Development Stage | Owner).

## Building the row list

- Rows = key work packages (see the level-of-detail guide): specification,
  design/CAD, simulation/CAE, drawings/release, DFMEA, DVP, procurement,
  build, testing, testing support, software, calibration, functional safety,
  cybersecurity, industrialization, vehicle integration — whichever of these
  the corpus actually assigns, plus corpus-specific packages.
- Reconcile the matrix against the SOW text: a task in the RASIC but absent
  from the SOW narrative (or vice versa) silently expands scope — include it
  with its owner and flag the mismatch if material.
- Explicit AND implicit tasks: an acceptance criterion or deliverable implying
  work ("DVP agreed with Customer prior to testing") creates a row even if no
  matrix lists it.
- Sourcing strategy (off-the-shelf/carry-over use, open-book procurement,
  minimum-quote rules, tooling ownership) is scope context: record it with the
  scope section, not as a table row.

## Consistency obligations

The ownership table must agree with the rest of the report: every phase column
exists in Development Phases; every deliverable's producing task appears as a
row owned by AVL (or the mismatch is flagged); ownership conflicts raised here
appear under Risk Detection, not as footnotes.
