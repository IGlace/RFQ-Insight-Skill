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

## AVL denominator classification (Commercial Info, fields 4-7) — OFFICIAL VOCABULARY

Classify into EXACTLY one value per field from the official lists below (from
AVL's Denominators reference). Copy the value verbatim — never invent, merge,
or paraphrase a category. Tag (inferred) when the RFQ doesn't use the term.

**Project Type** (the report's "Product type" field):
Advanced /Pre-Development · Resident Engineering · TaaS (Testing as a Service)
· SOP Project w/o CSM · SOP Project with CSM · Others

**Technology**:
ICE & Mild Hybrid · CO2 Neutral ICE · Hybrid · Battery Electric · FC & EC ·
ADAS · Other Green Tech · Non-Green Tech

**Industry**:
Passenger Car · 2-Wheeler · Racing · Truck & Bus · Offroad · Special Purpose ·
Hydrogen & Industrial Energy · Marine, Rail · Aviation · Others

**Lead Product** (the product with MOST development effort — drives AVL
internal team assignment). Official definitions from the AVL Denominators
reference (use the category names verbatim, including their spelling):
- **Spark Ignited** — spark-ignited engines (gasoline, …), including embedded
  software.
- **Compression Ignited** — compression-ignited engines (diesel, …),
  including embedded software.
- **Transmission incl. Hybrid Transmission** — transmissions incl. hybrid
  transmissions (DHT, AMT, AT, DCT, CVT, …).
- **BEV Transmission and EDU / E-Axles** — transmissions and E-axles /
  Electric Drive Units. Note: assign E-Machine and Power-Electronics
  development share to E-machine & Power Electronics, not here.
- **E-machine & Power Electronics** — E-machine & power electronics (incl.
  on-board chargers) and their integration.
- **Battery** — battery, BMS, including embedded software.
- **Fuell Cell** — PEM and Solid Oxide fuel cells, including embedded
  software.
- **PT System Integration BEV** — development of high-voltage powertrains for
  fuel-cell and battery-electric vehicles covering System Design (requirement
  engineering, system specification), System Integration (functional,
  electrical and mechanical integration of all powertrain and HV components)
  and System Calibration (central powertrain controller), plus HV powertrain
  system V&V on integration test instances (HV integration test bed, PAVIL,
  in vehicle).
- **PT System Integration incl. Hybrid PT** — the same System Design /
  Integration / Calibration / V&V scope for hybrid-electric and conventional
  powertrains (PAVIL and in vehicle).
- **Vehicle Development & Integration** — complete vehicle development,
  powertrain and system in-vehicle integration, demonstrator vehicles,
  platform development support, geometrical configuration, body, safety,
  homologation, NVH, aerodynamics, vehicle benchmarking, etc.
- **Chassis & Vehicle Motion** — chassis system development and
  vehicle-dynamics functions (e.g. ABS, ESC, traction control, limited-slip
  control, torque vectoring, electrified all-wheel drive, rear-wheel
  steering).
- **Thermal Management and HVAC** — vehicle-level THM/HVAC: system design,
  component specification, supplier management. Does NOT include thermal
  management of powertrain components — that scope belongs to the respective
  IC-based or electrification product.
- **E/E Systems (incl Cyber Security & Safety)** — HV and LV electric and
  electronics incl. software, functional safety, cyber security,
  infotainment, telematics, comfort electronics, wiring harness, EMC, data
  and network architecture, function architecture, wiring architecture and
  harness components, EE systems and related EE testing / EE simulation.
- **ADAS/Automated Driving (incl Connectivity)** — complete system, software,
  hardware, sensors (requirements engineering, system design, development,
  integration, validation) and connectivity.
- **SW-Products (e.g. DRIVE, VSM, EPOS)** — e.g. DRIVE (incl. hardware), VSM,
  EPOS.
- **Electrolyzer** — PEM, SOEC, AEL, AEM electrolyzers, e-fuel and hydrogen
  derivates, including embedded software.
- **Emerging Energy Technologies** — carbon capture, low-carbon hydrogen,
  stationary energy storage, smart-grid integration, solar water splitting,
  non-hydrogen energy technologies, including embedded software.
- **Others** — testing facility rentals, manufacturing, certification and
  homologation @ MTC, test equipment @ Tippelmann.

**Confirmed worked example** (client-validated classification): an RFQ for a
REEV front P1P3 system (P1 ISG + P3 traction motor + single-speed gearbox,
dedicated-hybrid architecture) up to C-sample within an SOP-bound program =
Project Type "SOP Project w/o CSM", Lead Product "Transmission incl. Hybrid
Transmission" (a P1/P3 dedicated hybrid drive classifies as hybrid
transmission — NOT as E-Drive/E-Axle), Technology "Hybrid", Industry
"Passenger Car". A clean-sheet NA gasoline V12 engineering service = Lead
Product "Spark Ignited", Technology "ICE & Mild Hybrid" (or CO2 Neutral ICE if
alternative fuels), Industry "Passenger Car" (or "Racing" only when not
road-homologated).

Classification hints: "development up to SOP maturity" = an SOP Project; with
vs w/o CSM = whether customer-specific modification of an existing AVL product
is involved. The engagement covering only early phases of an SOP-bound program
is still classified by the program (SOP Project), with the contracted phases
stated in the Summary.

## Classification disambiguation (common errors from field testing)

**Off-road vs Special Purpose:**
- Off-road = construction equipment, agricultural machinery, mining vehicles,
  forestry machines — mobile machines that operate off paved roads.
- Special Purpose = stationary power units, marine propulsion, generator sets,
  rail traction, military vehicles, airport ground support — anything that is
  NOT a road/off-road mobile machine. A "platform" that drives on-site but is
  not road-classified is Special Purpose.
- Decision test: does the product move on terrain under its own power as its
  primary function? Off-road. Everything else: Special Purpose.

**Engine simulation / testing services:**
- The lead product is what is being DEVELOPED or TESTED, not "simulation" itself.
- An RFQ for V6 engine simulation -> Lead Product is "Spark Ignited" or
  "Compression Ignited" (depending on the engine type), NOT "Others".
- An RFQ for battery testing services -> Lead Product is "Battery", NOT "Others".

**Stationary energy / non-automotive:**
- Al-Air battery for data centers -> Lead Product "Emerging Energy Technologies"
  (not "Battery" — "Battery" is for automotive/vehicle HV batteries).
- Electrolyzer development -> Lead Product "Electrolyzer".
- Hydrogen production plant -> Lead Product "Emerging Energy Technologies".

**Customer contact completeness:**
- Scan cover EMAILS (From/To/CC), letterheads, signature blocks, revision tables.
- A contact is "incomplete" only when you found a name but no email — report
  what you found and flag the missing email, don't report "(not found)".
