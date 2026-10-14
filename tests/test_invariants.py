"""Invariants that keep duplicated content from drifting.

The skill deliberately states some things twice - once for Python, once for
the agent (and once per prompt). These tests are what make that safe.
"""

import os
import re

from conftest import SKILL_ROOT
from rfq import delivery
from rfq.schema import SECTION_SHAPES, TITLES, describe_shapes

REFERENCES = os.path.join(SKILL_ROOT, "references")
SECTIONS_MD = os.path.join(REFERENCES, "sections.md")
QA_PROMPT = os.path.join(REFERENCES, "prompts", "RFQ_QA_Extraction_Prompt_v13.md")
SLIDE_PROMPT = os.path.join(REFERENCES, "prompts", "RFQ_Slide_Plan_Prompt_v13.md")

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


def test_qa_prompt_lists_the_same_twelve_sections():
    """Stage 1 is matched on id alone, so its prompt must carry exactly the
    schema's ids and titles - a retitled or renumbered row would silently
    route an answer to the wrong slide."""
    rows = parse_id_rows(QA_PROMPT)
    assert rows == TITLES
    assert list(rows) == list(range(1, 13))


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
