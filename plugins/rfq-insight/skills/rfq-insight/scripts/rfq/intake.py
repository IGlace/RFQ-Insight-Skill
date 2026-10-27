"""Copy RFQ documents attached in chat into a named folder under the RFQ root.

The skill asks once for a folder name; `run` then copies the files into
`<root>/<name>` so the normal analysis can run on that folder. No model
worker is involved.
"""

import os
import shutil
import tempfile
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
    """A single safe folder name: no separators, no `..`, no leading dots;
    spaces are kept and only what delivery.safe_filename removes is
    dropped."""
    text = str(name or "").replace("..", "").replace("/", "").replace("\\", "")
    text = text.strip().lstrip(".").strip()
    if not text.rstrip(". "):
        raise ValueError("The folder name is empty after cleaning.")
    cleaned = safe_filename(text).lstrip(".")
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
    """Copy each source into `folder`; raises OSError naming the source."""
    copied = []
    for src in sources:
        dest = _free_path(folder, os.path.basename(os.path.normpath(src)))
        try:
            if os.path.isdir(src):
                shutil.copytree(src, dest)
            else:
                shutil.copy2(src, dest)
        except OSError as exc:
            raise _CopyError(src, exc) from exc
        copied.append(os.path.basename(dest))
    return copied


class _CopyError(Exception):
    def __init__(self, src, exc):
        super().__init__(f"Could not copy {os.path.basename(os.path.normpath(src))}: {exc}.")


def _blocked(message: str) -> dict:
    return {"status": "blocked", "message": message}


def _inside(path: str, folder: str) -> bool:
    """True when `path` is `folder` or lies within it (real paths)."""
    path, folder = os.path.realpath(path), os.path.realpath(folder)
    try:
        return os.path.commonpath([path, folder]) == folder
    except ValueError:
        return False


def _clear(folder: str) -> None:
    for entry in os.listdir(folder):
        full = os.path.join(folder, entry)
        if os.path.isdir(full) and not os.path.islink(full):
            shutil.rmtree(full)
        else:
            os.remove(full)


def _replace(base: str, target: str, files) -> dict:
    """Stage the copies beside the target first, so a failed copy leaves the
    old folder as it was; only then swap the contents."""
    staging = tempfile.mkdtemp(dir=base, prefix=".intake-")
    try:
        staged = _copy_in(staging, files)
        _clear(target)
        for entry in staged:
            shutil.move(os.path.join(staging, entry), os.path.join(target, entry))
    except (_CopyError, OSError) as exc:
        return _blocked(str(exc) if isinstance(exc, _CopyError)
                        else f"Could not replace {target}: {exc}.")
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return {"status": "done", "folder": target, "copied": staged}


def _listing(folder: str) -> list:
    return sorted(n for n in os.listdir(folder) if n != OUTPUT_DIR)


def run(root, name, files, mode=None) -> dict:
    base = resolve_root(root)
    target = os.path.join(base, folder_name(name))
    if os.path.islink(target):
        return _blocked(f"{target} is a link and cannot be used as an RFQ folder.")
    real_base = os.path.realpath(base)
    real_target = os.path.realpath(target)
    if real_target == real_base or not _inside(real_target, real_base):
        raise ValueError("The folder must be inside the RFQ root.")
    for path in files:
        if not os.path.exists(path):
            return _blocked(f"Cannot find {path}.")
    if os.path.lexists(target) and not os.path.isdir(target):
        return _blocked(f"{target} exists and is not a folder.")
    exists = os.path.isdir(target)
    if exists and mode is None:
        return {"status": "exists", "folder": target, "files": _listing(target)}
    if exists and mode == "replace":
        if any(_inside(path, target) for path in files):
            return _blocked(f"Cannot replace {target} with files that are inside it.")
        return _replace(base, target, files)
    os.makedirs(target, exist_ok=True)
    try:
        return {"status": "done", "folder": target,
                "copied": _copy_in(target, files)}
    except _CopyError as exc:
        if not exists:
            shutil.rmtree(target, ignore_errors=True)
        return _blocked(str(exc))
