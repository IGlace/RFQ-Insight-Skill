# RFQ Insight plugin

Analyse an RFQ package folder and generate the AVL RFQ Insight PowerPoint
deck. Ask the host to "analyse the RFQ package in <folder>" (or, in Cowork,
"in this folder"); the skill runs its fixed workflow silently and returns one
PowerPoint link. The deck and an internal JSON run report land in
`<folder>/output/`.

The plugin contains one skill, `skills/rfq-insight/`, shared by Claude
(Cowork, Claude Code, Claude Desktop Code) and Codex. It needs Python 3.10+
with `pip` and `venv` where it runs; the first run installs the document
libraries into `~/.rfq-insight/venv`.

Installation, usage and the comparison with the original pipeline are in the
repository root: https://github.com/IGlace/RFQ-Insight-Skill
