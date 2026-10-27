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
  GPT-6.1 Sol on Codex). Where a host cannot pick a worker's model, the run
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

On Claude Code 2.1.275 or later the two commands collapse into one:
`/plugin install rfq-insight --marketplace IGlace/RFQ-Insight-Skill`.

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

## Permissions: running without prompts

The plugin ships `hooks/hooks.json` with one small script, `hooks/approve.py`,
that approves exactly the calls the skill makes by design: a Python
interpreter running one of the skill's two entry points (`bootstrap.py` or
`rfq_run.py`), `mkdir` under `output/.work`, and writes to `output/.work`.
Chained or piped commands, the internal modules under `scripts/rfq/` and
writes anywhere else fall back to the host's normal prompts.

| Host | What happens | What the user does once |
|---|---|---|
| Claude Desktop Cowork | Folder access is granted when the folder is connected; commands inside the sandbox never prompt. Hooks do not run and are not needed. | Connect the RFQ folder. |
| Claude Code / Claude Desktop Code | The skill's `allowed-tools` frontmatter pre-approves Python, `mkdir`, file reads and writes and Agents for the turn that invokes it, and the plugin's `PreToolUse` hook pre-approves the runner and checkpoint writes on every call, including the workers'. The skill still sends its one-line permission notice before the first command. | Nothing. Optional: add the same rules under `permissions.allow` in `~/.claude/settings.json`, or run the session in auto mode. |
| Codex CLI / IDE / desktop, ChatGPT Work (local) | Commands in the working folder run freely. The toolbox setup (venv in the home directory, download from PyPI) leaves the sandbox, so Codex raises an approval; the plugin's `PermissionRequest` hook approves it, but Codex runs plugin hooks only after they are trusted once. | On first use, accept the hook-trust review for `rfq-insight` (Codex `/hooks`, or the review it offers). Alternatively pick **Approve for me** or **Full access** from the permissions menu under the composer, or in `~/.codex/config.toml` set `[sandbox_workspace_write] network_access = true` and add your `.rfq-insight` folder to `writable_roots`. |
| ChatGPT Work (cloud) | Runs in OpenAI's hosted environment with no local sandbox prompts; package downloads need **Settings → Data controls → Work network access** on. | Enable Work network access. |

Open the RFQ folder as the working folder in every host: writes to
`<folder>/output/` are then inside the workspace and never need approval.
`RFQ_INSIGHT_HOME` relocates the toolbox when the home directory is not
writable (for example to a sandbox's writable root).

## Author and department on the deck

The deck footer shows an author and a department. The runner picks them in
this order, first match wins:

1. `--author "<name>"` and `--department "<name>"` on the `next` command, when
   the request supplies them.
2. The environment variables `RFQ_INSIGHT_AUTHOR` and
   `RFQ_INSIGHT_DEPARTMENT`.
3. The `author` and `department` keys in `~/.rfq-insight/config.json`
   (`%USERPROFILE%\.rfq-insight\config.json` on Windows; `RFQ_INSIGHT_HOME`
   moves that folder):

   ```json
   {"author": "Jane Doe", "department": "Powertrain Sales"}
   ```

4. Otherwise the operating-system user name and "RFQ Insight".

The values are saved with a new run; a resumed run keeps them.

## Uploading documents in chat

In Claude Code, Claude Desktop Code and Codex you can attach the RFQ documents
to the message instead of naming a folder. The skill asks one question, "Which
folder name should I use for this RFQ?", copies the files into that folder and
analyses it. If the folder already exists it asks one more: add the files to it,
or replace its contents.

The folders are created under `RFQ_INSIGHT_ROOT`, or under `~/RFQs` when that is
not set (`%USERPROFILE%\RFQs` on Windows). Set it to put them elsewhere:

```
export RFQ_INSIGHT_ROOT="$HOME/Documents/RFQs"
```

Cowork has no attachments outside the connected folder; put the documents in
that folder as before.

## Update or remove

Updating the marketplace (`claude plugin marketplace update rfq-insight`,
`codex plugin marketplace add` again, or **Check for updates** in Cowork)
picks up a new plugin version; the plugin version in every manifest is bumped
on every release (see `plugins/rfq-insight/CHANGELOG.md`). Keep the RFQ documents, generated decks and reports, and the
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
