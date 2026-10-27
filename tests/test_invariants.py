"""Invariants that keep duplicated content from drifting.

The skill deliberately states some things twice - once for Python, once for
the agent: the canonical sections, the deduction catalogue, the prompt files.
These tests are what make that safe.
"""

import hashlib
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


def test_skill_md_describes_the_intake_exception():
    _, body = _skill_parts()
    assert "## Attached documents" in body
    assert "Which folder name should I use for this RFQ?" in body
    assert "--mode add" in body and "--mode replace" in body
    assert "--author" in body and "--department" in body


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
    rule_33 = next(line for line in prompt.splitlines() if line.startswith("3.3 "))
    assert "phase names" not in rule_33
    assert "translate only the items rule 3.11 names" in rule_33
    rule_761 = next(line for line in prompt.splitlines() if line.startswith("7.6.1 "))
    assert "follows rule 3.11" in rule_761


def test_followup_prompt_answers_in_english():
    prompt = _read(os.path.join(PROMPTS, workers.PROMPTS["followup"]))
    assert "English always" in prompt
    assert "3.11" not in prompt
    assert "stay verbatim" in prompt


KNOWLEDGE_80 = os.path.join(REFERENCES, "knowledge", "80_avl_nomenclature_and_skill_areas.md")
TEAM_CODES = ("DSV DSC DSP DSA DSS DSD DSG DSR DSF DDE DDI DDM DDC DDD DDT DDP DMB DMM DMV DMC DMI DML "
              "DCX DCO DCP DCC DCS DJF DJS DJT DJV DFD DFM DFO DFS DFT DKC DKD DKS DKT DPP DOP DOI").split()


