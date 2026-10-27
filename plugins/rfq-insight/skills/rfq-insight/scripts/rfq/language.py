"""The language gate: answers are written in English, so a field that reads
as German, French, Italian or Spanish goes back for repair.

Pure Python and deliberately cheap. A field counts as foreign when more than
MAX_SHARE of its words are common function words of those languages. The
words in brackets are the customer's originals and a number-bearing token is
a designation ("VW 80000"), so neither is counted; a field too short to judge
(fewer than MIN_TOKENS words) scores 0.0.
"""
import re
import unicodedata

from .validation import _cells

# Lowercase function words of three or more letters (shorter tokens are never
# counted). Words that are also English words an RFQ may use ("per", "plus",
# "sin", "hat", "man", "die", "come", "con", "son", "hay", "para", "sans",
# "tout") are left out on purpose.
FUNCTION_WORDS = {
    "de": frozenset("""der das und ist nicht mit für von den dem ein eine
        auf wird werden sind bei nach über oder auch des als aus zur zum durch
        vom wurde kann muss sowie bzw einer einem einen eines nur noch wenn
        aber sich keine kein ohne dass sie wir ihr ihre ihrer ihren ihrem
        seine seiner seinen""".split()),
    "fr": frozenset("""les des est une pour dans sur avec par pas sont que qui
        aux cette ses nous vous leur leurs mais ont été être fait sous
        elle ils elles comme aussi entre doit doivent avant selon chez
        ces""".split()),
    "it": frozenset("""gli del della dei delle che non una uno sono dal nel
        dello degli alla alle nella nelle anche questo questa essere tra fra
        più molto senza sul sulla ogni suo sua loro deve devono entro secondo
        presso negli dalla dalle dagli dell nell dall sull dallo nelle""".split()),
    "es": frozenset("""los las del que por una como más esta este
        pero sobre entre también todo cada muy sus nos ser debe deben antes
        según desde hasta donde cuando estos estas tiene tienen sino""".split()),
}
_ALL = frozenset().union(*FUNCTION_WORDS.values())

# Words that name a party's role, not a party ("Lieferant", "client"): a
# bracketed "original" made only of them is no party name
# (validation._party_names).
ROLE_WORDS = frozenset("""lieferant lieferanten zulieferer unterlieferant kunde
    kunden auftraggeber auftragnehmer hersteller anbieter bieter besteller
    dienstleister partner fournisseur fournisseurs client clients fabricant
    constructeur prestataire sous-traitant acheteur fornitore fornitori
    cliente clienti committente produttore costruttore appaltatore proveedor
    proveedores fabricante contratista subcontratista comprador supplier
    customer manufacturer contractor subcontractor vendor buyer oem""".split())


def is_function_word(word: str) -> bool:
    """`word` is a function word of German, French, Italian or Spanish
    ("der", "mit", "les", "della")."""
    return str(word).strip().lower() in _ALL


def is_role_word(word: str) -> bool:
    """`word` names a party's role ("Lieferant", "client"), not a party."""
    return str(word).strip().lower() in ROLE_WORDS

MIN_TOKENS = 6
MAX_SHARE = 0.25
MAX_PROBLEMS = 10
ANSWER_IDS = range(1, 12)

_WORD = re.compile(r"[^\W_]+(?:-[^\W_]+)*")
_SEPARATOR_CELL = re.compile(r":?-+:?")
_FILE_EXT = re.compile(r"\.(pdf|docx?|pptx?|xlsx?|csv|txt|msg|png|jpe?g)\b\W*$",
                       re.IGNORECASE)
_ABBREVIATION_LETTERS = 3


def _without_brackets(text: str) -> str:
    """The text without its bracketed groups, nested ones included, in one
    pass; a bracket that never closes stays."""
    out, opened = [], []
    for ch in text:
        if ch == "(":
            opened.append(len(out))
            out.append(ch)
        elif ch == ")" and opened:
            del out[opened.pop():]
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def _without_file_names(text: str) -> str:
    """File names are the customer's, not prose: chunks with an underscore
    or a document extension go."""
    return " ".join(c for c in text.split()
                    if "_" not in c and not _FILE_EXT.search(c))


def _tokens(text: str) -> list:
    """Words of three letters or more without digits, acronyms (all caps)
    and abbreviations ("est."); elisions split at the apostrophe."""
    text = _without_file_names(_without_brackets(
        unicodedata.normalize("NFC", str(text))))
    tokens = []
    for m in _WORD.finditer(text):
        word = m.group()
        if len(word) <= 2 or any(c.isdigit() for c in word) or word.isupper():
            continue
        if (len(word) <= _ABBREVIATION_LETTERS
                and text[m.end():m.end() + 1] == "."):
            continue
        tokens.append(word.lower())
    return tokens


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
