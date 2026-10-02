# Finding implicit facts in an RFQ corpus

Most bid-relevant facts in an RFQ package are NOT in the section where you would
expect them. This guide lists the proven places and techniques for surfacing
answers that are implied, scattered, or hidden. Content found this way is a
legitimate answer — tag it (inferred) when it is derived rather than stated.

## 1. Obligation mining ("shall" statements)

Scan every document for the obligation verbs: **shall, must, will, is required
to, ensure, provide, deliver, is responsible for, at no additional cost,
including but not limited to**.

- "The Supplier shall …" = a supplier obligation → candidate for Scope of Work,
  Deliverables, or Standards, wherever it lands.
- "The Customer will …" = a customer-furnished item (CFI) or customer task →
  candidate for Scope of Work (customer-owned row) AND a dependency risk if the
  project depends on its timeliness (test vehicles, input data, CAD models,
  benchmark data, licenses, test-bed slots, prototype parts).
- "including but not limited to", "all necessary", "state of the art",
  "turnkey" = open-ended scope → record the obligation AND flag the unbounded
  phrasing under Risk Detection.

## 2. Definitions-section mining

Obligations hide inside defined terms. A definitions clause like *"Deliverables
means all documents, data, models, hardware and IP created under this SOW"*
silently expands the deliverables list far beyond the itemized table. Always
read the definitions of: Deliverables, Milestone, Acceptance, Defect, Services,
Background/Foreground IP, Confidential Information. Whatever they embed
(criteria, deadlines, scope) counts as stated content of the matching section.

## 3. Acceptance-criteria back-inference

Every acceptance criterion implies a deliverable and an activity, even when the
deliverables table omits it. "Acceptance upon successful completion of the
durability run" implies someone must plan, fund, and execute that run — find
who, or flag the gap. Acceptance mechanics (review periods, deemed-acceptance
windows, number of re-test/remediation cycles) are Timing facts: extract them
into the milestone picture as procedural timings.

## 4. Cross-references and framework inheritance

- An SOW under a **framework / master agreement (Rahmenvertrag, POSA, MSA)**
  inherits commercial, liability, IP, data-protection and warranty terms that
  are NOT repeated in the SOW. Both documents together are the contract — read
  the framework agreement for Standards, Commercial Info and Risk content.
- Referenced customer norms ("per customer standard XYZ", "per VW 011xx") are
  binding even when not attached. A referenced-but-missing document is itself a
  finding: list the reference under Customer Specific Standards and flag the
  missing attachment under Risk Detection.
- **Order-of-precedence clauses** decide which document wins on conflict.
  Note the order; when two files disagree, resolve per that clause and mention
  the conflict. If no precedence clause exists, the conflict itself is a
  document risk.

## 5. Schedule back-calculation

Timing facts hide outside the schedule table:

- Milestones given as offsets ("M3 = M2 + 3 months", "SOP − 18 months") plus a
  single anchor date let you DERIVE calendar dates — do it, tag (inferred).
- An MRD (material required date) for a build implies an unstated design-release
  deadline earlier by the procurement lead time. A design release implies
  drawing/BOM completion before it.
- Motivation or background paragraphs often contain the only mention of a
  target SOP or program duration — a milestone stated in passing still counts.
- Submission windows ("within 10 business days of Commencement"), review
  periods, and delay-payment trigger windows are timing facts too.

## 6. Quantity and effort inference

Fleet sizes, engine/sample counts, test matrices, "up to 3 design loops",
change-management rules (what counts as a paid change vs. included rework) all
bound — or fail to bound — the effort. Extract every stated quantity exactly.
Placeholders ("xxxx Nm", ">5 engines", "TBD mule count", empty tables,
"Annex to follow", "to be agreed", "wird noch definiert") are findings twice:
record the placeholder verbatim where it belongs, and flag it under Risk
Detection as unbounded scope/cost.

## 7. Where sections typically hide

| Looking for | Also check |
|---|---|
| Timing / milestones | motivation, objectives, acceptance clauses, delay-payment tables, framework agreement notice periods |
| Deliverables | acceptance criteria, definitions, RASIC rows, payment-milestone descriptions |
| Responsibilities | deliverable descriptions ("agreed with Customer" = customer approval role), acceptance flows, framework flow-down clauses |
| Standards | NDA/annexes, data-protection clauses, drawing notes (GD&T system), IT/CAD toolchain requirements, prototype-protection annexes |
| Commercial info | cover letter/email, framework agreement, submission instructions |
| Product targets | duty cycles, test descriptions (a 500h durability test implies a durability target), benchmark references |

## 8. Discipline

- Derived facts are answers — put them in the section, tagged (inferred), with
  the derivation compact ("M3 ≈ Jan 2027 (M2+3 months from stated M1)").
- Never let inference drift into invention: every inferred fact must be
  traceable to specific corpus statements. If the chain needs an assumption the
  corpus doesn't support, it is not a fact — at most it is a Risk Detection
  entry about the gap.
- Before declaring anything "Info not available", confirm you checked the
  hiding places above across ALL files, not just the obvious section.
