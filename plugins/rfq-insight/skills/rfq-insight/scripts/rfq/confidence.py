"""Score a section's confidence from its deductions and explain it.

The model names catalogue rules (rfq/schema.py RULES) with a count and the
items they rest on; the runner adds its own (reviewer verdicts, corpus
misses, unread files). Everything numeric is decided here: the points of
each entry, the cap per code, the 1-10 score and its band, and the notes
text written under the section's first slide.

The score stays internal: it decides the band and is saved in the run
report, but no slide, chip or note shows it. The reader sees High / Medium /
Low and, in the notes, the reasons the rating was lowered, never the points
those reasons cost.
"""

import re

from .schema import RULES, rule_applies, rule_points, rule_sections

BAND_WORD = {"high": "High", "medium": "Medium", "low": "Low"}
SHOWN_NOUNS = {2: "paragraphs", 3: "targets", 7: "rows", 10: "standards",
               11: "risks"}
NO_DEDUCTIONS = "No deductions: every item is stated in the documents."
NO_DEDUCTIONS_ABSENT = "No deductions: confirmed absent after a full sweep."

# The rules that belong to section 1's Products/Skills slide ALONE. They are
# declared on the section 1 answer (the model has one answer per section) but
# must never reach the Opportunity Info rating: the client's whole point is
# that an estimated split may not be averaged in with the customer's legal
# name. rfq/verification.py keeps them out of the section score;
# rfq/opportunity.py scores the split slide from them.
SPLIT_RULES = ("P1", "P2")


def is_split(entry) -> bool:
    return str((entry or {}).get("rule", "")) in SPLIT_RULES


def partition_split(deductions) -> tuple:
    """(entries for the section, entries for the percentage slide)."""
    entries = list(deductions or ())
    return ([e for e in entries if not is_split(e)],
            [e for e in entries if is_split(e)])


def _sections_text(ids) -> str:
    """(3, 4, ..., 10, 13) -> "sections 3-10 and 13"; (3,) -> "section 3"."""
    runs = []
    for number in sorted(ids):
        if runs and number == runs[-1][1] + 1:
            runs[-1][1] = number
        else:
            runs.append([number, number])
    parts = [str(a) if a == b else f"{a}-{b}" for a, b in runs]
    if len(ids) == 1:
        return f"section {parts[0]}"
    words = parts[0] if len(parts) == 1 else (
        ", ".join(parts[:-1]) + " and " + parts[-1])
    return f"sections {words}"


def _rule(entry, section, mode, allow_python):
    """The catalogue rule of one entry, or ValueError naming what is wrong."""
    code = str(entry.get("rule", ""))
    rule = RULES.get(code)
    if rule is None:
        raise ValueError(f"Section {section} uses unknown rule {code}.")
    if rule.source == "python" and not allow_python:
        raise ValueError(f"Section {section} uses rule {code}, which only "
                         f"the runner may write.")
    if section not in rule_sections(rule):
        raise ValueError(f"Section {section} uses rule {code}, which belongs "
                         f"to {_sections_text(rule_sections(rule))}.")
    if not rule_applies(rule, section, mode):
        raise ValueError(f"Section {section} uses rule {code}, which applies "
                         f"to Additional Information only when the answer is "
                         f"{rule.mode}.")
    count = entry.get("count", 1)
    if type(count) is not int or count < 1:
        raise ValueError(f"Section {section} rule {code} needs a count of at "
                         f"least 1, not {count!r}.")
    return rule


def label(rule, count) -> str:
    """The rule's label for `count` items: "{count} cell(s)" -> "4 cells"."""
    return rule.label.format(count=count).replace(
        "(s)", "" if count == 1 else "s")


def deduction_line(points, code, count=1, items="", basis="") -> str:
    """One notes line: "4 owner cells assigned by inference: PM (SOR 3)".
    Neither `points` nor the rule code is printed: the notes say in plain
    English why the rating was lowered, not by how much or under which rule
    (the code stays in the run report's deductions)."""
    line = label(RULES[code], count)
    if items:
        line += f": {items}"
    return line + (f" ({basis})" if basis else "")


