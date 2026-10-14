# Selecting the key information (level of detail)

The RFQ Insight report is a management decision document, not a requirements
database. The reader is a sales manager or chief engineer deciding whether and
how to bid. Every extracted point must pass the DECISION TEST:

> Would this fact change the bid decision, the price, the schedule, the risk
> picture, or the staffing? If not, it does not belong in the report.

The prompt's section rules set the caps (Description, Technical Targets, Scope
of Work, Standards, Risks); this guide decides what survives a cap. Sections
without a cap (Application, Collaboration, Phases, Deliverables, Timing) are
complete: the test decides how coarsely an item is named, never whether a
stated item is listed.

## Technical targets: what "defines the product"

Keep the parameters a chief engineer would quote when describing the product
in two minutes: architecture/type, headline performance numbers, key design
choices, required compliance (ASPICE/ISO 26262 yes/no). Skip tolerance-level
detail.

## Prioritization heuristics when there is too much

1. Money first: anything touching price, payment, penalties, unbounded effort.
2. Dates second: anything constraining the critical path.
3. Ownership third: anything assigning or shifting responsibility.
4. Compliance fourth: anything certifiable or auditable.
5. Everything else only if it uniquely characterizes the product or project.

## Signals that a detail is NOT key

- It repeats boilerplate any RFQ of this customer contains (unless it carries a
  number or deadline).
- It is an internal process description of the customer with no supplier
  obligation.
- It duplicates another point at finer granularity (keep the parent).
- It would only matter after contract award (execution detail, not bid
  decision) — e.g. report formatting rules, meeting cadences, template names.

## Writing style for extracted points

Dense, self-contained, decision-ready: lead with the fact, keep identifiers
verbatim, quantify wherever the corpus quantifies. One idea per bullet or row.
A reader must never need the source document open to understand a point.
