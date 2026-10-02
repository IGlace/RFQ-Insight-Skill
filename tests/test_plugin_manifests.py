"""The plugin and marketplace manifests agree with each other and the skill."""

import json
import os
import re

from conftest import REPO_ROOT, SKILL_ROOT

PLUGIN = os.path.join(REPO_ROOT, "plugins", "rfq-insight")


def _load(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as fh:
        return json.load(fh)


def test_claude_plugin_manifest_is_complete():
    manifest = _load(PLUGIN, ".claude-plugin", "plugin.json")
    assert manifest["name"] == "rfq-insight"
    assert re.fullmatch(r"\d+\.\d+\.\d+", manifest["version"])
    assert manifest["description"]
    assert manifest["author"]["name"]


def test_codex_plugin_manifest_matches_claude_manifest():
    claude = _load(PLUGIN, ".claude-plugin", "plugin.json")
    codex = _load(PLUGIN, ".codex-plugin", "plugin.json")
    assert codex["name"] == claude["name"]
    assert codex["version"] == claude["version"]
    assert codex["description"] == claude["description"]
    assert codex["skills"] == "./skills/"
    assert codex["interface"]["displayName"] == "RFQ Insight"
    assert any("$rfq-insight" in p for p in codex["interface"]["defaultPrompt"])
    assert os.path.isdir(os.path.join(PLUGIN, "skills"))


def test_marketplaces_point_at_the_plugin_folder():
    claude = _load(REPO_ROOT, ".claude-plugin", "marketplace.json")
    codex = _load(REPO_ROOT, ".agents", "plugins", "marketplace.json")
    plugin = _load(PLUGIN, ".claude-plugin", "plugin.json")
    for marketplace in (claude, codex):
        assert marketplace["name"] == "rfq-insight"
        assert [p["name"] for p in marketplace["plugins"]] == ["rfq-insight"]
    assert claude["plugins"][0]["source"] == "./plugins/rfq-insight"
    assert claude["plugins"][0]["version"] == plugin["version"]
    assert claude["metadata"]["version"] == plugin["version"]
    assert codex["plugins"][0]["source"] == {"source": "local", "path": "./plugins/rfq-insight"}
    assert os.path.isfile(os.path.join(SKILL_ROOT, "SKILL.md"))


def test_skill_frontmatter_names_the_skill():
    with open(os.path.join(SKILL_ROOT, "SKILL.md"), encoding="utf-8") as fh:
        head = fh.read().split("---")[1]
    assert re.search(r"^name:\s*rfq-insight\s*$", head, re.M)
    assert "description:" in head


def test_codex_skill_metadata_mentions_the_skill_name():
    with open(os.path.join(SKILL_ROOT, "agents", "openai.yaml"), encoding="utf-8") as fh:
        body = fh.read()
    assert "$rfq-insight" in body
    assert 'display_name: "RFQ Insight"' in body


def test_plugin_ships_no_runtime_state_and_archive_skips_caches():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "package_plugin", os.path.join(REPO_ROOT, "tools", "package_plugin.py"))
    packager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(packager)
    names = [relative.as_posix() for _, relative in packager.plugin_files()]
    assert ".claude-plugin/plugin.json" in names
    assert ".codex-plugin/plugin.json" in names
    assert "skills/rfq-insight/SKILL.md" in names
    assert not any("__pycache__" in n or n.endswith(".pyc") or n.endswith("runtime.json")
                   for n in names)