def resolve(deductions, section, mode=None, allow_python=False) -> list:
    """Each entry copied with its `points` and notes `line`. A code's cap
    holds across all its entries in the section (a once-rule costs its
    points once); entries past the cap cost 0. `mode` is the Additional
    Information answer's mode; `allow_python` admits the runner's own rules.
    Raises ValueError naming the first unknown or disallowed code."""
    spent = {}
    resolved = []
    for entry in deductions:
        rule = _rule(entry, section, mode, allow_python)
        count = entry.get("count", 1)
        limit = rule.points if rule.once else rule.cap
        points = min(rule_points(rule, count), limit - spent.get(rule.code, 0))
        spent[rule.code] = spent.get(rule.code, 0) + points
        resolved.append({**entry, "points": points, "line": deduction_line(
            points, rule.code, count, entry.get("items", ""),
            entry.get("basis", ""))})
    return resolved


def provenance(deductions=()) -> str:
    """What the section's content mostly IS: "extracted" (nothing was
    inferred or decided), "decided" (the RFQ holds the fact but was unclear
    and a judgement settled it), "inferred" (the analysis supplied content
    the RFQ does not state) or "estimated" (an inference the whole slide
    rests on - a percentage split nobody stated, phases the RFQ never names).

    Read from the section's DECLARED deductions and nothing else. A section
    that reasons rather than quotes (Description, Risk Detection) says so
    through its own rules - S2.1 "sentences not backed by a statement in
    the RFQ", S11.1 "risks whose triggering clause could not be located" -
    so declaring none is a positive statement that every item does rest on
    the documents, not an oversight to be penalised a second time.

    Rules with no `kind` (V1, V3) are reliability failures, not provenance:
    they move the score but never this.
    """
    kinds = set()
    for entry in deductions or ():
        rule = RULES.get(str(entry.get("rule", "")))
        if rule is None or rule.kind is None:
            continue
        kinds.add("estimated" if rule.dominant else rule.kind)
    for level in ("estimated", "inferred", "decided"):
        if level in kinds:
            return level
    return "extracted"


# The highest score each provenance may reach, whatever the points say.
# Client requirement 1, 15.10.2026: High means "extracted, no interpretation",
# so content the analysis decided or supplied may not present itself as High
# merely because it cost few points. The ceilings are the TOP OF A BAND
# (`band` reads high from 7, medium from 4), which is what keeps the number
# and the word from ever contradicting each other.
SCORE_CEILING = {"extracted": 10, "decided": 6, "inferred": 6, "estimated": 3}


def score(deductions, section, mode=None) -> int:
    """10 minus the points of the section's resolved deductions, capped by
    what the content actually IS (see `provenance`), at least 1. Entries
    without points are resolved first."""
    if any("points" not in entry for entry in deductions):
        deductions = resolve(deductions, section, mode, allow_python=True)
    value = 10 - sum(entry["points"] for entry in deductions)
    return max(1, min(value, SCORE_CEILING[provenance(deductions)]))


def band(value) -> str:
    """"high" from 7, "medium" from 4, else "low"."""
    return "high" if value >= 7 else "medium" if value >= 4 else "low"


def shown_line(section, shown) -> str:
    """"Shown: 13 of 16 standards." when the answer was trimmed, else ""."""
    if shown is None:
        return ""
    if isinstance(shown, dict):
        found, kept = shown.get("found", 0), shown.get("shown", 0)
    else:
        found, kept = shown.found, shown.shown
    noun = SHOWN_NOUNS.get(section)
    if not noun or found <= kept:
        return ""
    return f"Shown: {kept} of {found} {noun}."


# Plain-English answer to "was this extracted or inferred?", written into
# every slide's notes (client requirement 4, 15.10.2026).
BASIS_WORD = {
    "extracted": "Basis: extracted from the RFQ documents, no interpretation.",
    "decided": "Basis: extracted from the RFQ documents, with a judgement "
               "made where they were unclear.",
    "inferred": "Basis: partly inferred - some content is not stated in the "
                "RFQ.",
    "estimated": "Basis: AI interpretation. The RFQ does not state this "
                 "directly; treat it as a starting point, not a fact.",
}
NO_CONTRADICTIONS = "Contradictions: none detected."
CONTRADICTIONS = ("Contradictions: the documents were unclear or disagreed; "
                  "the deductions above say how it was settled.")


