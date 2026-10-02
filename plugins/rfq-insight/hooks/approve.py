#!/usr/bin/env python3
"""PreToolUse hook: approve the plugin's own tool calls, nothing else.

Claude Code (and the Code experience in Claude Desktop) asks the user before
each shell command and file write unless a rule allows it. This hook reads the
pending tool call from stdin and prints an "allow" decision when the call is
one the RFQ Insight skill makes by design:

  * a shell command that runs one Python interpreter on one script inside this
    plugin's `skills/rfq-insight/scripts/` folder, optionally redirecting its
    output into an RFQ folder's `output/.work/` directory;
  * `mkdir` of a directory under `output/.work/`;
  * a Write or Edit of a file under `output/.work/`.

Anything else prints nothing, so the host's normal permission flow applies.
Chained or piped commands are never approved even when they mention the
plugin, so a prompt-injected command cannot ride on the plugin's trust.
Cowork does not run hooks and needs none: it grants folder access once.
"""

import json
import os
import re
import shlex
import sys

SCRIPTS = {
    "bootstrap.py", "workflow_state.py", "extract_corpus.py", "merge_image_text.py",
    "corpus_text.py", "stage_request.py", "record_execution.py", "validate.py",
    "extract_claims.py", "apply_verdicts.py", "plan_input.py", "finalize.py",
    "evaluate.py", "render_run.py",
}
INTERPRETERS = {"python", "python3", "py", "python.exe", "python3.exe"}
WORK_DIR = re.compile(r"[\\/]output[\\/]\.work([\\/]|$)")
PLUGIN_SCRIPTS = re.compile(r"[\\/]skills[\\/]rfq-insight[\\/]scripts[\\/]")
FORBIDDEN = re.compile(r"[;|&`]|\$\(|\n")


def _norm(path):
    return os.path.normcase(os.path.normpath(path))


def _basename(token):
    """Last path component on either separator; the hook may run on Linux
    while judging a Windows path, where os.path.basename would not split."""
    return re.split(r"[\\/]", token)[-1]


def _is_interpreter(token):
    base = _basename(token.strip('"\'')).lower()
    if base in INTERPRETERS:
        return True
    # The bootstrap toolbox: ~/.rfq-insight/venv/{bin/python,Scripts/python.exe}
    return bool(re.search(r"[\\/]\.rfq-insight[\\/]venv[\\/](bin[\\/]python3?|Scripts[\\/]python(3)?\.exe)$",
                          token.strip('"\''), re.I))


def _is_plugin_script(token):
    token = token.strip('"\'')
    if ".." in re.split(r"[\\/]", token):
        return False
    return bool(PLUGIN_SCRIPTS.search(token)) and _basename(token) in SCRIPTS


def _in_work_dir(token):
    return bool(WORK_DIR.search(token.strip('"\'')))


def shell_command_allowed(command):
    if not command:
        return False
    text = command.strip()
    if text.startswith("&"):          # PowerShell call operator for a quoted path
        text = text[1:].lstrip()
    text = text.replace("2>&1", " ")  # the one '&' a stderr merge needs
    if FORBIDDEN.search(text):
        return False
    try:
        argv = shlex.split(text, posix=True)
    except ValueError:
        return False
    if not argv:
        return False
    # Strip output redirections; they may only target the work directory.
    tokens, i = [], 0
    while i < len(argv):
        tok = argv[i]
        if tok in (">", ">>", "2>", "2>>"):
            if i + 1 >= len(argv) or not _in_work_dir(argv[i + 1]):
                return False
            i += 2
            continue
        if re.fullmatch(r"(2?>>?)(.+)", tok):
            target = re.fullmatch(r"(2?>>?)(.+)", tok).group(2)
            if not _in_work_dir(target):
                return False
            i += 1
            continue
        tokens.append(tok)
        i += 1
    if tokens[0] in ("mkdir", "mkdir.exe"):
        rest = [t for t in tokens[1:] if not t.startswith("-")]
        return bool(rest) and all(_in_work_dir(t) for t in rest)
    if len(tokens) >= 2 and _is_interpreter(tokens[0]) and _is_plugin_script(tokens[1]):
        return True
    if (len(tokens) >= 3 and _is_interpreter(tokens[0]) and tokens[1] == "-B"
            and _is_plugin_script(tokens[2])):
        return True
    return False


def file_write_allowed(path):
    return bool(path) and _in_work_dir(_norm(path))


def decide(payload):
    tool = payload.get("tool_name", "")
    inputs = payload.get("tool_input") or {}
    if tool == "Bash":
        return shell_command_allowed(inputs.get("command", ""))
    if tool in ("Write", "Edit", "MultiEdit"):
        return file_write_allowed(inputs.get("file_path", ""))
    return False


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if decide(payload):
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": "RFQ Insight plugin script or checkpoint",
        }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