# SHA-256 of the lowercased surnames in the two organisation announcements (area
# heads, team leads, chief engineers, business-unit functions, signatories), so the
# names themselves never enter the repository. None may appear in the knowledge file.
PEOPLE_IN_ANNOUNCEMENTS_SHA256 = frozenset({
    "01849f9accf9d029d609c69d826a88783f6cf8d821ef3da1b66e1b4943edcea8",
    "03fb94180aa0ff2c583d97bbb1fc6d84a6ba7df5bde3c267459bb9a9b8c9841b",
    "097443ddcdac0fe0ad1f64445eaf53caad5c89a62322b32c7d6ff8d0d2f4321e",
    "0af64f19017ee96bc38afb8b7a7caba25f32cc61d1f91ac02a65c26965f1fdaa",
    "0b57879f5c5772d4e352cf1341d2afc7e9a80320f46972cf9817026f9f37ee8e",
    "0cbdf9577eb455185f9a68c1127a886f79fbba5f5d74ee190b3fd133199b18c7",
    "120c6db7cc90742016baddf57fc5db94c0b2c1c1141894d5a39d609d1aaa5f84",
    "1551d1eb020a113540d8ceb787d53b17750037ceeade4ceeafb67919ebbd7265",
    "185af55f5998a418e43d646f186f88a301e311e56e127e4a8ae14403c9f5eb00",
    "1d786ee2b0ed83c47228fb690ce83d14442f9eb8c42871e200640240c4f8f6b3",
    "20d29c0aebb7b385574657ec1e87ff95e089a18b8b24a347f330a505310380d8",
    "23635671b14ff3f69e01d9f32f74ae309de09a953f6b49385b3a81b3239237db",
    "2c9e17e0efca5899feadff3e96253829126e1b38378f6fb7734be91016fd0b95",
    "2df97378b712ab69fbbba62d5445c7308624cb18c04b58ef806e97e6f543c01f",
    "2f644700e2116b2c1a0784179cf4b5d8dd3ebd0385988888486c191874993a83",
    "3974768352e7c3173565d84b0d666bc23f70c65cb5ec1684ef46095175191b9b",
    "3a9a588cbc5a98ec81d42a00b1dc1ed4b64c27279f6f4104ede61d223e9d16d2",
    "3b00a52f6037e01424487f45fdc4b5f71891118aa1822bf83f5f5b2d41700b13",
    "4036a9e2ed951c0044ca3271d547fa24f3a9cf2f03c0cd7e5f1f6294be27d5d9",
    "42086d00f59a40467c29c8f94101577775b8b58c848a7020959a12a8558ce664",
    "42962a4e46d9b573bf83a116dd53163982d5944d860ebb2a103caad0c1fdc134",
    "462c91093e93294a6ff222934daa3a12dbc9f3d46684d3d7285504e4b58c84e3",
    "4748d4c802a775e8db9a23ec58f0986cacdc5d2d3356d22c490a7d22331ff133",
    "49ee5d7a4358b1688d64564be9ae68f2d6cc5ed615723da2aeb074c14feffaa4",
    "4bdbc215d8dc3c571e802a69bced0c3071cc4a1f129ad97e15b357018aac6cd4",
    "4d2ce2ff8c4873bc8e204591ac893ba52fa08b54ca75ab817f6ced29b8da7ddd",
    "4e7cca5a936679699164038ea6ef227fabad1a061daa754dd4c48f9eb40d8d18",
    "4f9f306c876a1609c7b43aa9751dc0c8d35cdbeb961374a4e7821bbe62134883",
    "4ff7b31280d6d96507b2d5f967abad2416b0140a00274996a6c0fb6e966a6dad",
    "53870b1610f2b17244da4f0790458acce4ed99b13cc66faa4b005043085aec51",
    "55989b5a2680158a6ec389aa3f45ee256f9729f89b79241fb7fb77e991e69f86",
    "5baf133faf32df5bd738c83e5cb1885d4607358d3a7dfb16c8c8f4e16d4206c8",
    "64199f675b8b8f25c4423737a104e3f456f719d4f5c769fa706ea4872e2d50d1",
    "67c0d24d27237820ed1c8c80b5cb7de9743e6789e5c743b4d27c029ccc57a166",
    "68bbb17c100cb1fae4dd0aba03ebd83fefd8a9b68793b8a218d3c12f6cb9bd94",
    "6dea11ab84c44cf0254be06c86e87d0bf08670bd77115d8cdc53b19508c3d765",
    "72d4cf7752eec5e27637706a5aec3869261911e31971b10c9640d1fe0b5dd22a",
    "7b1fe418be6ca883945f6dd8e80df49c293700b10944ba621e9cf52d2a8c91b7",
    "7dd2f3de2cba1bd694a0187bfbbb519fabcb95b1d77c858ce0b955502c1e3de3",
    "7dfc9a6cb61828a32effc20fc062d7767e5aa63e3f422d0876bab157c624a34c",
    "8280923fdd901fb65e10c676c130345bf571fb0d4c7f69e559b2cffab9570622",
    "82ddf06044ac2494ea18823e7541ca425689043b237707204218e414109d942e",
    "88f13c6af1bfc5d17f498f282cc674916fa438d09b3c58283b24a06cc4578d93",
    "8a57c7de5c0641ecbe1074eba095ca34c2142cc63230c475c0038d83f2a8f01b",
    "8e34e10d3761ed97805ca2f31b3a72eac41dfbcf6b64fbd1365443be3f9b0fda",
    "8efd8f84013f665550a45ad850e4061e1aedf814838144966af6144e698836aa",
    "94e901841eb6585b46f65d95ea202933088bc897a39b8f21721a46da46e5b03c",
    "980fd8b834527d95d80184f4f676bc8b8c5baa90240d6b4c8af81f8d1ea13d02",
    "98ea52745a3ed57bd79cd06a3a9c44093f3b9f0a48606317b85c2ebfdc1bf043",
    "99dee7ecf4f2028bb5d27395292532853ff13b875fe8dbe06503756e5641a996",
    "9ae58bda03f2c1f5c806a3e9b1f74ba239268c3bd1fd454191893d22a46ec1c6",
    "9c5f9ea54b4d8ce73065ff06d0fde839b917437f0a8f4110df7133f745a29559",
    "9c8e7441a72456b2576b90e75eb90628214bf732e426ef2f218fe25bb6d6e3a0",
    "9fdd214866bef9474efca4ceee036966cb509e8fe657d9d8bed562064cd5363a",
    "a336a46f53da6ce990377cb18977bd2e31f94f725f0282b1026058e5c39ad863",
    "a3a8b78152fb5f947ab86d7c6925c0f9d51420d5aac1e88392a23c7afd4ff620",
    "a538d8f81203ae6164d938c9d3f6778711131ed0c5bc9dd04231b3e7c7f01b90",
    "a5822a8c8b00deb97c29a1e397b34b4d85877265e533fd6e55e836f5fafb167f",
    "a8ca634d09a6fd4d3f9ca3cbc007a14593b7c28eeef493cffb755218dcc99bbe",
    "a8eb1895a04644c904257352d8dba16e212faf24bf8dab14b1e00193108da24f",
    "a92531871708165bf79d3d6e54ee909a39f3486233ff6b77718b184e6caef8e0",
    "a9450d6defa83ca27a40fd7ab781b9583d29270758b54dba4a80fd303b42c98b",
    "a961203ac345715af5059734a2f078099f163454e3b7652b570c83d83ce49ab7",
    "ac1991f2a7f327c1cdbc4eefbdfc92fe560fec4005db29a0c7ad80dea3ad4857",
    "ac4f1e6d62f075e9ace7cdc14f1dae6d1407b523f441a16dd0789aa4f8ca58e2",
    "ad4a272d89efd4ad7ec7988d0dbb86eee32ab56fd3a9918f91e490a490dd427a",
    "ae85f8a721659fa2b8650930c6fb0f95ceca68cd3d470699eca8bba510a1ed70",
    "b14fef1c36595ac99b4e6bce1d657eba80c9c8efc8f9944158bf95ca604227f8",
    "b346c1e9184641719f59eaa3f115a1adb2130d5a5e36580addd1d7c60684b0a1",
    "b3d5a520c56a0e154a6f7b5870878346dd7c3df012b7e5abf76073cd8159eca6",
    "b4ff4bd02a8efb4dd9e94d613270a63d29f3b962750ceb51b104aaafbbbb0c18",
    "b60e45937954ce9479e70dd3b0f59f3623ae0f97f9b3736d3a03b0636b950383",
    "b6f8d434a847fb0f0c1a8d9b936b8ca952e224f205a55f4ba9b2c20f88fdc9e7",
    "bb52a41f57a38eb8c757ea7125f3d578cc8ea4659554a2128fa88f739c79c530",
    "bb7aa507ee307613a18d2b1eabb42e76a5e3ff8a00d021b738f6a5a8f299ed29",
    "bcd85161840ba377c8fea4a09ffb6bb3b1e41b3c6160ce6290507b1be58959af",
    "bce88734ea752a4258313a93910d68a0004a91f8a1747a6e17747f234e64045c",
    "bd3f375fb2be40eebd2a1dcfe193841915534a73176057289b141c3791e1fae8",
    "bff7a4bf43f6485120cc28615f1fbcd9823d6225f68ef2b1169dce2a0af507cb",
    "c2496fba35bb28b63d17fac6e90697b6a50ccfc7e53a4a82dbf392893613d523",
    "c2cc5bf2f2c619bc710989333c25b9814b0cf579eb0db2becd220104ff304f8e",
    "c44096356d260c8f7b034d5270ebb06143ab1b4433b70d2f2e96f0cf81bd8985",
    "c447c92918451908bc0b1eac9173f9124686e896fae7346aaaadcbaa8c4c9ba0",
    "c9f4e771fdbb19737d4dd0b777201cdd8f50d751dfabcd308cc004c89cd36fea",
    "d22a4de8872034ae54f648c3f86b815534e65b1a596a79e3e5b421c48259021b",
    "d7a727460641d8be3a3eed5312684ea2e2e9d59263c9a6d88f85a45666fd63fb",
    "d821aa45735a020c5b152a076ac5c8fd294d8ffcc0a8199adc9c2fbbfa67a496",
    "dd0036093d88b63f7f2b98670151250f17f920f4600cf71d7b2de386a3919efb",
    "e02fb2af41f4d1a4a0346333579dacb0683b3b07a5648fcf6513cdc8a56e8d7f",
    "e158b55e31ea45aa621753c5d2b3863efe120c535920d290c51dcf2286733bba",
    "e580c294a82d6ca4cd806fa801c14b8c6f9c512ed46e2c5d12cac33e82d8ed34",
    "e69110e7cfc808620b8ca5ac378dc9716ab258d0de511c2f16a318fde01b70c5",
    "ead44efdc0755a3081535de137634fedd88220b3752435a54ac52d6457f48b71",
    "eed96ac4550563f66e43474bac8a7eb670a83c460305298b203ff7d9aeecd2aa",
    "f1c45b88340d12a2dfcdee7a159f8c56ad83328695dfe90d0ddacff9a5a97117",
    "f297afed2f39488186e2972b0cb4b064fd9e6f1d7fee07fa4900149e4d5f6af9",
    "f44d8e28f433f0f4b1a4c3603a25ef86f1c3d34636e31a95c1260455a5dcfacb",
    "f58a121b3a0b5dacf9a5c0d1b7be93882e292331662876da0489c396c6820361",
    "f5f9cc117d31860bb16e7e40f3c9807593865bf4046d882b63d49f069fb0fa7f",
    "f6b94f9d48a177b72ee9759682f5a0ca04e7836531ccba8733438a947bc0fc8e",
    "f8f999bff883cc21d08a7d0d38b7b2108db73ddb9772a7676813adfa8b3043d9",
    "f968dff66e3574901c890cd11323e19eb42287b85fec7cf8ef914f0cad548177",
    "fc311d6059bd43a91be811b9d2c5883c48237fd0ec128154631d523b9229dd96",
    "fdb4f454aa686ff46dcfbe553d82272715547ffff8ee220cf5efcb36f2c11961",
    "fe48a6ec3d1c9015a5b44a11136270306d9e65b98646209b9f2052ea13170740",
})


