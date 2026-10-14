# Selecting the key information (level of detail)

The RFQ Insight report is a management decision document, not a requirements
database. The reader is a sales manager or chief engineer deciding whether and
how to bid. Every extracted point must pass the DECISION TEST:

> Would this fact change the bid decision, the price, the schedule, the risk
> picture, or the staffing? If not, it does not belong in the report.

## What "key" means per section

- **Opportunity Info** — the client's fields only: customer, contact, quotation
  due date, Opportunity name, Project type, Lead product, Technology,
  Industry, plus the Products (%) and Skills (%) splits. Every classification
  value comes verbatim from 90_guidance_denominators.md. Account Name (Site)
  and KAM (PTE) are looked up by the application, never written by you.
- **Description** — the five-paragraph story a manager reads in 60 seconds: what
  product, why, what's expected from us, how long, when to reply. No technical
  parameters here; they have their own section.
- **Technical Product Definitions and Targets** — the parameters that DEFINE
  the product: architecture/type, headline performance numbers, key design
  choices, required compliance (ASPICE/ISO 26262 yes/no). When the corpus has
  hundreds of requirements, keep the ones a chief engineer would quote when
  describing the product in two minutes; skip tolerance-level detail. Never
  evaluate here — pure summary.
- **Application Approach** — the variant/program matrix (which vehicles, which
  configuration, which legislation, what volume). One row per application;
  "Info not available" verbatim for missing volumes.
- **Collaboration Approach** — the parties (customer, AVL, every third party
  the corpus names), each with its role and interfaces. Never an invented
  party; "No further parties are named in the RFQ." when there are none.
- **Development Phases** — only phases the corpus names, with their definition
  status and scope status. Not a lecture on sample phases.
- **Scope of Work** — KEY tasks, not every task: aim for the 10–25 rows that
  carry cost or risk. Merge micro-tasks into their parent work package
  (individual CAE load cases → "Simulation"). A task earns its own row when it
  has a distinct owner, a distinct phase pattern, or notable cost/risk.
- **AVL Deliverables** — key deliverables, grouped by phase/task; itemize what
  is contractually acceptance-relevant (identified by ID like D01… when the
  corpus numbers them). No acceptance criteria in this section.
- **Timing** — every real milestone (there is rarely reason to drop one), plus
  procedural timings (review windows, delay triggers). Consolidated from the
  whole corpus, conflicts noted.
- **Customer Specific Standards** — every named norm/standard/compliance regime
  with what it applies to. Standards are expensive to miss, so search for all of
  them — but the section is capped at one slide (13 rows), so select by
  compliance weight and disclose the counts, per the prompt's section 10 rule.
- **Risk Detection** — the risks that would make a manager act: clarify before
  quoting, price a contingency, decline. Not a generic risk lecture; every risk
  cites the clause that triggers it.

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
