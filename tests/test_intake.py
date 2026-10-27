import json
import os
import shutil
import subprocess
import sys

import pytest

from conftest import SCRIPTS
from rfq import intake


def _src(tmp_path, name, body=b"x"):
    p = tmp_path / "src" / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(body); return str(p)


def test_root_resolution_order(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path)); monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert intake.resolve_root(str(tmp_path / "a"), {"RFQ_INSIGHT_ROOT": str(tmp_path / "b")}) == str(tmp_path / "a")
    assert intake.resolve_root(None, {"RFQ_INSIGHT_ROOT": str(tmp_path / "b")}) == str(tmp_path / "b")
    assert os.path.isdir(tmp_path / "b")
    assert intake.resolve_root(None, {}) == str(tmp_path / "RFQs")


def test_folder_name_stays_inside_the_root():
    assert intake.folder_name("Acme V6") == "Acme V6"
    assert intake.folder_name("  Acme   V6 / pack ") == "Acme V6 pack"
    assert intake.folder_name("../../etc") == "etc"
    with pytest.raises(ValueError):
        intake.folder_name("..")


def test_new_folder_copies_files(tmp_path):
    out = intake.run(str(tmp_path / "root"), "Acme V6", [_src(tmp_path, "sow.pdf"), _src(tmp_path, "sub/app.xlsx")])
    assert out["status"] == "done" and out["folder"] == str(tmp_path / "root" / "Acme V6")
    assert sorted(os.listdir(out["folder"])) == ["app.xlsx", "sow.pdf"]


def test_existing_folder_reports_then_adds_or_replaces(tmp_path):
    root = str(tmp_path / "root"); f = _src(tmp_path, "sow.pdf")
    intake.run(root, "Acme", [f]); os.makedirs(tmp_path / "root" / "Acme" / "output")
    out = intake.run(root, "Acme", [f])
    assert out["status"] == "exists" and out["files"] == ["sow.pdf"]
    out = intake.run(root, "Acme", [f], mode="add")
    assert sorted(os.listdir(out["folder"])) == ["output", "sow.pdf", "sow_2.pdf"]
    out = intake.run(root, "Acme", [f], mode="replace")
    assert sorted(os.listdir(out["folder"])) == ["sow.pdf"]


def test_missing_source_is_blocked(tmp_path):
    out = intake.run(str(tmp_path), "Acme", [str(tmp_path / "nope.pdf")])
    assert out["status"] == "blocked" and "nope.pdf" in out["message"]


def test_directory_source_is_copied_recursively(tmp_path):
    _src(tmp_path, "pack/a.txt"); _src(tmp_path, "pack/deep/b.txt")
    out = intake.run(str(tmp_path / "root"), "Acme", [str(tmp_path / "src" / "pack")])
    assert out["status"] == "done"
    assert os.path.isfile(os.path.join(out["folder"], "pack", "deep", "b.txt"))


def test_blocked_source_leaves_an_existing_folder_untouched(tmp_path):
    root = str(tmp_path / "root"); f = _src(tmp_path, "sow.pdf")
    intake.run(root, "Acme", [f])
    out = intake.run(root, "Acme", [f, str(tmp_path / "nope.pdf")], mode="replace")
    assert out["status"] == "blocked"
    assert os.listdir(tmp_path / "root" / "Acme") == ["sow.pdf"]


def test_cli_intake_prints_json(tmp_path):
    f = _src(tmp_path, "sow.pdf")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    result = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, "rfq_run.py"), "intake",
         "--root", str(tmp_path / "root"), "--name", "Acme V6", f],
        cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    out = json.loads(result.stdout)
    assert out["status"] == "done" and out["copied"] == ["sow.pdf"]
    assert os.path.isfile(tmp_path / "root" / "Acme V6" / "sow.pdf")


def test_symlinked_target_is_blocked_and_outside_data_survives(tmp_path):
    root = tmp_path / "root"; root.mkdir()
    outside = tmp_path / "outside"; outside.mkdir(); (outside / "keep.txt").write_text("k")
    os.symlink(outside, root / "Link", target_is_directory=True)
    f = _src(tmp_path, "sow.pdf")
    for mode in (None, "add", "replace"):
        out = intake.run(str(root), "Link", [f], mode=mode)
        assert out["status"] == "blocked" and "link" in out["message"]
    assert os.listdir(outside) == ["keep.txt"]


def test_replace_with_a_source_inside_the_target_is_blocked(tmp_path):
    root = str(tmp_path / "root")
    intake.run(root, "S", [_src(tmp_path, "a.txt")])
    inside = str(tmp_path / "root" / "S" / "a.txt")
    out = intake.run(root, "S", [inside], mode="replace")
    assert out["status"] == "blocked" and "inside it" in out["message"]
    assert os.listdir(tmp_path / "root" / "S") == ["a.txt"]


def test_failed_copy_keeps_the_previous_replace_contents(tmp_path, monkeypatch):
    root = str(tmp_path / "root")
    intake.run(root, "Acme", [_src(tmp_path, "old.pdf", b"old")])
    os.makedirs(tmp_path / "root" / "Acme" / "output")
    new = _src(tmp_path, "new.pdf")

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(shutil, "copy2", boom)
    out = intake.run(root, "Acme", [new], mode="replace")
    assert out["status"] == "blocked" and out["message"].startswith("Could not copy new.pdf")
    assert sorted(os.listdir(tmp_path / "root" / "Acme")) == ["old.pdf", "output"]
    assert not [n for n in os.listdir(root) if n.startswith(".intake-")]


def test_failed_copy_in_add_and_new_modes_is_blocked(tmp_path, monkeypatch):
    root = str(tmp_path / "root"); f = _src(tmp_path, "sow.pdf")
    monkeypatch.setattr(shutil, "copy2", lambda *a, **k: (_ for _ in ()).throw(OSError("denied")))
    out = intake.run(root, "Fresh", [f])
    assert out["status"] == "blocked" and not os.path.exists(tmp_path / "root" / "Fresh")
    monkeypatch.undo()
    intake.run(root, "Acme", [f])
    monkeypatch.setattr(shutil, "copy2", lambda *a, **k: (_ for _ in ()).throw(OSError("denied")))
    out = intake.run(root, "Acme", [f], mode="add")
    assert out["status"] == "blocked" and os.listdir(tmp_path / "root" / "Acme") == ["sow.pdf"]


def test_target_that_is_a_plain_file_is_blocked(tmp_path):
    root = tmp_path / "root"; root.mkdir(); (root / "Acme").write_text("x")
    out = intake.run(str(root), "Acme", [_src(tmp_path, "sow.pdf")])
    assert out["status"] == "blocked" and "not a folder" in out["message"]
