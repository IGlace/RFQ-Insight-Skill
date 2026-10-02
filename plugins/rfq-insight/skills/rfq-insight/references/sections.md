# The 11 canonical sections

Every RFQ analysis answers these eleven, in this order, with these exact
titles. The ids are fixed: stage 1 is matched to a section on `id` alone and
stage 2 receives the titles verbatim.

Do not invent, merge, split, reorder or retitle a section. A section with
nothing to say is still answered - with the absence stated.

| id | title_en | title_de |
|---|---|---|
| 1 | Commercial Info | Kommerzielle Informationen |
| 2 | Source Material | Quellenmaterial |
| 3 | Summary | Zusammenfassung |
| 4 | Technical Product Definitions and Targets | Technische Produktdefinitionen und Ziele |
| 5 | Application Approach | Anwendungsansatz |
| 6 | Development Phases | Entwicklungsphasen |
| 7 | Scope of Work and Responsibilities | Leistungsumfang und Verantwortlichkeiten |
| 8 | AVL Deliverables | AVL-Liefergegenstände |
| 9 | Timing | Terminplanung |
| 10 | Customer Specific Standards | Kundenspezifische Normen |
| 11 | Risk Detection | Risikoerkennung |

This table is duplicated from `scripts/rfq/schema.py::TITLES` on purpose -
`finalize.py` needs the titles in Python, the analysis stage needs them in
markdown. `tests/test_invariants.py` fails if the two ever disagree.
