"""Invariants that keep duplicated content from drifting.

The skill deliberately states some things twice - once for Python, once for
the agent. These tests are what make that safe.
"""

import os
import re

from conftest import SKILL_ROOT
from rfq.schema import TITLES

SECTIONS_MD = os.path.join(SKILL_ROOT, "references", "sections.md")

_ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*$")


def parse_sections_md(path=SECTIONS_MD):
    """Pull {id: (title_en, title_de)} out of the markdown pipe table."""
    out = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            m = _ROW.match(line.rstrip("\n"))
            if m:
                out[int(m.group(1))] = (m.group(2), m.group(3))
    return out


def test_sections_md_matches_schema_titles():
    assert parse_sections_md() == TITLES


SKILL_MD = os.path.join(SKILL_ROOT, "SKILL.md")

# Naming any of these would couple the skill to one harness. The skill
# describes ACTIONS ("run scripts/extract_corpus.py"), never tool names.
FORBIDDEN_TOOL_NAMES = ("Bash", "Read", "Write", "Edit", "MultiEdit",
                        "Glob", "Grep", "Task", "Skill", "WebFetch",
                        "NotebookEdit", "TodoWrite")


def _skill_body():
    """The procedure after the frontmatter. The frontmatter's `allowed-tools`
    grant legitimately names host tools; the procedure itself must not."""
    with open(SKILL_MD, encoding="utf-8") as fh:
        text = fh.read()
    assert text.startswith("---\n")
    return text.split("\n---\n", 1)[1]


def test_skill_md_names_no_harness_tool():
    body = _skill_body()
    offenders = [name for name in FORBIDDEN_TOOL_NAMES
                 if re.search(rf"\b{name}\b", body)]
    assert offenders == [], f"SKILL.md names harness tools: {offenders}"


def test_skill_frontmatter_pre_approves_the_tools_the_procedure_needs():
    with open(SKILL_MD, encoding="utf-8") as fh:
        frontmatter = fh.read().split("\n---\n", 1)[0]
    for rule in ("Bash(python *)", "Bash(python3 *)", "Bash(py *)", "Bash(mkdir *)",
                 "- Read", "- Write", "- Edit", "- Agent"):
        assert rule in frontmatter, rule


def test_skill_md_never_builds_a_deliverable_filename_itself():
    """SKILL.md used to tell the agent to run the quality gate on
    `<folder>/output/<name>_RFQ_Analysis.json`, where `<name>` was the
    opportunity name the user typed. finalize.safe_name replaces every run
    of [^A-Za-z0-9_.-] with "_", so any name with a space - the normal
    case - pointed the next step at a file that does not exist. The paths
    finalize prints are the only authority."""
    import finalize
    assert finalize.safe_name("Acme V6") == "Acme_V6"

    with open(SKILL_MD, encoding="utf-8") as fh:
        body = fh.read()
    guesses = re.findall(r"<[a-z]+>" + re.escape(finalize.SUFFIX), body)
    assert guesses == [], \
        f"SKILL.md builds a deliverable filename from a placeholder: {guesses}"


def test_skill_md_references_only_scripts_that_exist():
    with open(SKILL_MD, encoding="utf-8") as fh:
        body = fh.read()
    referenced = set(re.findall(r"scripts/([a-z_]+\.py)", body))
    assert referenced, "SKILL.md references no scripts at all"
    for name in sorted(referenced):
        assert os.path.exists(os.path.join(SKILL_ROOT, "scripts", name)), \
            f"SKILL.md references a script that does not exist: {name}"
