# Install RFQ Insight

RFQ Insight is one plugin, maintained in `plugins/rfq-insight/`, that installs
into Claude Desktop (Cowork and Code), Claude Code and Codex. This repository is
the marketplace for it. Nothing here bundles Python or the document libraries;
the first run provisions them.

## What every host needs

- Python 3.10 or newer with `pip` and `venv` on the machine (or inside the
  sandbox) where the plugin runs. On Windows, `py -3` or `python` must start
  that version.
- Permission for the app to read the RFQ folder, write its `output` subfolder,
  and create `~/.rfq-insight/venv` (`%USERPROFILE%\.rfq-insight\venv` on
  Windows). The venv is shared by every host on the machine.
- Package-index access (pypi.org) on first use, when the skill downloads
  `python-pptx`, `Pillow`, `pydantic`, `python-docx`, `openpyxl` and
  `pdfplumber` into that venv. If the venv cannot be created but the host's own
  Python already has those libraries, the skill uses it instead.
- Account access to the models the routing asks for (Claude Opus and Sonnet;
  GPT-6 Sol on Codex). Where a host cannot pick a worker's model, the run
  continues on the host's current model.

Use local plugins only where your organisation permits them. These instructions
do not override any app policy.

## Claude Desktop — Cowork

1. Open Claude Desktop, switch to **Cowork**, and open **Customize → Plugins**.
2. Choose **Add → Add marketplace** and enter this repository:
   `https://github.com/IGlace/RFQ-Insight-Skill` (or `IGlace/RFQ-Insight-Skill`).
3. Install **RFQ Insight** from the marketplace list.
4. Connect the folder that holds the RFQ package as the Cowork working folder,
   start a new session and ask: `Analyse the RFQ package in this folder`.

Alternative for a machine without GitHub access: run
`python tools/package_plugin.py` in a checkout of this repository and upload the
resulting `dist/rfq-insight-plugin.zip` through **Customize → Plugins → Add →
Upload**.

The first run inside a fresh Cowork sandbox installs the document libraries;
later runs in the same sandbox start immediately.

## Claude Code and Claude Desktop Code

```
claude plugin marketplace add IGlace/RFQ-Insight-Skill
claude plugin install rfq-insight@rfq-insight
```

Start a new session and ask `Analyse the RFQ package in <path>`, or invoke the
skill as `/rfq-insight:rfq-insight <path>`. The same marketplace can be added
from Claude Desktop's Code tab through its plugin settings.

## Codex (CLI, IDE extension, Codex and Work desktop modes)

```
codex plugin marketplace add IGlace/RFQ-Insight-Skill
codex plugin add rfq-insight@rfq-insight
```

In the desktop app the marketplace can also be added from the Plugins catalog.
Start a new thread and ask `Analyse the RFQ package in <path>`, or type
`$rfq-insight` to invoke the skill explicitly.

## Update or remove

Updating the marketplace (`claude plugin marketplace update rfq-insight`,
`codex plugin marketplace add` again, or **Check for updates** in Cowork)
picks up a new plugin version; the plugin version in both manifests is bumped
on every release. Keep the RFQ documents, generated decks and reports, and the
`output/.work` checkpoints: they live with the RFQ folder and let a later
request resume. `~/.rfq-insight/venv` can be deleted when no installation
needs it; the next run recreates it.

Remove the plugin through the same host surface that installed it
(`claude plugin uninstall rfq-insight@rfq-insight`,
`codex plugin remove rfq-insight@rfq-insight`, or Customize → Plugins in
Cowork). If an older manually copied `rfq-insight` skill folder exists under
`~/.claude/skills` or `~/.codex/skills`, delete it so the host does not list
the skill twice.

See [USAGE.md](USAGE.md) for running an analysis.
