"""Copy RFQ documents attached in chat into a named folder under the RFQ root.

The skill asks once for a folder name; `run` then copies the files into
`<root>/<name>` so the normal analysis can run on that folder. No model
worker is involved.
"""

import os
import re
import shutil
from typing import Mapping

from rfq.delivery import safe_filename

OUTPUT_DIR = "output"
ROOT_ENV = "RFQ_INSIGHT_ROOT"


def resolve_root(root=None, env: Mapping = os.environ) -> str:
    """The RFQ root: `root`, else $RFQ_INSIGHT_ROOT, else ~/RFQs; created."""
    chosen = root or env.get(ROOT_ENV) or os.path.join("~", "RFQs")
    path = os.path.abspath(os.path.expanduser(str(chosen)))
    os.makedirs(path, exist_ok=True)
    return path


def folder_name(name: str) -> str:
    """A single safe folder name: no separators, no `..`, no leading dots,
    spaces turned into underscores."""
    text = str(name or "").replace("..", "").replace("/", "").replace("\\", "")
    text = text.strip().lstrip(".").strip()
    if not text.rstrip(". "):
        raise ValueError("The folder name is empty after cleaning.")
    cleaned = re.sub(r"\s+", "_", safe_filename(text)).lstrip(".")
    if not cleaned:
        raise ValueError("The folder name is empty after cleaning.")
    return cleaned


def _free_path(folder: str, name: str) -> str:
    stem, ext = os.path.splitext(name)
    path = os.path.join(folder, name)
    n = 2
    while os.path.lexists(path):
        path = os.path.join(folder, f"{stem}_{n}{ext}")
        n += 1
    return path


def _copy_in(folder: str, sources) -> list:
    copied = []
    for src in sources:
        dest = _free_path(folder, os.path.basename(os.path.normpath(src)))
        if os.path.isdir(src):
            shutil.copytree(src, dest)
        else:
            shutil.copy2(src, dest)
        copied.append(os.path.basename(dest))
    return copied


def _listing(folder: str) -> list:
    return sorted(n for n in os.listdir(folder) if n != OUTPUT_DIR)


def run(root, name, files, mode=None) -> dict:
    base = resolve_root(root)
    target = os.path.join(base, folder_name(name))
    if os.path.commonpath([base, os.path.abspath(target)]) != base \
            or os.path.abspath(target) == base:
        raise ValueError("The folder must be inside the RFQ root.")
    for path in files:
        if not os.path.exists(path):
            return {"status": "blocked", "message": f"Cannot find {path}."}
    exists = os.path.isdir(target)
    if exists and mode is None:
        return {"status": "exists", "folder": target, "files": _listing(target)}
    if exists and mode == "replace":
        for entry in os.listdir(target):
            full = os.path.join(target, entry)
            if os.path.isdir(full) and not os.path.islink(full):
                shutil.rmtree(full)
            else:
                os.remove(full)
    os.makedirs(target, exist_ok=True)
    return {"status": "done", "folder": target,
            "copied": _copy_in(target, files)}
