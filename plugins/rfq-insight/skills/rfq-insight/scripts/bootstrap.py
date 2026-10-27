#!/usr/bin/env python3
"""Provision the skill's document toolbox, or report that it is ready.

Everything the skill needs (python-pptx, Pillow, pydantic, python-docx,
openpyxl, pdfplumber) is installed into an isolated virtual environment under
the user's home directory:

    ~/.rfq-insight/venv

Not inside the plugin folder: an installed plugin is read-only, its path
changes on every update, and a re-install must not wipe a working toolbox.
When the virtual environment cannot be created or populated (no package-index
access, no `venv` module), the system interpreter is accepted as a fallback
provided it can already import every required library. Set RFQ_INSIGHT_HOME
to move the toolbox elsewhere. A stamp file records the hash of requirements.txt, so a
skill update that changes the dependency list re-provisions automatically
and an unchanged one costs a file read.

    python bootstrap.py --check      exit 0 and print the interpreter path if
                                     the toolbox is ready; exit 3 if not
    python bootstrap.py              create/refresh it, print the path
    python bootstrap.py --versions   print the installed versions as JSON

Every other script in this skill is run with the interpreter this prints.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys

# RFQ_INSIGHT_HOME relocates the toolbox, e.g. into a sandbox's writable
# root when the home directory is off limits.
HOME_DIR = os.environ.get("RFQ_INSIGHT_HOME") or os.path.join(os.path.expanduser("~"), ".rfq-insight")
VENV_DIR = os.path.join(HOME_DIR, "venv")
STAMP_NAME = ".requirements-sha256"
REQUIREMENTS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "requirements.txt")

EXIT_OK = 0
EXIT_NOT_READY = 3
EXIT_FAILED = 4

# Generous: six packages including Pillow over a slow corporate link is
# minutes, not seconds. It exists only so a stalled connection surfaces a
# message instead of hanging silently forever.
INSTALL_TIMEOUT = 900

# Substrings that mean "this machine could not reach the package index",
# which is the one bootstrap failure the user can actually act on.
#
# Deliberately NARROW: every entry describes a transport failure. Resolution
# failures ("could not find a version that satisfies", "no matching
# distribution") are NOT here, because they are far more often a bad pin, a
# yanked release or a wheel missing for this platform than a blocked network
# — and telling a salesperson to call IT about network access when the real
# fault is requirements.txt sends two people down the wrong path.
_NETWORK_SIGNS = ("proxyerror", "connection broken", "network is unreachable",
                  "temporary failure in name resolution", "ssl", "timed out",
                  "retries exceeded", "failed to establish a new connection")


def interpreter(venv_dir: str = VENV_DIR) -> str:
    """Path to the toolbox interpreter (not necessarily existing yet)."""
    if os.name == "nt":
        return os.path.join(venv_dir, "Scripts", "python.exe")
    return os.path.join(venv_dir, "bin", "python")


def requirements_digest(req: str = REQUIREMENTS) -> str:
    """Hash the dependency LIST, not the bytes it happens to be stored in.

    Line endings are normalized first. Git rewrites them on checkout when
    core.autocrlf is on — the Windows default — so without this the same
    unchanged requirements file hashes differently after a branch switch or
    a fresh clone, the stamp stops matching, and a working toolbox is
    discarded for a multi-minute reinstall that changes nothing. Worse, it
    fails outright when the machine happens to be offline at that moment.
    """
    with open(req, "rb") as fh:
        content = fh.read().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(content).hexdigest()


def is_ready(venv_dir: str = VENV_DIR, req: str = REQUIREMENTS) -> bool:
    """True when the toolbox exists AND matches the current requirements."""
    stamp = os.path.join(venv_dir, STAMP_NAME)
    if not os.path.exists(interpreter(venv_dir)) or not os.path.exists(stamp):
        return False
    with open(stamp, encoding="utf-8") as fh:
        return fh.read().strip() == requirements_digest(req)


def explain_pip_failure(output: str) -> str:
    """Turn installer output into one sentence the user can act on."""
    low = (output or "").lower()
    if any(sign in low for sign in _NETWORK_SIGNS):
        return ("I couldn't set up the tools I need because this machine "
                "can't reach the software library it downloads them from - "
                "that's usually a network or proxy restriction. Ask IT to "
                "allow access to pypi.org, then try again.")
    return ("I couldn't set up the tools I need. The technical detail is in "
            "the message below; IT will be able to read it.")


def installed_versions(python: str) -> dict:
    """Read installed metadata without requiring pip in the selected runtime."""
    code = (
        "import json; from importlib.metadata import distributions; "
        "print(json.dumps({d.metadata['Name']: d.version for d in distributions() "
        "if d.metadata['Name']}))"
    )
    try:
        proc = subprocess.run([python, "-c", code],
                              capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            return {}
        versions = json.loads(proc.stdout)
        if isinstance(versions, dict):
            return versions
    except Exception:
        pass
    return {}


# Import names of every requirement, checked in a subprocess so a broken
# library cannot take this script down with it.
REQUIRED_IMPORTS = ("pptx", "PIL", "pydantic", "docx", "openpyxl", "pdfplumber",
                    "extract_msg")


def system_interpreter_ready(python: str = sys.executable) -> bool:
    """True when `python` can already import every library the skill needs."""
    code = "import " + ", ".join(REQUIRED_IMPORTS)
    try:
        proc = subprocess.run([python, "-c", code], capture_output=True,
                              text=True, timeout=120)
    except Exception:
        return False
    return proc.returncode == 0


def provision(venv_dir: str = VENV_DIR, req: str = REQUIREMENTS) -> str:
    """Create the toolbox and install requirements. Returns the interpreter
    path. Raises RuntimeError whose message is safe to show the user."""
    import venv

    os.makedirs(os.path.dirname(venv_dir) or ".", exist_ok=True)
    try:
        venv.EnvBuilder(with_pip=True, clear=False).create(venv_dir)
    except Exception as exc:
        raise RuntimeError(
            "I couldn't create the private folder where I keep my tools "
            f"({venv_dir}). Check you have permission to write there."
        ) from exc

    python = interpreter(venv_dir)
    try:
        proc = subprocess.run(
            [python, "-m", "pip", "install", "--disable-pip-version-check",
             "--quiet", "-r", req],
            capture_output=True, text=True, timeout=INSTALL_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        # A stalled connection must not hang forever: with no message at all,
        # a non-technical user has nothing to act on and nothing to report.
        raise RuntimeError(
            "Setting up the tools I need took too long and I stopped "
            "waiting. That usually means the connection stalled part way "
            "through. Try again, and if it keeps happening ask IT whether "
            "downloads are being filtered.") from exc
    if proc.returncode != 0:
        detail = ((proc.stderr or "") + (proc.stdout or "")).strip()
        tail = "\n".join(detail.splitlines()[-8:])
        raise RuntimeError(f"{explain_pip_failure(detail)}\n\n{tail}")

    with open(os.path.join(venv_dir, STAMP_NAME), "w", encoding="utf-8") as fh:
        fh.write(requirements_digest(req))
    return python


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="report readiness without changing anything")
    ap.add_argument("--versions", action="store_true",
                    help="print installed package versions as JSON")
    args = ap.parse_args()

    if args.check:
        if is_ready():
            print(interpreter())
            sys.exit(EXIT_OK)
        if system_interpreter_ready():
            print(sys.executable)
            sys.exit(EXIT_OK)
        print("The tools I need aren't set up on this machine yet.",
              file=sys.stderr)
        sys.exit(EXIT_NOT_READY)

    if args.versions:
        print(json.dumps(installed_versions(interpreter()), indent=2))
        sys.exit(EXIT_OK)

    try:
        python = provision()
    except RuntimeError as exc:
        # A sandbox without package-index access may still carry the
        # libraries on its own interpreter; that beats refusing to run.
        if system_interpreter_ready():
            print(sys.executable)
            sys.exit(EXIT_OK)
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_FAILED)
    print(python)
    sys.exit(EXIT_OK)


if __name__ == "__main__":
    main()