def settled_a_conflict(deductions=()) -> bool:
    """Whether any `decided` rule fired. Asked separately from `provenance`:
    a section that both settled a conflict AND inferred something reads as
    "inferred" there, but the conflict is still a fact the reader must be
    told about."""
    for entry in deductions or ():
        rule = RULES.get(str(entry.get("rule", "")))
        if rule is not None and rule.kind == "decided":
            return True
    return False


# Said only when the ceiling actually bit: the deduction lines alone would
# have left the section at High, so the reader is told what held it lower.
CAPPED = {
    "decided": "Not rated High: the documents were unclear here and the "
               "analysis settled it.",
    "inferred": "Not rated High: some of this is not stated in the RFQ.",
    "estimated": "Not rated above Low: this is an AI estimate.",
}


def cap_line(score, deductions=()) -> str:
    """The sentence explaining a rating the deduction lines alone would not
    have lowered that far, or "" when they would."""
    kind = provenance(deductions)
    raw = 10 - sum(entry.get("points", 0) for entry in deductions or ())
    if kind == "extracted" or band(score) == band(max(1, raw)):
        return ""
    return CAPPED[kind]


def basis_lines(deductions=()) -> list:
    """The two provenance sentences for one section's notes."""
    return [BASIS_WORD[provenance(deductions)],
            CONTRADICTIONS if settled_a_conflict(deductions)
            else NO_CONTRADICTIONS]


def notes_header(band) -> str:
    """The first line of a rated section's notes: "Confidence: Medium"."""
    return f"Confidence: {BAND_WORD[band]}"


def notes(score, band, lines, check_line, shown_line, sources_block,
          not_found=False, deductions=()) -> str:
    """The section's notes: the band, what the content IS, one line per
    deduction (or the no-deductions line), whether anything had to be
    settled, the check line, the shown line when trimmed, then the sources
    block after a blank line. `score` is used only to tell whether the
    provenance ceiling lowered the band; it is never printed."""
    basis, contradictions = basis_lines(deductions)
    head = [notes_header(band), basis]
    head += list(lines) or [
        NO_DEDUCTIONS_ABSENT if not_found else NO_DEDUCTIONS]
    head += [line for line in (cap_line(score, deductions), contradictions,
                               check_line, shown_line) if line]
    text = "\n".join(head)
    return f"{text}\n\n{sources_block}" if sources_block else text


# What a run report saved before the scores were hidden still carries in its
# notes; `unscored` rewrites it so a replayed deck shows no number either.
_SCORED_HEADER = re.compile(r"^Confidence (?:10|[1-9])/10 \((High|Medium|Low)\)",
                            re.MULTILINE)
_POINTS_PREFIX = re.compile(r"^-\d+  (?=\S)", re.MULTILINE)
_RULE_CODE_PREFIX = re.compile(r"^[A-Z]\d+(?:\.\d+)?  (?=\S)", re.MULTILINE)
_CAPPED_PREFIX = re.compile(r"^Capped at (?:10|[1-9])/10: ", re.MULTILINE)
_SCORE_SUFFIX = re.compile(r": ((?:10|[1-9]))/10$", re.MULTILINE)


def unscored(text) -> str:
    """`text` (a section's notes) without any score or deducted points:
    the old "Confidence 6/10 (Medium)" header, "-2  S7.1 ..." lines,
    "Capped at 6/10: ...", a follow-up's trailing ": 6/10" and the leading
    rule code ("S7.1  ...") older versions printed on deduction lines."""
    text = _SCORED_HEADER.sub(lambda m: notes_header(m.group(1).lower()),
                              str(text or ""))
    text = _POINTS_PREFIX.sub("", text)
    text = _RULE_CODE_PREFIX.sub("", text)
    text = _CAPPED_PREFIX.sub("Not rated higher: ", text)
    return _SCORE_SUFFIX.sub(
        lambda m: ": " + BAND_WORD[band(int(m.group(1)))], text)


def merge_python_deductions(answer: dict, codes, entries) -> dict:
    """Replace the answer's entries of the runner's `codes` with `entries`,
    keeping the model's own; running it again gives the same list."""
    codes = set(codes)
    kept = [entry for entry in answer.get("deductions") or []
            if entry.get("rule") not in codes]
    answer["deductions"] = kept + [dict(entry) for entry in entries]
    return answer
