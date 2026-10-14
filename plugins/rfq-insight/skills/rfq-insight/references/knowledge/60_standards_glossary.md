# Standards and compliance regimes in automotive engineering-service RFQs

Recognition glossary: what each standard governs, and what normally triggers
it. Find every standard the corpus names — missing one is the expensive error;
the prompt's section 10 rule decides which 13 are shown and how. The versions
below are background: a designation or version in the report is always the
corpus's own.

## Process & quality

- **Automotive SPICE (ASPICE)** — process capability model for software/system
  development (current PAM v4.0, VDA QMC 2023; adds hardware HWE processes).
  Requirements come as capability levels ("CL2 for VDA scope"). Trigger: any
  software/E-E development in scope.
- **ISO 9001:2015** — baseline QMS certification.
- **IATF 16949:2016** — automotive QMS for PRODUCTION part suppliers. Pure
  engineering-service providers normally need ISO 9001, not IATF — an RFQ
  demanding IATF from a service-only scope is a clarification point.
- **VDA 6.3** (4th ed. 2023) — process audit standard; P2–P4 cover project
  management and product/process development.
- **APQP / PPAP (AIAG)** — advanced product quality planning and production
  part approval; **VDA 2 (PPA/PPF)** is the German equivalent. Trigger: parts
  destined for production.
- **AIAG-VDA FMEA Handbook (2019)** — the harmonized DFMEA/PFMEA method (or
  customer-internal templates).
- **VDA MLA / RGA** ("Reifegradabsicherung für Neuteile", maturity level
  assurance, ML0–ML7) — maturity-level reporting for critical new parts.
  Garbled references ("MLBEV" etc.) usually mean this — flag, don't guess.

## Safety & security

- **ISO 26262:2018** — functional safety of road-vehicle E/E systems; ASIL A–D;
  requires a safety lifecycle and a DIA (Development Interface Agreement)
  splitting safety work products between customer and supplier. Trigger:
  safety-relevant E/E (torque control, actuation, engine management).
- **ISO/SAE 21434:2021** — automotive cybersecurity engineering (TARA,
  cybersecurity case); interface agreement = CIAD. Trigger: connected or
  software-bearing components.
- **UNECE R155 / R156** — type-approval regulations for cybersecurity (CSMS)
  and software-update management (SUMS), flowed down to partners.

## Information security & data

- **TISAX** (VDA ISA catalogue, v6.x) — automotive information-security
  assessment; labels include Info High/Very High, **Prototype Protection**,
  Test Vehicles, Data Protection. Trigger: handling OEM confidential data, CAD,
  prototype hardware. Note the required assessment level/label if stated —
  acquiring a missing label has lead time (project risk).
- **ISO/IEC 27001:2022** — generic ISMS certification; non-German OEMs often
  require this instead of (or besides) TISAX.
- **GDPR / national data-protection rules** — triggered whenever personal data
  is processed; often invoked via customer-internal directives.
- **Prototype protection annexes** — OEM confidentiality, camouflage,
  transport and photo rules, usually with penalty clauses; evidence = the
  TISAX Prototype Protection label.

## Substances & environment

- **REACH (EC 1907/2006), RoHS (2011/65/EU), ELV (2000/53/EC)** — substance
  restrictions on physical parts; compliance evidenced via **IMDS** entries and
  **GADSL** screening.
- **ISO 14001:2015** (environment) and **ISO 45001** (occupational H&S) —
  vendor-qualification checkboxes, often with CO2/ESG reporting clauses.

## Drawings, CAD & data exchange

- **GD&T systems**: **ASME Y14.5-2018** (US) vs the **ISO GPS** suite
  (ISO 8015 / ISO 1101 / ISO 5459; UK umbrella **BS 8888**); mixed-system
  drawings are a known defect source.
- **CAD mandates**: system and version (CATIA V5/3DX, Siemens NX, Creo) — a
  mismatch is a cost/licensing item. Neutral formats STEP AP242 (ISO 10303),
  JT (ISO 14306); data quality VDA 4955/SASIG PDQ; exchange OFTP2/ODETTE.
- **Customer norm systems** (VW 011xx, MBN, BMW GS, etc.) — binding when
  referenced even if not attached; a cited-but-missing norm is a document risk.

## Reading rules

- For each standard, capture the APPLICABILITY the corpus states ("applies to
  all software deliverables") rather than a generic description.
- A norm cited without a version is a possible document-risk note.
- A demanded certification the bidder may not hold (TISAX label, ASPICE level)
  is simultaneously a standards entry AND a project risk.
