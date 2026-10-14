"""Invariants that keep duplicated content from drifting.

The skill deliberately states some things twice - once for Python, once for
the agent (and once per prompt). These tests are what make that safe.
"""

import os
import re

from conftest import SKILL_ROOT
from rfq import delivery
from rfq.schema import (RULES, SECTION_MODES, SECTION_SHAPES, TITLES,
                        describe_shapes)

REFERENCES = os.path.join(SKILL_ROOT, "references")
SECTIONS_MD = os.path.join(REFERENCES, "sections.md")
QA_PROMPT = os.path.join(REFERENCES, "prompts", "RFQ_QA_Extraction_Prompt_v14.md")
SLIDE_PROMPT = os.path.join(REFERENCES, "prompts", "RFQ_Slide_Plan_Prompt_v14.md")

_ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*$")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def parse_id_rows(path):
    """{id: (col2, col3)} out of every 3-column markdown pipe row whose first
    cell is a number."""
    out = {}
    for line in _read(path).splitlines():
        m = _ROW.match(line)
        if m:
            out[int(m.group(1))] = (m.group(2), m.group(3))
    return out


def test_sections_md_matches_schema_titles():
    assert parse_id_rows(SECTIONS_MD) == TITLES


def _table_after(text, header):
    """The data rows (lists of cells) of the pipe table whose header row is
    exactly `header`."""
    lines = text.splitlines()
    start = lines.index(header)
    assert re.fullmatch(r"\|(\s*-+\s*\|)+", lines[start + 1]), header
    rows = []
    for line in lines[start + 2:]:
        if not line.startswith("|"):
            break
        rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows


# Sections the analysis worker answers; 12 is built by the application.
MODEL_SECTIONS = tuple(range(1, 12))


def test_qa_prompt_lists_the_same_twelve_sections_and_their_modes():
    """Stage 1 is matched on id alone, so its prompt must carry exactly the
    schema's ids and titles - a retitled or renumbered row would silently
    route an answer to the wrong slide. The mode column is the schema's."""
    rows = _table_after(_read(QA_PROMPT), "| id | title | mode |")
    assert [int(row[0]) for row in rows] == list(range(1, 13))
    for number, title, mode in rows:
        number = int(number)
        assert title == TITLES[number][0], number
        expected = ("built by the application" if SECTION_MODES[number] == "python"
                    else SECTION_MODES[number])
        assert mode == expected, number
    assert SECTION_MODES[12] == "python"


def test_qa_prompt_section_headings_carry_title_and_mode():
    """Each section's rule block is headed '### 7.N <title> — <mode>'."""
    headings = re.findall(r"^### 7\.(\d+) (.+) — (\w+)$", _read(QA_PROMPT), re.M)
    assert [int(n) for n, _, _ in headings] == list(MODEL_SECTIONS)
    for number, title, mode in headings:
        assert (title, mode) == (TITLES[int(number)][0],
                                 SECTION_MODES[int(number)])


def _sections_cell(cell):
    """'all' / '3-10' / '1' -> the section ids among 1-11 it names."""
    if cell == "all":
        return set(MODEL_SECTIONS)
    out = set()
    for part in cell.split(","):
        low, _, high = part.strip().partition("-")
        out.update(range(int(low), int(high or low) + 1))
    return out


def _model_rules():
    return {code: rule for code, rule in RULES.items() if rule.source == "model"}


def _rule_ids(rule):
    ids = set(MODEL_SECTIONS) if rule.sections == "all" else set(rule.sections)
    return ids & set(MODEL_SECTIONS)


def test_qa_prompt_deduction_table_is_the_model_rule_catalogue():
    """The catalogue the model writes deductions from is schema.RULES:
    every model rule, code and label verbatim, the same sections, no points
    (Python owns them) and no reviewer or runner rule."""
    rows = _table_after(_read(QA_PROMPT), "| code | rule | sections |")
    assert all(len(row) == 3 for row in rows)
    model = _model_rules()
    assert [row[0] for row in rows] == list(model)
    for code, label, cell in rows:
        assert label == model[code].label, code
        assert _sections_cell(cell) == _rule_ids(model[code]), code


def test_qa_prompt_never_offers_a_runner_rule_or_points():
    text = _read(QA_PROMPT)
    runner = [code for code, rule in RULES.items() if rule.source != "model"]
    assert runner
    for code in runner:
        assert not re.search(rf"(?<![\w.]){re.escape(code)}(?![\w.])", text), code
    assert not re.search(r"\bpoints?\b[^.\n]*\b\d+\b", text)


