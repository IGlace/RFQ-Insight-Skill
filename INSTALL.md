# Install RFQ Insight

RFQ Insight is one plugin, maintained in `plugins/rfq-insight/`, that installs
into Codex (the primary host), Claude Code and Claude Desktop (Code and
Cowork). This repository is the marketplace for it. Nothing here bundles
Python or the document libraries; the first run provisions them. Word page
numbers in the deck notes need a Windows host with Microsoft Word; other hosts
cite chapters instead.

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
- Account access to the models the routes in
  `references/platforms/models.json` ask for. Where a host cannot pick a
  worker's model, the run continues on the host's configured model.

Use local plugins only where your organisation permits them. These instructions
do not override any app policy.

## Codex (CLI, IDE extension, Codex and Work desktop modes)

```
codex plugin marketplace add IGlace/RFQ-Insight-Skill
codex plugin add rfq-insight@rfq-insight
```

In the desktop app the marketplace can also be added from the Plugins catalog.
Start a new thread and ask `Analyse the RFQ package in <path>`, or type
`$rfq-insight` to invoke the skill explicitly.

The session needs fresh workers (`collaboration.spawn_agent` or the host's
equivalent) and image viewing. Each worker request carries its route's model
and reasoning effort from `models.json`: analysis `high`, verification,
figures, slides and follow-up `medium`. When the worker tool hides those
overrides, the worker inherits the host's configured model and the run
continues.

## Claude Code and Claude Desktop Code

```
claude plugin marketplace add IGlace/RFQ-Insight-Skill
claude plugin install rfq-insight@rfq-insight
```

Start a new session and ask `Analyse the RFQ package in <path>`, or invoke the
skill as `/rfq-insight:rfq-insight <path>`. The same marketplace can be added
from Claude Desktop's Code tab through its plugin settings.

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

## Permissions

The plugin ships no approval hook: the client asked for every command to go
through the host's own permission handling. Before its first command the skill
sends one notice and continues; it never waits for a reply.

| Host | What happens | What the user does once |
|---|---|---|
| Codex CLI / IDE / desktop, ChatGPT Work (local) | The notice says: set the session to Auto or Full Access with `/approvals` (`/permissions` in newer versions), otherwise approve each step. The toolbox setup (venv in the home directory, download from PyPI) leaves the sandbox and raises an approval under the default policy. | Pick Auto or Full Access, or in `~/.codex/config.toml` set `[sandbox_workspace_write] network_access = true` and add your `.rfq-insight` folder to `writable_roots`. |
| ChatGPT Work (cloud) | Runs in OpenAI's hosted environment with no local sandbox prompts; package downloads need **Settings → Data controls → Work network access** on. | Enable Work network access. |
| Claude Code / Claude Desktop Code | The notice says: switch the session to auto mode (Shift+Tab) to avoid a prompt at each step, otherwise approve each step when asked. | Switch to auto mode, or approve each step. |
| Claude Desktop Cowork | Folder access is granted when the folder is connected; commands inside the sandbox never prompt. No notice is shown. | Connect the RFQ folder. |

Open the RFQ folder as the working folder in every host: writes to
`<folder>/output/` are then inside the workspace. `RFQ_INSIGHT_HOME` relocates
the toolbox when the home directory is not writable (for example to a
sandbox's writable root).

## Update or remove

Updating the marketplace (`codex plugin marketplace add` again,
`claude plugin marketplace update rfq-insight`, or **Check for updates** in
Cowork) picks up a new plugin version; the plugin version in every manifest is
bumped on every release. Runs made with an earlier version keep working for
`render` and `compare`; to add follow-ups to one, run the analysis again
first (see [USAGE.md](USAGE.md#follow-up-questions)). Keep the RFQ documents, generated decks and reports, and the
`output/.work` checkpoints: they live with the RFQ folder and let a later
request resume. `~/.rfq-insight/venv` can be deleted when no installation
needs it; the next run recreates it.

Remove the plugin through the same host surface that installed it
(`codex plugin remove rfq-insight@rfq-insight`,
`claude plugin uninstall rfq-insight@rfq-insight`, or Customize → Plugins in
Cowork). If an older manually copied `rfq-insight` skill folder exists under
`~/.codex/skills` or `~/.claude/skills`, delete it so the host does not list
the skill twice.

See [USAGE.md](USAGE.md) for running an analysis.
