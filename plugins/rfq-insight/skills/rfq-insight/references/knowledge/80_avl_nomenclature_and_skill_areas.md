# AVL nomenclature & skill areas (official internal definitions)

Use these AVL-internal meanings when reading RFQs and writing the report —
they override generic industry usage where they differ.

## Nomenclature

- **RFQ** — request for quotation; no standard format or type.
- **Opportunity** — a potential customer project; key interaction is RFQ
  receival and offer submission.
- **Phases** — development GENERATIONS from prototype up to volume production;
  a higher generation means higher product maturity. A phase is a development
  generation — not a workstream, not a timing-plan line item, not a meeting.
- **Variant** — product development for different target applications;
  differentiation in the lead product and related derivative variants.
- **Supplier** — from the CUSTOMER's perspective: AVL and/or third-party
  project participants; from AVL's perspective: a THIRD-PARTY project
  participant. In the report, "Supplier" always means the AVL-perspective
  third party (AVL is named AVL).
- **Product** — the product to be developed (combustion engine, electrified
  transmission, battery, powertrain, vehicle, …).
- **Lead product** — the dominant enabler for the project from the customer's
  view (AVL Guidance Document). It must be one of the products listed in
  Opportunity Info's Products (%) with at least 5%, and is not necessarily the
  largest share. Official product names: 90_guidance_denominators.md.
- **Application** — the target environment for the developed product, e.g. the
  target vehicle for a high-voltage battery under development.
- **Location** — where development activity happens: on-site at customer
  facilities, off-site at AVL, on extreme-ambient test trips.
- **Release recommendation** — AVL prepares deliverables to allow a customer
  review and customer FINAL release; final release sits with the product-
  responsible party (production of product), generally NOT AVL. Read RFQ
  release/approval clauses with this split in mind.
- **Unclear data** — contradictions, vague, or ambiguous content. This is the
  official name for what the report's Risk Detection lists as document risks.
- **Skill/Task** — a development activity: design, simulation, procurement,
  testing, software development, calibration, production engineering, …

## Skill areas / tech centers (the "key task" granularity)

These tech-center areas set the Scope-of-Work granularity only. Opportunity
Info's Skills (%) uses the Guidance Document's skill list in
90_guidance_denominators.md (Functional Development, Simulation, Design, …),
never these names.

AVL organizes development work into these skill areas:

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

**Level-of-detail rule for Scope of Work (client-confirmed):** "key tasks, not
every detailed task." The right granularity is roughly the skill-area level:
one row per skill area actually in scope, split only where ownership genuinely
differs inside an area (e.g. design owned by AVL but 2D drawings by the
customer, or software split between AVL and a base-software supplier).
Individual load cases, single meetings, per-component drawings and similar
micro-tasks fold into their parent row. A well-formed key-task table has
roughly 10–18 rows — if you are producing 25+, you are transcribing the RFQ's
task list instead of mapping it to skill areas.

The same granularity governs Deliverables ("key deliverables") and Technical
Product Definitions ("the parameters that define the product"): identify the
key information; the deck presents each of these sections in one to two slides
like the client's reference report.