def test_qa_prompt_per_section_deductions_use_only_allowed_codes():
    """Each section's 'Deductions:' rule names every section-specific code
    of that section and no code the section may not use."""
    text = _read(QA_PROMPT)
    model = _model_rules()
    blocks = re.split(r"^### 7\.", text, flags=re.M)[1:]
    assert len(blocks) == len(MODEL_SECTIONS)
    for block in blocks:
        number = int(block.split(" ", 1)[0])
        lines = [line for line in block.splitlines()
                 if re.match(rf"7\.{number}\.\d+ Deductions:", line)]
        assert len(lines) == 1, number
        named = set(re.findall(r"\b(G\d|S\d+\.\d+)\b", lines[0]))
        allowed = {code for code, rule in model.items()
                   if number in _rule_ids(rule)}
        own = {code for code, rule in model.items()
               if rule.sections != "all" and _rule_ids(rule) == {number}}
        assert named <= allowed, (number, named - allowed)
        assert own <= named, (number, own - named)


FOLLOWUP_PROMPT = os.path.join(REFERENCES, "prompts", "RFQ_Followup_Prompt_v2.md")


def test_followup_prompt_rule_table_is_the_additional_information_catalogue():
    """Follow-up answers (section 13) may use exactly the model rules that
    schema.RULES allows there, each in the mode it is limited to."""
    rows = _table_after(_read(FOLLOWUP_PROMPT), "| code | rule | mode |")
    model = {code: rule for code, rule in _model_rules().items()
             if rule.sections == "all" or 13 in rule.sections}
    assert [row[0] for row in rows] == list(model)
    for code, label, mode in rows:
        assert label == model[code].label, code
        assert mode == (model[code].mode or "both"), code


# CONTRACT §9: the markdown the parser of the deck reads, verbatim.
CANONICAL_SHAPES = (
    "Hub: <customer short>",
    "| Party | Type | Role |",
    "| Phase | Definition | Scope | Hardware milestone | Span |",
    "| Scope of Work | <in-scope phase names from section 6, in order> |",
    "| Milestone | Target timing | Phase / Task |",
    "## Project Risks",
    "## Document Risks",
    "`in scope`",
    "`referenced only: <why>`",
)


def test_qa_prompt_states_the_canonical_markdown_shapes_verbatim():
    text = _read(QA_PROMPT)
    missing = [shape for shape in CANONICAL_SHAPES if shape not in text]
    assert missing == []
    # the party Type values the collab parser maps, in the header's own rule
    assert ("header exactly `| Party | Type | Role |`, Type one of customer, "
            "avl, supplier, third;") in text


def _output_part(text):
    return text[text.index("## 10. Output"):]


def test_qa_prompt_output_contract_has_no_retired_field_or_section_12():
    """tldr, presentation and the free-text confidence are gone from the
    model's output, and the model never answers section 12."""
    output = _output_part(_read(QA_PROMPT))
    for retired in ("tldr", "confidence_reason", "presentation", '"id": 12'):
        assert retired not in output, retired
    assert '"id": <1..11>' in output


def _slide_prompt_shapes():
    """The SECTION SLIDE SHAPES table of the stage-2 prompt as
    {id: (section title, ((layout, ...), ...))}, parsing the prompt's
    "gantt + table, or timeline + table" wording."""
    text = _read(SLIDE_PROMPT)
    start = text.index("SECTION SLIDE SHAPES (fixed")
    out = {}
    for line in text[start:].splitlines():
        m = _ROW.match(line)
        if not m:
            if out and not line.startswith("|"):
                break                       # the table ended
            continue
        shapes = tuple(tuple(part.strip() for part in alt.split("+"))
                       for alt in re.split(r",\s*or\s+", m.group(3)))
        out[int(m.group(1))] = (m.group(2), shapes)
    return out


def test_slide_prompt_shape_table_matches_schema_section_shapes():
    """Every id in SECTION_SHAPES has a row in the Slide prompt's SECTION
    SLIDE SHAPES table, titled as the schema titles it and permitting
    exactly the shapes the validator permits."""
    rows = _slide_prompt_shapes()
    assert set(rows) == set(SECTION_SHAPES) == set(TITLES)
    for number, shapes in SECTION_SHAPES.items():
        title, permitted = rows[number]
        assert title == TITLES[number][0], number
        assert permitted == shapes, (number, permitted, shapes)
        # and the repair message names the same alternatives
        assert describe_shapes(number) == " or ".join(
            " + ".join(alt) for alt in permitted)


SKILL_MD = os.path.join(SKILL_ROOT, "SKILL.md")

# Naming any of these would couple the skill to one harness. The skill
# describes ACTIONS ("run scripts/rfq_run.py"), never tool names.
FORBIDDEN_TOOL_NAMES = ("Bash", "Read", "Write", "Edit", "MultiEdit",
                        "Glob", "Grep", "Task", "Skill", "WebFetch",
                        "NotebookEdit", "TodoWrite")


