# RFQ Insight plugin

RFQ Insight transforms RFQ documents into a standardized PowerPoint summary,
providing a clear overview of scope, deliverables, timelines, and risks.
Interactive follow-up questions and revision comparisons help you to quickly
identify key changes and focus on what matters most. The resulting summary is
designed to be the basis for efficient and effective opportunity development.

Ask the host to "analyse the RFQ package in <folder>" (or, in Cowork,
"in this folder"); the skill runs its fixed workflow silently and returns one
PowerPoint link. The deck and an internal JSON run report land in
`<folder>/output/`. Afterwards the same folder answers follow-up questions,
adds them to a new deck on request, and can be compared with another
finished analysis. Documents can also be attached in chat (the skill asks
once for a folder name), and Outlook `.msg` mails in the package are read
together with their attachments.

The plugin contains one skill, `skills/rfq-insight/`, shared by Claude
(Cowork, Claude Code, Claude Desktop Code) and Codex. It needs Python 3.10+
with `pip` and `venv` where it runs; the first run installs the document
libraries into `~/.rfq-insight/venv`.

Install from the marketplace in Claude Code:

```
/plugin install rfq-insight --marketplace IGlace/RFQ-Insight-Skill
```

Installation for every host, usage and the comparison with the original
pipeline are in the repository root:
https://github.com/IGlace/RFQ-Insight-Skill. Release notes are in
[CHANGELOG.md](CHANGELOG.md).
