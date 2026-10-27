"""Invariants that keep duplicated content from drifting.

The skill deliberately states some things twice - once for Python, once for
the agent: the canonical sections, the deduction catalogue, the prompt files.
These tests are what make that safe.
"""

import os
import re

from conftest import SKILL_ROOT
from rfq import workers
from rfq.schema import (ADDITIONAL_INFO_ID, RULES, SECTION_IDS, TITLES,
                        rule_sections, rules_for)

REFERENCES = os.path.join(SKILL_ROOT, "references")
SECTIONS_MD = os.path.join(REFERENCES, "sections.md")
SKILL_MD = os.path.join(SKILL_ROOT, "SKILL.md")
PROMPTS = os.path.join(REFERENCES, "prompts")

_ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*$")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def parse_sections_md(path=SECTIONS_MD):
    """Pull {id: (title_en, title_de)} out of the markdown pipe table."""
    out = {}
    for line in _read(path).splitlines():
        m = _ROW.match(line)
        if m:
            out[int(m.group(1))] = (m.group(2), m.group(3))
    return out


def test_sections_md_matches_schema_titles():
    assert parse_sections_md() == TITLES


# Naming any of these would couple the skill to one harness. The skill
# describes ACTIONS ("run scripts/rfq_run.py next"), never tool names.
FORBIDDEN_TOOL_NAMES = ("Bash", "Read", "Write", "Edit", "MultiEdit",
                        "Glob", "Grep", "Task", "Skill", "WebFetch",
                        "NotebookEdit", "TodoWrite")


def _skill_parts():
    """(frontmatter, procedure). The frontmatter's `allowed-tools` grant
    legitimately names host tools; the procedure itself must not."""
    text = _read(SKILL_MD)
    assert text.startswith("---")
    head, body = re.split(r"\r?\n---\r?\n", text, maxsplit=1)
    return head, body


def test_skill_md_names_no_harness_tool():
    _, body = _skill_parts()
    offenders = [name for name in FORBIDDEN_TOOL_NAMES
                 if re.search(rf"\b{name}\b", body)]
    assert offenders == [], f"SKILL.md names harness tools: {offenders}"


def test_skill_frontmatter_pre_approves_the_tools_the_procedure_needs():
    frontmatter, _ = _skill_parts()
    for rule in ("Bash(python *)", "Bash(python3 *)", "Bash(py *)", "Bash(mkdir *)",
                 "- Read", "- Write", "- Edit", "- Agent"):
        assert rule in frontmatter, rule


def test_skill_md_references_only_the_two_entry_points():
    """The runtime has exactly two executables; everything under scripts/rfq/
    is internal. A procedure that named an internal module, or a script that
    no longer exists, would send the coordinator down a dead path."""
    _, body = _skill_parts()
    referenced = set(re.findall(r"scripts/([a-z_]+\.py)", body))
    assert referenced == {"bootstrap.py", "rfq_run.py"}
    for name in referenced:
        assert os.path.isfile(os.path.join(SKILL_ROOT, "scripts", name))
    assert not re.search(r"scripts/rfq/[a-z_]+\.py", body)


def test_adapters_reference_only_the_two_entry_points():
    for host in ("claude", "codex"):
        body = _read(os.path.join(REFERENCES, "platforms", f"{host}.md"))
        referenced = set(re.findall(r"\b([a-z_]+\.py)\b", body))
        assert referenced <= {"bootstrap.py", "rfq_run.py"}, (host, referenced)


def test_every_worker_prompt_exists_and_is_documented():
    documented = _read(os.path.join(PROMPTS, "README.md"))
    for stage, filename in workers.PROMPTS.items():
        assert os.path.isfile(os.path.join(PROMPTS, filename)), (stage, filename)
        assert f"`{filename}`" in documented, filename
    on_disk = {n for n in os.listdir(PROMPTS) if n.endswith(".md") and n != "README.md"}
    assert on_disk == set(workers.PROMPTS.values()), \
        "a prompt file is shipped that no worker reads, or vice versa"


def _rule_table(text, header):
    """Rows of the first pipe table whose header line is `header`."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == header)
    rows = []
    for line in lines[start + 2:]:
        if not line.startswith("|"):
            break
        rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows


def _expand(spec):
    """'1, 3-10' -> {1, 3, 4, ..., 10}"""
    out = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-")
            out.update(range(int(lo), int(hi) + 1))
        elif part:
            out.add(int(part))
    return out


def test_analysis_prompt_rule_table_matches_the_catalogue():
    """The analysis prompt lists the model's deduction codes verbatim, with
    the sections each may stand in; rfq/schema.py::RULES scores them. A code
    the prompt names but Python cannot score would be silently ignored, and
    a scoring rule the prompt omits would never be declared."""
    prompt = _read(os.path.join(PROMPTS, workers.PROMPTS["analysis"]))
    rows = _rule_table(prompt, "| code | rule | sections |")
    assert rows, "no rule table in the analysis prompt"
    listed = {code: (label, _expand(sections)) for code, label, sections in rows}
    expected = {code: rule for code, rule in RULES.items()
                if rule.source == "model"
                and set(rule_sections(rule)) & set(SECTION_IDS)}
    assert set(listed) == set(expected)
    for code, rule in expected.items():
        label, sections = listed[code]
        assert label == rule.label, code
        assert sections == set(rule_sections(rule)) - {ADDITIONAL_INFO_ID}, code


def test_followup_prompt_rule_table_matches_the_catalogue():
    prompt = _read(os.path.join(PROMPTS, workers.PROMPTS["followup"]))
    rows = _rule_table(prompt, "| code | rule | mode |")
    assert rows, "no rule table in the follow-up prompt"
    listed = {code: (label, mode) for code, label, mode in rows}
    expected = {}
    for mode in ("extracted", "analysed"):
        for rule in rules_for(ADDITIONAL_INFO_ID, mode):
            expected[rule.code] = (rule.label, mode)
    assert listed == expected


def test_knowledge_files_the_analysis_worker_reads_exist():
    knowledge = os.path.join(REFERENCES, "knowledge")
    files = sorted(n for n in os.listdir(knowledge) if n.endswith(".md"))
    assert len(files) == 9
    assert files[-1] == "90_guidance_denominators.md"
    data = os.path.join(REFERENCES, "data")
    assert os.path.isfile(os.path.join(data, "accounts.csv"))
    assert os.path.isfile(os.path.join(data, "vocabularies.json"))


SKILL_AREA_CODES = ("DS", "DD", "DM", "DC", "DJ", "DF", "DK", "DP", "DO", "DR", "DI")


def test_prompts_are_v15_and_v3():
    assert workers.PROMPTS["analysis"] == "RFQ_QA_Extraction_Prompt_v15.md"
    assert workers.PROMPTS["followup"] == "RFQ_Followup_Prompt_v3.md"


def test_analysis_prompt_carries_the_language_and_prose_rules():
    prompt = _read(os.path.join(PROMPTS, workers.PROMPTS["analysis"]))
    assert "3.11 Language:" in prompt and "(Konzept-Freeze)" in prompt
    assert 'reads "not available"' in prompt
    for code in SKILL_AREA_CODES:
        assert f"({code})" in prompt


def test_followup_prompt_answers_in_english():
    prompt = _read(os.path.join(PROMPTS, workers.PROMPTS["followup"]))
    assert "English always" in prompt
