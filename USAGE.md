# Using RFQ Insight

Ask, in Claude Desktop Cowork, Claude Code or Codex:

> Analyse the RFQ package in RFQs\Acme_V6

In Cowork, connect the RFQ folder as the working folder and ask:

> Analyse the RFQ package in this folder

The plugin sends one permission notice, runs its fixed workflow and returns
one PowerPoint link, then stops. It does not ask setup questions, offer
workflow choices, explain its progress, or show its analysis, verification or
quality-check reasoning.

## Fixed behavior

- The deck's display name is the opportunity name the analysis finds
  (`<Customer short> – <Project title>`); a `--project` name you supply only
  seeds the cover until then. The file is named
  `RFQ Insight_<Opportunity name>_<DDMMYYYY>.pptx`.
- Saved progress resumes automatically. A completed run reuses its existing
  deck after checking it. An explicitly requested rerun restarts the named
  stage and everything after it.
- Existing decks and reports are preserved. New outputs receive the next
  unused suffix, such as `_2` or `_3`, when a filename is already taken.
- The twelve sections, their one-slide shapes, model assignments and
  independent verification are predefined. The plugin does not offer
  customization choices.
- Missing required inputs, unreadable supported documents, packages that are
  too large even after evidence factoring, unavailable required capabilities,
  three failed worker attempts and a failed quality check stop the run with
  one short sentence.
- Unsupported file types, including Outlook `.msg`, remain excluded.
  Individual illegible figures are recorded internally; they do not trigger
  questions.

## Follow-up questions

Once a folder has been analysed, ask a question about it:

> In the Acme_V6 RFQ, which standard applies to the wiring harness?

The answer comes back in chat with a `Sources:` line. Ask to add the answers
to the presentation and a new deck is written with an "Additional
Information" section before Source Material; the earlier deck stays
untouched. If the documents changed since the run, the plugin re-reads them
first and tells you that the existing deck reflects the older files.

## Comparing two analyses

> Compare the RFQ analyses in RFQs\Acme_V6 and RFQs\Acme_V6_rev2

Both folders must hold a finished run. The plugin writes
`RFQ Insight Comparison_<A> vs <B>_<DDMMYYYY>.pptx` into folder A's `output/`
and returns its link. No model is used.

## Files

The PowerPoint is saved in `<your RFQ folder>/output/`. Use the returned link;
filenames may carry a numeric suffix.

The JSON run report, quality-check results, follow-up history and `.work/`
checkpoints support validation and recovery. They remain internal and are not
included in the chat handoff. Keep `.work/` so later requests can resume saved
progress and answer follow-up questions.

## Requirements

Install the plugin in a supported application on a machine (or sandbox) with
Python 3.10+, `pip` and `venv`. The first run provisions the document libraries
automatically. See [INSTALL.md](INSTALL.md). Word page numbers in the notes
need a Windows host with Word; elsewhere the notes cite chapters.

Do not run two analyses concurrently in the same RFQ folder. If a run stops,
correct the stated blocker and repeat the request. RFQ documents and outputs
may contain confidential customer information; keep them out of source control.
