# Automotive development phases and milestone vocabulary

Background knowledge for reading phase and timing content correctly. Three
hard rules sit above everything here:

1. **The RFQ's OWN definitions always beat these conventions.** This file is
   for interpreting what the corpus says, never for adding phases or
   milestones it doesn't name — and never for RENAMING what it does name.
   Phase names in the report are the customer's own wording, verbatim. If the
   customer structures the project as named acceptance stages, numbered
   phases, or gateway spans, those ARE the phases — do not translate them
   into the A/B/C/D-sample alphabet or any other scheme below just because
   that scheme is common. The conventions below exist so you understand a
   corpus that USES them, not so you impose them on one that doesn't.
2. **Sample-phase letters are NOT interchangeable across customers** — each
   OEM defines its own criteria.
3. **Alphabetical naming is a last-resort fallback only**: when the corpus
   clearly describes distinct sequential development phases but names none of
   them anywhere, label them "Phase A", "Phase B", … in chronological order,
   tagged (inferred) and explicitly declared as agent-assigned. This is the
   ONLY situation in which the agent names phases itself.

## Sample phases (German/VDA "Muster" convention — consensus meanings)

- **A-sample (A-Muster)**: functional prototype, low property maturity —
  concept demonstration; geometry/material may deviate; soft tooling, machined
  or hand-built parts; rig testing, packaging, early function checks.
- **B-sample**: near-series design, target (or close) material, prototype/
  auxiliary tooling, representative geometry; fit for test-vehicle fleets and
  DV-type testing; design not yet frozen.
- **C-sample**: series tooling and series material, but not necessarily full
  series process conditions (off-line, non-cadence); used for PV-type
  validation, pre-series builds, homologation testing.
- **D-sample**: full series conditions (series tooling, process, location,
  cycle time) — the state required for PPAP / VDA 2 PPA initial-sample
  submission (ISIR/EMPB).

Some programs use only A/B/C, or add sub-levels (B1/B2, A1/A2 — e.g. "A1 Dyno,
A2 Dyno+mule" hardware sets). Treat sub-levels as what the corpus defines them
to be.

## Other phase naming systems you may meet

- **Mule (Versuchsträger/Aggregateträger)**: earliest drivable hardware — new
  powertrain packaged into a modified donor vehicle; precedes true prototypes.
- Generic European: Concept → Prototype → Pre-series (Vorserie) → 0-series
  (Nullserie) → Series.
- VW Group builds: VFF → PVS → 0-Serie → SOP.
- Ford-style: Mule → VP → TT → PP → Job 1.
- GM-style: Alpha/Beta → PPV/MVB → SORP.
- Engineering-services convention (AVL/FEV/IAV programs): **P0/P1/P2** hardware
  generations — P0 ≈ concept/mule-level from modified carry-over parts, P1 =
  first fully new prototype design, P2 = refined near-series prototype. No
  normative definition exists; the program's own definition governs.
- Vehicle-programme gateways (Pre-PT, PT, PF, EV/BR and similar letter codes in
  an OEM's high-level plan) are VEHICLE gates, not engine/component sample
  phases — do not mix them into the component phase list; they matter only as
  timing anchors.

## Milestone / event glossary

- **SOP** — Start of Production: series production of saleable product; the
  anchor most program timing is back-calculated from. (US: Job #1; GM: SORP.)
- **SOS** — ambiguous: "Start of Series" (≈SOP) or "Start of Sales" (market
  launch). Resolve from context; flag if unresolvable.
- **KO / kick-off** — formal project start after nomination; starts every
  deliverable clock.
- **Design release** — formal release of CAD/drawings/BOM at defined maturity
  for procurement or tooling. "Release for series tooling" triggers tooling
  cost — a major commitment point.
- **Design freeze** — no further design change without change control; usually
  per sample phase.
- **MRD (Material Required Date)** — parts must be at the point of use for a
  build; the real hardware deadline, weeks before the build event. An MRD
  implies an unstated earlier design-release/procurement deadline.
- **First Fire** — first combustion run of a newly built engine (dyno);
  analogues: first spin (e-motor), first shift (transmission). A classic
  contractual milestone in engine SOWs.
- **Gateway / quality-gate approval** — management review against exit
  criteria; passing authorizes the next phase and often a payment milestone.
- **DVP / DVP&R** — Design Verification Plan (& Report): the test-program
  document (tests, methods, sample counts, acceptance criteria, timing). Who
  writes, executes and approves it is a key responsibility question.
- **DV / PV testing** — DV proves the DESIGN on design-intent (A/B-level)
  parts; PV proves the PRODUCTION part on series-tooling (C/D-level) parts.
- **PPAP** (AIAG, 18 elements, submission levels 1–5) / **PPA-PPF (VDA 2)** —
  production part approval before SOP; evidence = ISIR/EMPB dossier.
- **PDI** — pre-delivery inspection of finished units before handover.
- **Homologation / type approval** — regulatory certification; requires
  series-condition hardware.
- **Run@Rate / capacity verification** — demonstration of production at
  contractual rate before/during ramp-up.
- **BIPO** — no public standard definition (plausibly "build in-process
  observation" — witnessed builds). If the corpus uses it, extract and use the
  corpus's own definition; never assert an external one.

## Reading phase/timing content correctly

- A phase named with hardware quantities and an MRD is a **hardware
  milestone** — the supplier's design releases must precede it by procurement
  lead time; check whether that implied release date exists and is feasible.
- Distinguish IN-SCOPE phases (this SOW's work) from REFERENCED phases (future
  SOWs, adjacent programs): both are listed in the phase answer with their
  status, but only in-scope phases structure the ownership table.
- When one document gives calendar dates and another gives offsets, derive and
  cross-check; a conflict between derived and stated dates is a document risk.
- **Garbled/OCR'd timing charts**: development plans embedded as images reach
  the corpus as scrambled text — labels detached from their dates, rows
  interleaved, characters misread ("X0" → "XD", "A2" → "AZ"). Never trust a
  label↔date pairing read from such a chart without a dependency-logic check:
  prototype testing cannot complete before that prototype's delivery; a
  design/technology freeze precedes the analyses built on it; procurement →
  build → test → SOP is the invariant order. Re-pair dates to the labels that
  keep the sequence consistent (tag (inferred)), match chart names against
  the narrative spelling, and flag the garbled extraction as a document risk.
