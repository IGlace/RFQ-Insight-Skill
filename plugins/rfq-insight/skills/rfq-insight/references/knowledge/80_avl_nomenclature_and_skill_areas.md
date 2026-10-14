# AVL nomenclature & skill areas (official internal definitions)

These AVL-internal meanings override generic industry usage.

## Nomenclature

- **RFQ** — request for quotation; no standard format.
- **Opportunity** — a potential customer project (RFQ received, offer
  submitted).
- **Phases** — development GENERATIONS from prototype up to volume production;
  not a workstream, a timing-plan line item or a meeting.
- **Variant** — product development for different target applications;
  differentiation in the lead product and related derivative variants.
- **Supplier** — for the customer, AVL and/or third parties; in the report,
  always a THIRD-PARTY project participant (AVL is named AVL).
- **Product** — the product to be developed (combustion engine, electrified
  transmission, battery, powertrain, vehicle, …).
- **Application** — the target environment for the developed product, e.g. the
  target vehicle for a high-voltage battery under development.
- **Location** — where development happens: on-site at the customer,
  off-site at AVL, on extreme-ambient test trips.
- **Release recommendation** — AVL prepares deliverables to allow a customer
  review and customer FINAL release; final release sits with the product-
  responsible party (production of product), generally NOT AVL. Read RFQ
  release/approval clauses with this split in mind.
- **Unclear data** — contradictions, vague, or ambiguous content. This is the
  official name for what the report's Risk Detection lists as document risks.
- **Skill/Task** — a development activity: design, simulation, procurement,
  testing, software development, calibration, production engineering, …

## Skill areas / tech centers (the "key task" granularity)

These tech-center areas set the Scope-of-Work row granularity only. Opportunity
Info's Skills (%) uses the Guidance Document's skill list in
90_guidance_denominators.md (Functional Development, Simulation, Design, …),
never these names.

- Program & Project Management (DP)
- Project Quality (DO)
- Functional Development (DS)
- Digital Product Dev. Design (DD-D)
- Digital Product Dev. Simulation (DD-S)
- Validation & Industrialization (DM-V / DM-I)
- E/E, SW & Controls (DJ)
- Calibration (DC)
- Test & Data Factory (DF)
- Comm. Driveline & Vehicle (DK)

One Scope-of-Work row per skill area actually in scope, split only where
ownership genuinely differs inside an area (e.g. design owned by AVL but 2D
drawings by the customer, or software split between AVL and a base-software
supplier). If you are producing 25+ rows, you are transcribing the RFQ's task
list instead of mapping it to skill areas.
