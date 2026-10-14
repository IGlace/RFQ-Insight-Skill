# Finding implicit facts in an RFQ corpus

Most bid-relevant facts in an RFQ package are NOT in the section where you would
expect them. This guide lists where they hide. Whether a derived fact may be
used, and how it is tagged, is decided by the section's rule in the prompt.

## 1. Obligation mining ("shall" statements)

Scan every document for the obligation verbs: **shall, must, will, is required
to, ensure, provide, deliver, is responsible for, at no additional cost,
including but not limited to**.

- "The Supplier shall …" = a supplier obligation → candidate for Scope of Work,
  Deliverables, or Standards, wherever it lands.
- "The Customer will …" = a customer-furnished item (CFI) or customer task →
  a customer-owned Scope of Work row AND a dependency risk if the project
  depends on its timeliness (test vehicles, input data, CAD, test-bed slots).
- "including but not limited to", "all necessary", "state of the art",
  "turnkey" = open-ended scope → record the obligation AND flag the unbounded
  phrasing under Risk Detection.

## 2. Definitions-section mining

A definitions clause like *"Deliverables means all documents, data, models,
hardware and IP created under this SOW"* silently expands the deliverables list
beyond the itemized table. Read the definitions of Deliverables, Milestone,
Acceptance, Defect, Services, Background/Foreground IP and Confidential
Information; what they embed counts as stated content of the matching section.

## 3. Acceptance-criteria back-inference

Every acceptance criterion implies an activity: "acceptance upon successful
completion of the durability run" means someone must plan, fund and execute
that run — find who, or flag the gap. Acceptance mechanics (review periods,
deemed-acceptance windows, re-test cycles) are procedural Timing facts.

## 4. Cross-references and framework inheritance

- An SOW under a **framework / master agreement (Rahmenvertrag, POSA, MSA)**
  inherits commercial, liability, IP, data-protection and warranty terms it
  does not repeat; read the framework for Standards, Opportunity Info and Risk
  content.
- Referenced customer norms ("per customer standard XYZ", "per VW 011xx") are
  binding even when not attached. List the reference under Customer Specific
  Standards and flag the missing attachment under Risk Detection.
- **Order-of-precedence clauses** decide which document wins on conflict. If
  no precedence clause exists, the conflict itself is a document risk.

## 5. Schedule back-calculation

Timing facts hide outside the schedule table:

- Milestones given as offsets ("M3 = M2 + 3 months", "SOP − 18 months") plus a
  single anchor date let you derive calendar dates.
- An MRD (material required date) for a build implies an earlier, unstated
  design-release deadline (procurement lead time).
- Motivation or background paragraphs often contain the only mention of a
  target SOP or program duration.
- Submission windows ("within 10 business days of Commencement") and
  delay-payment trigger windows are timing facts too.

## 6. Quantity and effort inference

Fleet sizes, sample counts, test matrices, "up to 3 design loops" and
change-management rules bound — or fail to bound — the effort; extract every
stated quantity exactly. Placeholders ("xxxx Nm", ">5 engines", "TBD", empty
tables, "Annex to follow", "wird noch definiert") are findings twice: record
them verbatim where they belong and flag them under Risk Detection.

## 7. Where sections typically hide

| Looking for | Also check |
|---|---|
| Timing / milestones | motivation, objectives, acceptance clauses, delay-payment tables, framework agreement notice periods |
| Deliverables | acceptance criteria, definitions, RASIC rows, payment-milestone descriptions |
| Responsibilities | deliverable descriptions ("agreed with Customer" = customer approval role), acceptance flows, framework flow-down clauses |
| Standards | NDA/annexes, data-protection clauses, drawing notes (GD&T system), IT/CAD toolchain requirements, prototype-protection annexes |
| Opportunity info | cover letter/email, framework agreement, submission instructions |
| Product targets | duty cycles, test descriptions (a 500h durability test implies a durability target), benchmark references |

An inference chain that needs an assumption the corpus does not support is not
a fact; at most it is a Risk Detection entry about the gap.
