"""The language gate: answers are written in English, so a field that reads
as German, French, Italian or Spanish goes back for repair.

Pure Python and deliberately cheap. A field counts as foreign when more than
MAX_SHARE of its words are common function words of those languages. The
words in brackets are the customer's originals and a number-bearing token is
a designation ("VW 80000"), so neither is counted; a field too short to judge
(fewer than MIN_TOKENS words) scores 0.0.
"""
import re

from .validation import _cells

# Lowercase function words of three or more letters (shorter tokens are never
# counted). Words that are also common English words in an RFQ ("per", "plus",
# "sin", "hat", "man") are left out on purpose.
FUNCTION_WORDS = {
    "de": frozenset("""der die das und ist nicht mit für von den dem ein eine
        auf wird werden sind bei nach über oder auch des als aus zur zum durch
        vom wurde kann muss sowie bzw einer einem einen eines nur noch wenn
        aber sich keine kein ohne dass sie wir ihr ihre ihrer ihren ihrem
        seine seiner seinen""".split()),
    "fr": frozenset("""les des est une pour dans sur avec par pas sont que qui
        aux cette ses nous vous leur leurs mais ont été être fait sans sous
        elle ils elles comme aussi entre tout""".split()),
    "it": frozenset("""gli del della dei delle che con non una uno sono dal nel
        dello degli alla alle nella nelle anche questo questa essere tra fra
        più molto senza sul sulla ogni suo sua loro""".split()),
    "es": frozenset("""los las del que con por para una son como más esta este
        pero sobre entre también todo cada muy sus nos hay ser""".split()),
}
_ALL = frozenset().union(*FUNCTION_WORDS.values())

MIN_TOKENS = 6
MAX_SHARE = 0.25
MAX_PROBLEMS = 10
ANSWER_IDS = range(1, 12)

_BRACKETED = re.compile(r"\([^()]*\)")
_WORD = re.compile(r"[^\W_]+(?:[-'’][^\W_]+)*")
_SEPARATOR_CELL = re.compile(r":?-+:?")


def _tokens(text: str) -> list:
    text = str(text)
    while True:
        stripped = _BRACKETED.sub(" ", text)
        if stripped == text:
            break
        text = stripped
    return [t for t in _WORD.findall(text.lower())
            if len(t) > 2 and not any(c.isdigit() for c in t)]


def foreign_share(text: str) -> float:
    """The share of the field's words that are function words of another
    language; 0.0 for a field with fewer than MIN_TOKENS words."""
    tokens = _tokens(text)
    if len(tokens) < MIN_TOKENS:
        return 0.0
    return sum(t in _ALL for t in tokens) / len(tokens)


def fields(answer_markdown: str) -> list:
    """The units of a markdown answer, in order: every non-separator table
    cell, every paragraph (lines up to a blank line) and every "- " item."""
    out, paragraph = [], []

    def flush():
        if paragraph:
            out.append(" ".join(paragraph))
            paragraph.clear()

    for raw in str(answer_markdown).splitlines():
        line = raw.strip()
        if not line:
            flush()
        elif line.startswith("|"):
            flush()
            cells = _cells(line)
            if all(_SEPARATOR_CELL.fullmatch(c) for c in cells):
                continue
            out.extend(c for c in cells if c)
        elif line.startswith("- "):
            flush()
            out.append(line[2:].strip())
        else:
            paragraph.append(line)
    flush()
    return out


def _problem(label: str, field: str) -> str:
    shown = " ".join(field.split())[:60]
    return f'{label}: not English: "{shown}"'


def _check_fields(label: str, texts) -> list:
    return [_problem(label, f) for f in texts if foreign_share(f) > MAX_SHARE]


def check_text(text: str, label: str = "Follow-up") -> list:
    """Problems for one answer text (a follow-up answer)."""
    if not isinstance(text, str):
        return []
    return _check_fields(label, fields(text))[:MAX_PROBLEMS]


def check_analysis(analysis: dict) -> list:
    """Problems for sections 1-11: every field of the answer and each
    deduction's items and basis, phrased so the worker can find the field."""
    problems = []
    answers = analysis.get("answers") if isinstance(analysis, dict) else None
    for answer in answers if isinstance(answers, list) else []:
        if not isinstance(answer, dict):
            continue
        number = answer.get("id")
        if type(number) is not int or number not in ANSWER_IDS:
            continue
        texts = fields(answer["answer"]) if isinstance(answer.get("answer"), str) else []
        deductions = answer.get("deductions")
        for entry in deductions if isinstance(deductions, list) else []:
            if isinstance(entry, dict):
                texts.extend(entry[k] for k in ("items", "basis")
                             if isinstance(entry.get(k), str))
        problems.extend(_check_fields(f"Section {number}", texts))
        if len(problems) >= MAX_PROBLEMS:
            break
    return problems[:MAX_PROBLEMS]
