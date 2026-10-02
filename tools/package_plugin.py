#!/usr/bin/env python3
"""Zip the plugin for hosts that install plugins from an archive.

    python tools/package_plugin.py            -> dist/rfq-insight-plugin.zip
    python tools/package_plugin.py --out X.zip

Claude Desktop (Cowork) accepts a plugin uploaded as a .zip whose root holds
`.claude-plugin/plugin.json`. Marketplace installs (Claude Code, Codex) read
this repository directly and do not need the archive. Nothing is installed.
"""

import argparse
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "rfq-insight"
SKIP_PARTS = {"__pycache__", ".pytest_cache"}
SKIP_SUFFIXES = {".pyc", ".pyo"}


def plugin_files():
    for path in sorted(PLUGIN.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(PLUGIN)
        if SKIP_PARTS.intersection(relative.parts) or path.suffix in SKIP_SUFFIXES:
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(PLUGIN.resolve()):
            raise ValueError(f"Plugin files must stay within the plugin folder: {path}")
        yield path, relative


def build(out: Path) -> Path:
    out = out.resolve()
    if out.exists():
        raise ValueError(f"Refusing to overwrite an existing archive: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "x", zipfile.ZIP_DEFLATED) as archive:
        for path, relative in plugin_files():
            info = zipfile.ZipInfo(relative.as_posix(), (2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / "rfq-insight-plugin.zip")
    args = parser.parse_args(argv)
    try:
        out = build(args.out)
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
