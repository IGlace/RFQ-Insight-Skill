# RFQ Insight plugin

Analyse an RFQ package folder and generate the AVL RFQ Insight PowerPoint
deck. Ask the host to "analyse the RFQ package in <folder>" (or, in Cowork,
"in this folder"); the skill runs its fixed workflow silently and returns one
PowerPoint link. Afterwards it answers follow-up questions about the analysed
RFQ and compares two analysed RFQs. The deck, an internal JSON run report and
the `.work/` checkpoints land in `<folder>/output/`.

The plugin contains one skill, `skills/rfq-insight/`, shared by Claude
(Cowork, Claude Code, Claude Desktop Code) and Codex. Its two executable
entry points are `scripts/bootstrap.py` (document toolbox in
`~/.rfq-insight/venv`) and `scripts/rfq_run.py` (the runner); everything under
`scripts/rfq/` is internal. It needs Python 3.10+ with `pip` and `venv`.

`references/data/accounts.csv` is AVL's Salesforce account list and is
confidential: distribute this plugin privately only.

Install from the marketplace in Claude Code:

    /plugin install rfq-insight --marketplace IGlace/RFQ-Insight-Skill

Installation for every host, usage, validation and the change history are in
the repository root: https://github.com/IGlace/RFQ-Insight-Skill
