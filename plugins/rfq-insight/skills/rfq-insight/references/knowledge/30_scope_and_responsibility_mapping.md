# Scope of Work separation and single-owner responsibility mapping

The prompt's section 7 rule fixes the single-owner table (one task, one owner
per phase) and its cell values. This file explains how to read the source's
notation into it — mechanically, never adding an assignment the source does
not make.

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

## Deriving the single owner

1. Owner = the party that EXECUTES the task ("R" in RASIC and RACI alike):
   the doer wins over the sign-off authority.
2. Customer approval rights (RASIC "A", "subject to Customer release") are NOT
   ownership — do not move the row to the customer. An approval step on the
   critical path is a schedule dependency: if approvals gate design releases or
   payments, raise it in Risk Detection.
3. "S"/"C"/"I" roles never appear in our table. If the supplier is only S on a
   customer-owned task, the row stays with the customer — but supplier Support
   effort is unpriced work: if it looks substantial, flag it in Risk Detection.
4. Several R's on one row, or one statement naming two or more parties
   jointly: "Joint" — a flag, not a fourth owner — unless that same source
   singles one out as executor. Different files or tables giving the same
   task to different parties: "—" and a Document Risk naming both (no
   deduction). Never split the row.
5. Empty matrix cells mean nothing by themselves — some matrices imply "not
   involved", others "informed". Never infer obligations from them. "—"
   (nobody assigned, or TBD) and "Joint" (two parties, none singled out) are
   different findings: chase a gap, versus split an overlap before contract.

## Party normalization

- **AVL** — AVL itself. A generic contractor term ("the Supplier",
  "engineering partner", "Auftragnehmer", "Party B") becomes AVL only under
  the prompt's contractor-identity rule: AVL is the bidder, so the requested
  work is AVL's proposed scope, but the appointment is an inference that
  Collaboration Approach and Risk Detection declare. If the RFQ names another
  contractor, its obligations are not AVL's.
- **The customer** — its established short name (VF, MAL, etc.).
- **Supplier** — any third party: sub-supplier, component supplier, tooling
  maker, single-source partner.

## Phase columns

Responsibility can shift between phases (supplier designs in A-phase, customer
industrializes from C-phase) — that shift is what the per-phase columns show;
never flatten it away.

## Building the row list

- Rows = key work packages at skill-area level (see
  80_avl_nomenclature_and_skill_areas.md): specification, design/CAD,
  simulation/CAE, drawings/release, DFMEA, DVP, procurement, build, testing,
  software, calibration, functional safety, cybersecurity, industrialization,
  vehicle integration — whichever the corpus actually assigns, plus
  corpus-specific packages.
- Reconcile the matrix against the SOW text: a task in the RASIC but absent
  from the SOW narrative (or vice versa) silently expands scope — include it
  with its owner and flag the mismatch if material.
- An acceptance criterion or deliverable implying work ("DVP agreed with
  Customer prior to testing") creates a row even if no matrix lists it.
- Sourcing strategy (off-the-shelf/carry-over use, open-book procurement,
  minimum-quote rules, tooling ownership) is not a table row; when it carries
  commercial exposure or a dependency it is a Risk Detection item.

## Consistency obligations

Every deliverable's producing task appears as a row owned by AVL, or the
mismatch is flagged in Risk Detection.
