# Flagging project risks and consistency (document) risks

Risk Detection is the section where engineering judgement lives. A good risk
entry names the trigger (the clause, number, or contradiction), states why it
matters for the bid, and is phrased so a manager can act on it (clarify,
price, decline). A risk without a corpus trigger is speculation — don't write it.

## A. Project risks — checklist

**Schedule feasibility**
- Compare the demanded timeline against what is typical for the product class:
  clean-sheet powertrain concept-to-gateway in under ~4–6 months, design
  release cycles of ~3 months, or build+test programs squeezed inside prototype
  procurement lead times are aggressive; say so and say why (lead times for
  castings/forgings/bespoke parts commonly dominate).
- Relative-offset milestones with no anchor date, or an anchor that conflicts
  between documents, make the whole schedule soft.
- Approval loops (customer review windows, gateway approvals) that sit on the
  critical path but have no committed customer response time.

**Commercial exposure**
- Delay payments / liquidated damages / service credits: note percentage,
  trigger window, cap, and whether they are stated as non-exclusive remedies
  (cumulative exposure). Typical automotive penalty clauses run 0.x–0.5% per
  week capped at 5–10% — anything harsher or uncapped is a headline risk.
- Blank or placeholder commercial sections (rates "[to be inserted]", empty
  payment schedules): the risk/reward cannot be assessed — quote-blocking.
- Open-book / cost-plus procurement obligations, minimum-quotes-per-commodity
  rules, tooling ownership transfer terms.
- Werkvertrag-like acceptance regimes (success owed, formal acceptance,
  remediation cycles) vs. pure service effort — acceptance mechanics turn
  schedule risk into payment risk.

**Scope boundedness**
- Unbounded quantities: ">5 engines", "TBD mule count", "xxxx Nm", "all
  necessary", "including but not limited to", uncapped iteration loops.
- Change management: if the SOW doesn't define what counts as a paid change,
  rework is free until proven otherwise.

**Dependencies**
- Customer-furnished items (inputs, CAD, benchmark data, test vehicles, parts,
  test-bed slots) with no committed delivery dates — late CFIs cascade into
  supplier delay-payment exposure.
- Third parties the supplier must integrate but does not control, especially
  when the supplier remains accountable for their output.
- Referenced-but-missing documents (norms, annexes "to follow").

**Compliance / IP**
- Certifications demanded that the bidder must acquire (TISAX label level,
  ASPICE capability level) with lead times longer than the project start.
- IP assignment of foreground IP, native CAD/CAE model delivery obligations,
  background-IP contamination risk.
- Liability carve-outs (unlimited for IP/confidentiality), insurance minimums.

## B. Document / consistency risks — checklist

- **Contradictions between documents**: dates, scope, ownership stated
  differently in SOW vs framework agreement vs annex. Always name both
  locations. Check the order-of-precedence clause; if none exists, that
  absence is itself a risk.
- **Contradictions within a document**: a commencement date in one clause vs a
  different one in the milestone table; a deliverable "optional" in the service
  list but a mandatory acceptance-gate item elsewhere; a task assigned to two
  parties in two sections (fed from the Scope-of-Work analysis).
- **Vague or ambiguous requirements**: undefined terms used normatively,
  "state of the art", "appropriate", unquantified targets.
- **Placeholders and gaps**: TBD/TBC, empty tables, "[insert]", missing
  annexes, unnumbered standard references (a norm cited without a version).
- **Mislabeled or misnumbered content**: service/deliverable IDs that don't
  match between tables, duplicated IDs, rows referencing non-existent items —
  correctable errors, but each needs a clarification before quoting.
- **Legend/semantics risks**: a responsibility matrix whose legend deviates
  from the standard letter meanings, or mixed RACI/RASIC semantics between
  documents.

## C. Writing the risk entries

- Split into the two groups the report expects: Project Risks and Document
  Risks. Within each, order by bid impact (quote-blocking first).
- One risk, one entry: trigger → consequence → implied action. Example shape:
  "Delay payments (3% timeliness, 10% competency) are stated as non-exclusive
  remedies (§11) — cumulative exposure is uncapped; cap must be negotiated
  before quoting."
- Schedule-feasibility judgement belongs HERE (not in Timing): one entry
  assessing whether the demanded timeline is typical/feasible for this product
  class, grounded in the milestones extracted in Timing.
- Do not pad: three sharp risks beat ten generic ones. But a genuinely risky
  RFQ can legitimately produce a long list — never drop a quote-blocking item
  for brevity.
