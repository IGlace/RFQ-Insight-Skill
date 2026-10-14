"""Score a section's confidence from its deductions and explain it.

The model names catalogue rules (rfq/schema.py RULES) with a count and the
items they rest on; the runner adds its own (reviewer verdicts, corpus
misses, unread files). Everything numeric is decided here: the points of
each entry, the cap per code, the 1-10 score and its band, and the notes
text written under the section's first slide.
"""

from .schema import RULES, rule_applies, rule_points, rule_sections

BAND_WORD = {"high": "High", "medium": "Medium", "low": "Low"}
SHOWN_NOUNS = {2: "paragraphs", 3: "targets", 7: "rows", 10: "standards",
               11: "risks"}
NO_DEDUCTIONS = "No deductions: every item is stated in the documents."
NO_DEDUCTIONS_ABSENT = "No deductions: confirmed absent after a full sweep."


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
    """One notes line: "-2  S7.1  4 cells placed by inference: PM (SOR 3)"."""
    line = f"-{points}  {code}  {label(RULES[code], count)}"
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


def score(deductions, section, mode=None) -> int:
    """10 minus the points of the section's resolved deductions, at least 1.
    Entries without points are resolved first."""
    if any("points" not in entry for entry in deductions):
        deductions = resolve(deductions, section, mode, allow_python=True)
    return max(1, 10 - sum(entry["points"] for entry in deductions))


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


def notes(score, band, lines, check_line, shown_line, sources_block,
          not_found=False) -> str:
    """The section's notes: score and band, one line per deduction (or the
    no-deductions line), the check line, the shown line when trimmed, then
    the sources block after a blank line."""
    head = [f"Confidence {score}/10 ({BAND_WORD[band]})"]
    head += list(lines) or [NO_DEDUCTIONS_ABSENT if not_found else NO_DEDUCTIONS]
    head += [line for line in (check_line, shown_line) if line]
    text = "\n".join(head)
    return f"{text}\n\n{sources_block}" if sources_block else text


def merge_python_deductions(answer: dict, codes, entries) -> dict:
    """Replace the answer's entries of the runner's `codes` with `entries`,
    keeping the model's own; running it again gives the same list."""
    codes = set(codes)
    kept = [entry for entry in answer.get("deductions") or []
            if entry.get("rule") not in codes]
    answer["deductions"] = kept + [dict(entry) for entry in entries]
    return answer