def _skill_parts():
    """(frontmatter, procedure body) of SKILL.md."""
    text = _read(SKILL_MD)
    assert text.startswith("---\n")
    return text[4:].split("\n---\n", 1)


def test_skill_md_names_no_harness_tool():
    _, body = _skill_parts()
    offenders = [name for name in FORBIDDEN_TOOL_NAMES
                 if re.search(rf"\b{name}\b", body)]
    assert offenders == [], f"SKILL.md names harness tools: {offenders}"


def test_skill_frontmatter_grants_no_tools_and_installs_no_hooks():
    """Client requirement: the plugin carries no hook and pre-approves no
    tool. The host's own permission flow applies, unmodified."""
    frontmatter, _ = _skill_parts()
    assert "allowed-tools" not in frontmatter
    assert re.search(r"^name:\s*rfq-insight\s*$", frontmatter, re.M)
    plugin_root = os.path.dirname(os.path.dirname(SKILL_ROOT))
    assert not os.path.exists(os.path.join(plugin_root, "hooks"))


def test_deck_names_keep_the_client_format_and_stay_readable():
    """'RFQ Insight_<Opportunity name>_<DDMMYYYY>': the opportunity name is
    kept readable (spaces, dashes and umlauts survive); only what Windows
    forbids in a file name is dropped."""
    assert delivery.deck_basename("Acme V6", "2026-10-06") \
        == "RFQ Insight_Acme V6_06102026"
    assert delivery.deck_basename("Lorem – Jänner/Q3: Test?", "2026-10-06") \
        == "RFQ Insight_Lorem – JännerQ3 Test_06102026"
    assert delivery.safe_filename("Acme V6") == "Acme V6"
    assert delivery.safe_filename('a<b>c:d"e/f\\g|h?i*j') == "abcdefghij"
    assert delivery.safe_filename("  two   spaces . ") == "two spaces"
    assert delivery.safe_filename("") == "RFQ"
    name = delivery.safe_filename("x" * 400)
    assert delivery.safe_filename(name) == name          # idempotent
    assert len(name) == delivery.MAX_NAME


def test_deck_names_are_truncated_at_a_word_to_fit_the_path_limit():
    """A deeply nested RFQ folder plus a long opportunity name must still
    give a path under MAX_PATH; the name part is cut at a word boundary and
    the prefix and date are never touched."""
    out_dir = os.path.join(os.sep, *["deep"] * 20, "output")   # ~107 chars
    full = delivery.deck_basename("Alpha Beta " * 20, "2026-10-06")
    base = delivery.deck_basename("Alpha Beta " * 20, "2026-10-06", out_dir)
    assert len(os.path.join(out_dir, full + ".pptx")) > delivery.MAX_PATH
    assert len(os.path.join(out_dir, base + ".pptx")) <= delivery.MAX_PATH
    assert base.startswith("RFQ Insight_Alpha Beta ")
    assert base.endswith("_06102026")
    assert len(base) < len(full)
    name = base[len("RFQ Insight_"):-len("_06102026")]
    assert name.split(" ")[-1] in ("Alpha", "Beta")       # cut at a word
    # a short name in the same folder is not touched at all
    assert delivery.deck_basename("Acme V6", "2026-10-06", out_dir) \
        == "RFQ Insight_Acme V6_06102026"


def test_skill_md_never_builds_a_deliverable_filename_itself():
    """SKILL.md used to tell the agent to run the quality gate on
    `<folder>/output/<name>_RFQ_Analysis.json`, where `<name>` was the
    opportunity name the user typed - a path that never existed once the
    name carried a space. The runner names the deliverables (see
    rfq/delivery.py) and the paths it prints are the only authority."""
    body = _read(SKILL_MD)
    # A placeholder for the user's wording glued to a deliverable extension
    # (`.work/.../<id>.json` is a checkpoint the runner names, not a guess).
    guesses = re.findall(r"<(?:[a-z ]*(?:name|opportunity|project|title)"
                         r"[a-z ]*)>[A-Za-z_ ]*\.(?:pptx|json)\b", body)
    assert guesses == [], \
        f"SKILL.md builds a deliverable filename from a placeholder: {guesses}"
    assert "RFQ Insight_<" not in body
    assert "_RFQ_Analysis" not in body


def test_skill_md_references_only_scripts_that_exist():
    body = _read(SKILL_MD)
    referenced = set(re.findall(r"scripts/([a-z_]+\.py)", body))
    assert referenced == {"bootstrap.py", "rfq_run.py"}, referenced
    for name in sorted(referenced):
        assert os.path.exists(os.path.join(SKILL_ROOT, "scripts", name)), \
            f"SKILL.md references a script that does not exist: {name}"
