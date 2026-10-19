# Using RFQ Insight

Ask, in Codex, Claude Code or Claude Desktop Cowork:

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
- The twelve sections, their modes (extracted or analysed), their one-slide
  shapes, the confidence rules, model routes and independent verification are
  predefined. The plugin does not offer customization choices.
- Missing required inputs, unreadable supported documents, packages that are
  too large even after evidence factoring, unavailable required capabilities,
  three failed worker attempts and a failed quality check stop the run with
  one short sentence.
- Unsupported file types, including Outlook `.msg`, remain excluded.
  Individual illegible figures are recorded internally; they do not trigger
  questions.

## What the host does during a run

The skill drives one loop. It runs `rfq_run.py next "<folder>" --host codex`
(or `--host claude`); the runner does every Python step and stops when it
needs a model worker. The host starts one fresh worker per request, waits for
them, and calls `next` again with `--completed <request_id>` for each worker
that delivered and `--failed <request_id>` for each that did not. That one
call records the results and advances the run; it repeats until `done`.

In a normal run the workers are: figure transcription (one `.txt` per
picture, several requests in parallel), one analysis worker, and the
verification partitions (eight claims each, in parallel). No slide worker
runs unless an answer does not parse into its fixed shape.

## Reading the deck

Each section's chip shows its confidence band: `High`, `Medium` or `Low`. No
number is shown. The speaker notes of the section's first slide explain the
rating and nothing else before the sources:

```
Confidence: Medium
Basis: partly inferred - some content is not stated in the RFQ.
S7.1  4 cells placed by inference: PM, design review, cooling jacket, failure handling (Technical Agreement 3.3.2 gives no phase for them)
S7.2  2 RASIC conflicts resolved to one executing party: test bench setup, calibration sign-off (Table 2 lists Aurobay and Party B as R)
Contradictions: the documents were unclear or disagreed; the deductions above say how it was settled.
Check: 6 statements reviewed by a separate reviewer: 6 confirmed.
Shown: 13 of 16 standards.

Sources:
File: …
```

Each deduction line says why the rating was lowered: the rule code, the
items concerned and the file or clause they rest on, never the points it
cost. Only content not taken from the RFQ lowers the rating (an inference, an
estimate, a refuted or uncorroborated value); a contradiction, an unreadable
page or picture, an unnamed contractor or a claim the reviewer found
ambiguous is reported, never priced. A `Not rated High: …` line explains a
band held down by what the content is (decided, inferred or estimated).
`No deductions: …` means every item is stated in the documents (or confirmed
absent). `Shown:` appears only when the
slide holds fewer rows than the analysis found. Items an extracted section
had to infer keep a light-orange `(inferred)` label directly beside the
text, table entry or diagram label. In the Scope of Work matrix, `N/A` marks a
task the RFQ gives no owner in any phase, and `—` a phase the task does not
run in; the legend under the matrix says so. Source Material (section 12)
lists every file, how much of it was read, and which sections use it; it is
always rated High.

## Follow-up questions

Once a folder has been analysed, ask a question about it:

> In the Acme_V6 RFQ, which standard applies to the wiring harness?

The answer comes back in chat with a `Sources:` line. Each answer is marked
extracted or analysed and carries its own deductions; extracted answers are
checked against the documents for dates, standards and number+unit values.
Ask to add the answers to the presentation and a new deck is written with an
"Additional Information" section before Source Material, scored with the
lowest score of its answers; the earlier deck stays untouched. If the
documents changed since the run, the plugin re-reads them first and tells you
that the existing deck reflects the older files.

Answers cannot be added to the deck of a run made before the scored
confidence: the plugin replies "The RFQ analysis predates the current
scoring; run the analysis again before adding follow-ups." That deck still
renders with its old notes.

## Comparing two analyses

> Compare the RFQ analyses in RFQs\Acme_V6 and RFQs\Acme_V6_rev2

Both folders must hold a finished run. The plugin writes
`RFQ Insight Comparison_<A> vs <B>_<DDMMYYYY>.pptx` into folder A's `output/`
and returns its link. Section confidence bands are shown side by side
(`High → Medium`). No model is used.

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
