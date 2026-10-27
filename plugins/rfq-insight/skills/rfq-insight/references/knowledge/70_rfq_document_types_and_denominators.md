# RFQ package document types & AVL denominator classification

## Document types in an RFQ corpus (what to expect from each)

- **RFQ / RFI / RFP cover letter or email** — commercial frame: quotation due
  date, contacts, submission rules. Often the ONLY place the reply deadline is
  stated.
- **SOR (Statement of Requirements) / Lastenheft** — the customer's WHAT:
  requirements, targets, variants. Primary source for Technical Product
  Definitions, Application Approach, Standards.
- **SOW (Statement of Work) / Leistungsbeschreibung** — the contracted HOW and
  WHO: services, deliverables, milestones, acceptance, RASIC. Primary source
  for Scope of Work, Deliverables, Timing, Development Phases.
- **Pflichtenheft** — the supplier's HOW in response to a Lastenheft (prior
  supplier commitments).
- **Framework / master agreement (Rahmenvertrag, MSA, POSA)** — governing
  commercial/legal terms inherited by every SOW under it: liability, IP,
  payment, data protection, rate cards, warranty. Primary source for
  commercial-risk and standards content the SOW doesn't repeat.
- **HLP (high-level plan) / timing charts** — program milestones, often
  vehicle-level gateways; cross-check against SOW milestone tables.
- **BOM / variant matrices / appendices** — scope-critical tables: variants,
  quantities, part lists.
- **Norm/standard annexes, prototype-protection annexes, NDAs** — compliance
  obligations (standards section) and data-handling rules.
- **Rate cards / commercial templates** — pricing structure; a blank one is a
  quote-blocking gap.

## AVL denominator classification (Opportunity Info)

The official values and their descriptions are in
`90_guidance_denominators.md`, generated from AVL's Guidance Document; the
prompt's section 1 rule says how each field is filled. Products (%) and
Skills (%) use the Guidance names, not the tech-center skill areas in
80_avl_nomenclature_and_skill_areas.md.

**Confirmed worked example** (client-validated classification): an RFQ for a
REEV front P1P3 system (P1 ISG + P3 traction motor + single-speed gearbox,
dedicated-hybrid architecture) up to C-sample within an SOP-bound program =
Project type "SOP Project w/o CSM (up to SOP or partial SOP development)",
Lead Product "Transmission incl. Hybrid Transmission" (a P1/P3 dedicated hybrid
drive classifies as hybrid transmission — NOT as E-Drive/E-Axle), Technology
"Hybrid", Industry "Passenger Car". The REEV example's Products (%) list must
then contain "Transmission incl. Hybrid Transmission" with at least 5%. A
clean-sheet NA gasoline V12 engineering service = Lead Product "Spark Ignited",
Technology "ICE & Mild Hybrid" (or "CO2-neutral ICE" if alternative fuels),
Industry "Passenger Car" (or "Racing" only when not road-homologated).

Classification hints: "development up to SOP maturity" = an SOP Project; with
vs w/o CSM = whether AVL carries full component responsibility including
Component Supplier Management (CSM); see the Project type descriptions in
90_guidance_denominators.md. An engagement covering only early phases of an
SOP-bound program is still classified by the program (SOP Project), with the
contracted phases stated in the Description.

## Classification disambiguation (common errors from field testing)

**Off-Road vs Special Purpose (Industry):**
- Special Purpose = defense and dual-use applications only.
- Decision test for a mobile machine: does it move on terrain under its own
  power as its primary function? Then it is Off-Road (forklifts and sweepers
  included).

**Engine simulation / testing services:**
- The lead product is what is being DEVELOPED or TESTED, not "simulation" itself.
- An RFQ for V6 engine simulation -> Lead Product is "Spark Ignited" or
  "Compression Ignited" (depending on the engine type), NOT
  "Others (Testing facility Rentals, Manufacturing, etc)".
- An RFQ for battery testing services -> Lead Product is "Battery", NOT
  "Others (Testing facility Rentals, Manufacturing, etc)".

**Stationary energy / non-automotive:**
- Electrolyzer development, or producing e-fuel or hydrogen derivates ->
  Lead Product "Electrolyzer".
- Low Carbon Hydrogen, Carbon Capture, Stationary Energy Storage, Smart Grid
  Integration, Solar Water Splitting -> "Emerging Energy Technologies", not
  "Battery".
- Al-Air battery for data centers -> "Emerging Energy Technologies" (it is
  Stationary Energy Storage, not an electrolyzer).
