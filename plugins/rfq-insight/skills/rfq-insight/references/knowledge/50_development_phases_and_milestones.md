# Automotive development phases and milestone vocabulary

Background knowledge for reading phase and timing content correctly. The RFQ's
OWN definitions always beat these conventions: this file is for understanding
a corpus that USES them, never for adding, renaming or translating the phases
and milestones a corpus names (the prompt's section 6 rule governs phase
names). Sample-phase letters are NOT interchangeable across customers — each
OEM defines its own criteria.

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
A2 Dyno+mule"), defined by the corpus.

## Other phase naming systems you may meet

- **Mule (Versuchsträger/Aggregateträger)**: earliest drivable hardware — new
  powertrain in a modified donor vehicle.
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

- **SOP** — Start of Production of saleable product; the anchor program
  timing is back-calculated from (US: Job #1; GM: SORP).
- **SOS** — ambiguous: "Start of Series" (≈SOP) or "Start of Sales" (market
  launch). Resolve from context; flag if unresolvable.
- **KO / kick-off** — formal start after nomination; starts every clock.
- **Design release** — formal release of CAD/drawings/BOM for procurement or
  tooling; "release for series tooling" triggers tooling cost.
- **Design freeze** — no further design change without change control; usually
  per sample phase.
- **MRD (Material Required Date)** — parts must be at the point of use for a
  build; the real hardware deadline, weeks before the build event. An MRD
  implies an unstated earlier design-release/procurement deadline.
- **First Fire** — first combustion run of a newly built engine (dyno);
  analogues: first spin (e-motor), first shift (transmission).
- **Gateway / quality-gate approval** — management review against exit
  criteria; passing authorizes the next phase and often a payment milestone.
- **DVP / DVP&R** — Design Verification Plan (& Report): the test-program
  document. Who writes, executes and approves it is a key responsibility
  question.
- **DV / PV testing** — DV proves the DESIGN on design-intent (A/B-level)
  parts; PV proves the PRODUCTION part on series-tooling (C/D-level) parts.
- **PPAP** (AIAG, 18 elements, submission levels 1–5) / **PPA-PPF (VDA 2)** —
  production part approval before SOP; evidence = ISIR/EMPB dossier.
- **Homologation / type approval** — regulatory certification on
  series-condition hardware.
- **Run@Rate** — demonstration of production at contractual rate.
- **BIPO** — no public standard definition (plausibly "build in-process
  observation" — witnessed builds). If the corpus uses it, extract and use the
  corpus's own definition; never assert an external one.

## Reading phase/timing content correctly

- A phase named with hardware quantities and an MRD is a **hardware
  milestone** — the supplier's design releases must precede it by procurement
  lead time; check whether that implied release date exists and is feasible.
- A phase's calendar span is stated (start and end dates given for it) or
  derived (from a timing chart or from the milestones that bound it). A
  derived span is allowed in the phase table's Span cell, tagged (inferred).
  When one document gives calendar dates and another gives offsets, derive and
  cross-check; a conflict between derived and stated dates is a document risk.
- **Garbled/OCR'd timing charts** misread characters too ("A2" → "AZ"); the
  prompt's Timing rule gives the dependency-logic check.
