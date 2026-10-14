# The 12 canonical sections

Every RFQ Insight deck has these twelve sections, in this order, with these
exact titles. The ids are fixed: the analysis is matched to a section on `id`
alone. The analysis answers sections 1-11; section 12 (Source Material) is
built by the application from the source catalogue.

Do not invent, merge, split, reorder or retitle a section. A section with
nothing to say is still answered - with the absence stated.

| id | title_en | title_de |
|---|---|---|
| 1 | Opportunity Info | Opportunity-Informationen |
| 2 | Description | Beschreibung |
| 3 | Technical Product Definitions and Targets | Technische Produktdefinitionen und Ziele |
| 4 | Application Approach | Anwendungsansatz |
| 5 | Collaboration Approach | Kooperationsansatz |
| 6 | Development Phases | Entwicklungsphasen |
| 7 | Scope of Work and Responsibilities | Leistungsumfang und Verantwortlichkeiten |
| 8 | AVL Deliverables | AVL-Liefergegenstände |
| 9 | Timing | Terminplanung |
| 10 | Customer Specific Standards | Kundenspezifische Normen |
| 11 | Risk Detection | Risikoerkennung |
| 12 | Source Material | Quellenmaterial |

This table is duplicated from `scripts/rfq/schema.py::TITLES` on purpose -
`rfq/delivery.py` needs the titles in Python, the analysis stage needs them in
markdown. The test suite fails if the two ever disagree.
