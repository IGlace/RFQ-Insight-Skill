# Using RFQ Insight

Ask, in Claude Desktop Cowork, Claude Code or Codex:

> Analyse the RFQ package in RFQs\Acme_V6

In Cowork, connect the RFQ folder as the working folder and ask:

> Analyse the RFQ package in this folder

The plugin runs its fixed workflow and returns one PowerPoint link, then stops.
It asks no questions about the analysis (the only questions are the two of a
chat upload, see "Attached documents"), offers no workflow choices, does not
explain its progress, and does not show its analysis, verification or
quality-check reasoning. Mandatory
application permission prompts may still appear; the skill sends one short
notice about them before its first command and does not wait for a reply.

## Fixed behavior

- The folder name becomes the display name on the cover and end slide until
  the analysis finds the opportunity name, unless you supplied one; the deck
  file is named from the opportunity name the analysis finds in the
  documents.
- Saved progress resumes automatically. A completed run reuses its existing deck
  after checking it. An explicitly requested rerun rebuilds the relevant stages.
- Existing decks and reports are preserved. New outputs receive the next unused
  suffix, such as `_2` or `_3`, when a filename is already taken.
- The twelve sections, their slide shapes, the confidence rules, the model
  assignments and the independent verification are predefined. The plugin does
  not offer customization choices.
- Every section's slide shows a confidence chip (High, Medium or Low). The
  speaker notes of each slide explain the rating: what was extracted, what was
  inferred or had to be settled, what the verifier checked, and every source
  by file, page or section. `(inferred)` marks inferred items on the slide.
- Missing required inputs, unreadable supported documents, unavailable required
  capabilities, and failed validation stop the run with one short error.
- Outlook `.msg` mails are read: the sender, recipients, date, subject and
  body, and every attachment in a supported format as a document of its own,
  listed beneath the mail in Source Material. A mail attached to a mail is
  read one level deep; a mail nested deeper, or an attached mail that cannot
  be read, is listed as not read and never stops the run. Other unsupported
  file types remain excluded. Individual
  illegible figures are recorded internally; they do not trigger questions.
- The deck is written in English whatever the language of the documents. A
  name the customer gives in another language keeps its original in brackets
  on first use, e.g. `Concept Freeze (Konzept-Freeze)`.

## Attached documents

Attach the RFQ documents to your message and ask to analyse them. You are
asked once for a folder name; the files are copied into a folder of that name
(under `~/RFQs`, or under `RFQ_INSIGHT_ROOT` when that is set) and analysed
from there. If the folder already exists you are asked once more whether to add
the files to it or replace its contents. This is the only time the plugin asks
you anything. See [INSTALL.md](INSTALL.md).

## Author and department

The deck footer shows an author and a department. Say them in the request
("author Jane Doe, department Powertrain Sales") or set them once as described
in [INSTALL.md](INSTALL.md); otherwise the footer shows your user name and
"RFQ Insight".

## Follow-up questions

Once a folder has been analysed, ask about it in the same or a later session:

> In RFQs\Acme_V6, which standards apply to the battery housing?

The answer comes back in chat with a `Sources:` line naming each file and
locator. If the RFQ files changed since the run, the plugin says so in one
sentence, re-reads them, and answers against the current documents; the
existing PowerPoint still reflects the older files.

To put the answers on slides:

> Add the follow-up answers to the presentation

A new deck is written next to the earlier one, with an "Additional
Information" section before Source Material. The earlier deck is untouched.
When the RFQ documents changed since the latest presentation, the analysis
has to run again first. Questions and answers are kept in
`<folder>/output/.work/followups.json`; deleting `output/` deletes them.

## Comparing two analyses

When two folders each hold a finished run (two RFQs, or two revisions of the
same RFQ), ask:

> Compare the RFQ analyses in RFQs\Acme_V6 and RFQs\Acme_V7

The plugin returns one link to a comparison deck written into the first
folder's `output/`. It never re-runs either analysis; if one folder has no
finished run, it says which one.

## Files

The PowerPoint is saved in `<your RFQ folder>/output/`. Use the returned link;
filenames are cleaned up and may have a numeric suffix.

The JSON run report, quality-check results and `.work/` checkpoints support
validation, recovery, follow-ups and comparisons. They remain internal and are
not included in the chat handoff. Keep `.work/` so later requests can resume
saved progress and answer questions.

## Requirements

Install the plugin in a supported application on a machine (or sandbox) with
Python 3.10+, `pip` and `venv`. The first run provisions the document libraries
automatically. See [INSTALL.md](INSTALL.md).

Do not run two analyses concurrently in the same RFQ folder. If a run stops,
correct the stated blocker and repeat the request. RFQ documents and outputs
may contain confidential customer information; keep them out of source control.
