#!/usr/bin/env python3
"""Approval hook: approve the plugin's own tool calls, nothing else.

Claude Code (and the Code experience in Claude Desktop) asks the user before
each shell command and file write unless a rule allows it; Codex asks when a
command needs to leave its sandbox (the toolbox venv in the home directory,
the package download). Both hosts load this plugin's `hooks/hooks.json` and
send the same JSON on stdin. For `PreToolUse` (Claude) the hook pre-approves
the call; for `PermissionRequest` (Codex, once the user has trusted the
plugin's hooks) it approves the escalation. Either way the decision is given
only when the call is one the RFQ Insight skill makes by design:

  * a shell command that runs one Python interpreter on one of the skill's two
    entry points (`bootstrap.py`, `rfq_run.py`) inside this plugin's
    `skills/rfq-insight/scripts/` folder, optionally redirecting its output
    into an RFQ folder's `output/.work/` directory - except an `intake` that
    replaces a folder (`--mode replace`) or names its own root (`--root`):
    the first deletes what the folder holds and the second points the copy
    anywhere, so both get the normal prompt;
  * `mkdir` of a directory under `output/.work/`;
  * a Write or Edit of a file under `output/.work/` (in Codex an
    `apply_patch` whose every touched file is under `output/.work/`).

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

SCRIPTS = {"bootstrap.py", "rfq_run.py"}
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


def _option(token, name):
    """`token` is `name` or an abbreviation argparse accepts for it
    (`--ro` for `--root`), with or without `=value`."""
    opt = token.split("=", 1)[0]
    return len(opt) >= 3 and name.startswith(opt)


def _intake_allowed(args):
    """An `intake` invocation (the arguments after the subcommand) is
    approved only on the default root and in `new` or `add` mode."""
    i = 0
    while i < len(args):
        tok = args[i]
        if tok == "--":
            return True
        if not tok.startswith("--"):
            i += 1
            continue
        has_value = "=" in tok
        value = tok.split("=", 1)[1] if has_value else (
            args[i + 1] if i + 1 < len(args) else "")
        if _option(tok, "--root"):
            return False
        if _option(tok, "--mode"):
            if value != "add":
                return False
        elif not _option(tok, "--name"):
            return False                 # an option this hook does not know
        i += 1 if has_value else 2
    return True


def _script_allowed(args):
    """The arguments after an approved entry point."""
    if args and args[0] == "intake":
        return _intake_allowed(args[1:])
    return True


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
        return _script_allowed(tokens[2:])
    if (len(tokens) >= 3 and _is_interpreter(tokens[0]) and tokens[1] == "-B"
            and _is_plugin_script(tokens[2])):
        return _script_allowed(tokens[3:])
    return False


def file_write_allowed(path):
    return bool(path) and _in_work_dir(_norm(path))


PATCH_FILE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", re.M)
PATCH_MOVE = re.compile(r"^\*\*\* Move to: (.+)$", re.M)


def patch_allowed(patch):
    """Codex edits files through apply_patch; approve only when every file
    the patch names lives under output/.work/."""
    if not isinstance(patch, str) or not patch.strip():
        return False
    paths = PATCH_FILE.findall(patch) + PATCH_MOVE.findall(patch)
    return bool(paths) and all(file_write_allowed(p.strip()) for p in paths)


def command_text(value):
    """Bash input as one string. Codex may send argv; a `sh -c <script>`
    wrapper is unwrapped, anything else is quoted back into one line."""
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        if (len(value) == 3 and _basename(value[0]) in ("sh", "bash", "zsh", "dash")
                and value[1] in ("-c", "-lc")):
            return value[2]
        return " ".join(shlex.quote(v) for v in value)
    return ""


def decide(payload):
    tool = payload.get("tool_name", "")
    inputs = payload.get("tool_input") or {}
    if not isinstance(inputs, dict):
        return False
    if tool == "Bash":
        return shell_command_allowed(command_text(inputs.get("command", "")))
    if tool in ("Write", "Edit", "MultiEdit"):
        return file_write_allowed(inputs.get("file_path", ""))
    if tool == "apply_patch":
        return patch_allowed(inputs.get("command", ""))
    return False


def decision(payload):
    """The JSON to print, or None to leave the host's normal flow alone."""
    if not decide(payload):
        return None
    reason = "RFQ Insight plugin script or checkpoint"
    if payload.get("hook_event_name") == "PermissionRequest":
        return {"hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": "allow"},
            "systemMessage": reason,
        }}
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "permissionDecisionReason": reason,
    }}


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    verdict = decision(payload)
    if verdict is not None:
        print(json.dumps(verdict))
    return 0


if __name__ == "__main__":
    sys.exit(main())