def test_knowledge_file_lists_the_eleven_areas_and_their_teams():
    body = _read(KNOWLEDGE_80)
    areas = re.findall(r"^### .+ \((D[A-Z])\)$", body, re.M)
    assert areas == list(SKILL_AREA_CODES)
    sections = {}
    for match in re.finditer(r"^### .+ \((D[A-Z])\)$", body, re.M):
        end = re.compile(r"^##", re.M).search(body, match.end())
        sections[match.group(1)] = body[match.end():end.start() if end else len(body)]
    for team in TEAM_CODES:
        assert team[:2] in sections, team
        assert f"({team})" in sections[team[:2]], team
    assert "## Mapping rules" in body
    for old in ("DD-D", "DD-S", "DM-V", "DM-I"):
        assert old not in body


def test_knowledge_file_names_no_people():
    body = _read(KNOWLEDGE_80)
    for word in re.findall(r"[A-Za-zÄÖÜäöüß-]+", body):
        digest = hashlib.sha256(word.lower().encode()).hexdigest()
        assert digest not in PEOPLE_IN_ANNOUNCEMENTS_SHA256, word


def test_skill_sources_use_crlf_line_endings():
    """The skill's Python, Markdown and prompt files are CRLF (the plugin's
    Windows convention); a file saved with LF would show up as a whole-file
    diff on the next Windows edit."""
    from pathlib import Path
    skill = Path(SKILL_ROOT)
    offenders = []
    for path in sorted(skill.rglob("*")):
        if path.suffix not in (".py", ".md") or "__pycache__" in path.parts:
            continue
        data = path.read_bytes()
        if data.count(b"\n") != data.count(b"\r\n"):
            offenders.append(str(path.relative_to(skill)))
    assert offenders == []


def test_skill_interaction_contract_reads_as_one_sentence_per_rule():
    text = open(os.path.join(SKILL_ROOT, "SKILL.md"), encoding="utf-8").read()
    assert "confirmation. This Apart" not in " ".join(text.split())
