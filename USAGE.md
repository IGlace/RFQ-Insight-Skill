# Using RFQ Insight

Ask, in Claude Desktop Cowork, Claude Code or Codex:

> Analyse the RFQ package in RFQs\Acme_V6

In Cowork, connect the RFQ folder as the working folder and ask:

> Analyse the RFQ package in this folder

The plugin runs its fixed workflow and returns one PowerPoint link, then stops.
It does not ask setup questions, offer workflow choices, explain its progress,
or show its analysis, verification or quality-check reasoning. Mandatory
application permission prompts may still appear.

## Fixed behavior

- The folder name becomes the opportunity name unless you already supplied one.
- Saved progress resumes automatically. A completed run reuses its existing deck
  after checking it. An explicitly requested rerun rebuilds the relevant stages.
- Existing decks and reports are preserved. New outputs receive the next unused
  suffix, such as `_2` or `_3`, when a filename is already taken.
- The eleven sections, presentation rules, model assignments and independent
  verification are predefined. The plugin does not offer customization choices.
- Missing required inputs, unreadable supported documents, unavailable required
  capabilities, and failed validation stop the run with one short error.
- Unsupported file types, including Outlook `.msg`, remain excluded. Individual
  illegible figures are recorded internally; they do not trigger questions.

## Files

The PowerPoint is saved in `<your RFQ folder>/output/`. Use the returned link;
filenames are cleaned up and may have a numeric suffix.

The JSON run report, quality-check results and `.work/` checkpoints support
validation and recovery. They remain internal and are not included in the chat
handoff. Keep `.work/` so later requests can resume saved progress.

## Requirements

Install the plugin in a supported application on a machine (or sandbox) with
Python 3.10+, `pip` and `venv`. The first run provisions the document libraries
automatically. See [INSTALL.md](INSTALL.md).

Do not run two analyses concurrently in the same RFQ folder. If a run stops,
correct the stated blocker and repeat the request. RFQ documents and outputs
may contain confidential customer information; keep them out of source control.
