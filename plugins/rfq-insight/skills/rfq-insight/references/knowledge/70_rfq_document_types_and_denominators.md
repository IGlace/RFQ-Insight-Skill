# RFQ package document types & AVL denominator classification

## Document types in an RFQ corpus (what to expect from each)

- **RFQ / RFI / RFP cover letter or email** — commercial frame: quotation due
  date, contacts, submission rules. Often the ONLY place the reply deadline is
  stated.
- **SOR (Statement of Requirements) / Lastenheft** — the customer's WHAT:
  requirements, targets, variants. Primary source for Technical Product
  Definitions, Application Approach, Standards. In conflicts, the primary
  SOR/Lastenheft usually outranks secondary material (subject to any
  order-of-precedence clause).
- **SOW (Statement of Work) / Leistungsbeschreibung** — the contracted HOW and
  WHO: services, deliverables, milestones, acceptance, RASIC. Primary source
  for Scope of Work, Deliverables, Timing, Development Phases.
- **Pflichtenheft** — the supplier's HOW in response to a Lastenheft; if
  present in the corpus it reflects prior supplier commitments.
- **Framework / master agreement (Rahmenvertrag, MSA, POSA)** — governing
  commercial/legal terms inherited by every SOW under it: liability, IP,
  payment, data protection, rate cards, warranty. Primary source for
  commercial-risk and standards content the SOW doesn't repeat.
- **HLP (high-level plan) / timing charts** — program milestones, often
  vehicle-level gateways; cross-check against SOW milestone tables.
- **RASIC / responsibility annex** — the responsibility matrix (see the
  mapping guide).
- **BOM / variant matrices / appendices** — scope-critical tables: variants,
  quantities, part lists. Parse them; never skip a table because it is hard.
- **Norm/standard annexes, prototype-protection annexes, NDAs** — compliance
  obligations (standards section) and data-handling rules.
- **Rate cards / commercial templates** — pricing structure; blank ones are a
  finding (commercial section "to be filled" = quote-blocking gap).

Extraction reality: corpus text extracted from .docx/.pdf loses table
structure — expect flattened multi-column rows (label lines followed by value
lines, IDs like D01…D14 separated from their descriptions). Reconstruct tables
from context before concluding something is missing, and note extraction
limitations in the affected answer rather than ignoring a garbled file.

## AVL denominator classification (Opportunity Info) — OFFICIAL VOCABULARY

The official values, with their descriptions, are in
`90_guidance_denominators.md`, generated from AVL's Guidance Document. Copy
each value from there verbatim: never invent, merge, shorten or paraphrase a
category. Tag (inferred) in the answer text when the RFQ doesn't use the term,
never inside the `opportunity` object.

- **Project type**: one value from "Project type".
- **Technology**: one value from "Technology".
- **Industry**: one value from "Industry".
- **Products (%)**: the share of AVL's development effort per product, from
  "Products (%)". Whole percentages adding up to exactly 100; list only
  products with more than 0%.
- **Skills (%)**: the share of AVL's effort per skill, from "Skills (%)".
  Same rules. These are the Guidance skill names, not the tech-center skill
  areas in 80_avl_nomenclature_and_skill_areas.md.
- **Lead product**: one of the listed products with at least 5%. It is the
  dominant enabler for the project from the customer's view, not
  necessarily the largest share.

**Confirmed worked example** (client-validated classification): an RFQ for a
REEV front P1P3 system (P1 ISG + P3 traction motor + single-speed gearbox,
dedicated-hybrid architecture) up to C-sample within an SOP-bound program =
Project type "SOP Project w/o CSM (up to SOP or partial SOP development)",
Lead Product "Transmission incl. Hybrid Transmission" (a P1/P3 dedicated hybrid drive classifies as hybrid
transmission — NOT as E-Drive/E-Axle), Technology "Hybrid", Industry
"Passenger Car". The REEV example's Products (%) list must then contain
"Transmission incl. Hybrid Transmission" with at least 5%. A clean-sheet NA gasoline V12 engineering service = Lead
Product "Spark Ignited", Technology "ICE & Mild Hybrid" (or "CO2-neutral ICE" if
alternative fuels), Industry "Passenger Car" (or "Racing" only when not
road-homologated).

Classification hints: "development up to SOP maturity" = an SOP Project; with
vs w/o CSM = whether AVL carries full component responsibility including
Component Supplier Management (CSM); see the Project type descriptions in
90_guidance_denominators.md. The engagement covering only early phases of an SOP-bound program
is still classified by the program (SOP Project), with the contracted phases
stated in the Description.

## Classification disambiguation (common errors from field testing)

**Off-Road vs Special Purpose (Industry):**
- Off-Road = agricultural, construction, mining and material-handling
  machines (forklifts etc.) and other mobile working machines (sweepers etc.).
- Special Purpose = defense and dual-use applications only.
- Marine propulsion and rail traction = "Marine, Rail"; stationary power
  generation, electrolysis, hydrogen/e-fuel production and stationary
  batteries = "Hydrogen & Industrial Energy" (see the Industry descriptions
  in 90_guidance_denominators.md).
- Decision test for a mobile machine: does it move on terrain under its own
  power as its primary function? Then it is Off-Road.

**Engine simulation / testing services:**
- The lead product is what is being DEVELOPED or TESTED, not "simulation" itself.
- An RFQ for V6 engine simulation -> Lead Product is "Spark Ignited" or
  "Compression Ignited" (depending on the engine type), NOT
  "Others (Testing facility Rentals, Manufacturing, etc)".
- An RFQ for battery testing services -> Lead Product is "Battery", NOT
  "Others (Testing facility Rentals, Manufacturing, etc)".

**Stationary energy / non-automotive:**
- Electrolyzer development, or an RFQ about producing e-fuel or hydrogen
  derivates (the Guidance's Electrolyzer description: "PEM, SOEC, AEL, AEM
  Electrolyzers, e-fuel and hydrogen derivates") -> Lead Product
  "Electrolyzer".
- Low Carbon Hydrogen, Carbon Capture, Stationary Energy Storage, Smart Grid
  Integration or Solar Water Splitting (the Guidance's Emerging Energy
  Technologies description) -> Lead Product "Emerging Energy Technologies".
- Al-Air battery for data centers -> Lead Product "Emerging Energy
  Technologies" (it is Stationary Energy Storage, not an electrolyzer).

**Customer contact completeness:**
- Scan cover EMAILS (From/To/CC), letterheads, signature blocks, revision tables.
- A contact is "incomplete" only when you found a name but no email — report
  what you found and flag the missing email, don't report "(not found)".
