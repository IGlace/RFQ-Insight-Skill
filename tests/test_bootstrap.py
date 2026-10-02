"""bootstrap.py - venv location, readiness stamp, plain-language failures.

These never create a real venv or touch the network: provisioning is
exercised by hand once (Task 13), and asserting pip's behaviour in unit
tests buys nothing.
"""

import json
import os
import sys

import pytest

import bootstrap


def test_line_endings_do_not_invalidate_the_toolbox(tmp_path):
    """Git rewrites line endings on checkout when core.autocrlf is on, which
    is the Windows default. The same dependency list stored CRLF must hash
    the same as stored LF, or a branch switch silently discards a working
    toolbox and demands a network reinstall that changes nothing.

    Found during the merge of this branch: checking out main flipped
    requirements.txt to CRLF and bootstrap --check reported the tools as
    missing.
    """
    lf = tmp_path / "lf.txt"
    crlf = tmp_path / "crlf.txt"
    body = "python-pptx==1.0.2\nPillow==12.2.0\n"
    lf.write_bytes(body.encode())
    crlf.write_bytes(body.replace("\n", "\r\n").encode())

    assert lf.read_bytes() != crlf.read_bytes()      # genuinely different bytes
    assert bootstrap.requirements_digest(str(lf)) \
        == bootstrap.requirements_digest(str(crlf))


def test_a_real_dependency_change_still_invalidates_the_toolbox(tmp_path):
    """The normalization must not blunt the stamp's actual job."""
    before = tmp_path / "before.txt"
    after = tmp_path / "after.txt"
    before.write_bytes(b"python-pptx==1.0.2\n")
    after.write_bytes(b"python-pptx==1.0.3\n")
    assert bootstrap.requirements_digest(str(before)) \
        != bootstrap.requirements_digest(str(after))


def test_interpreter_path_is_platform_correct(tmp_path):
    py = bootstrap.interpreter(str(tmp_path))
    if os.name == "nt":
        assert py.endswith(os.path.join("Scripts", "python.exe"))
    else:
        assert py.endswith(os.path.join("bin", "python"))


def test_venv_lives_under_the_user_home_not_the_skill():
    assert bootstrap.VENV_DIR.startswith(os.path.expanduser("~"))
    assert "skills" not in bootstrap.VENV_DIR


def test_not_ready_without_a_venv(tmp_path):
    assert bootstrap.is_ready(str(tmp_path)) is False


def test_ready_only_when_the_stamp_matches_requirements(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("python-pptx==1.0.2\n", encoding="utf-8")
    venv_dir = tmp_path / "venv"
    os.makedirs(os.path.dirname(bootstrap.interpreter(str(venv_dir))))
    open(bootstrap.interpreter(str(venv_dir)), "w").close()

    stamp = os.path.join(str(venv_dir), ".requirements-sha256")
    with open(stamp, "w", encoding="utf-8") as fh:
        fh.write("stale-digest")
    assert bootstrap.is_ready(str(venv_dir), str(req)) is False

    with open(stamp, "w", encoding="utf-8") as fh:
        fh.write(bootstrap.requirements_digest(str(req)))
    assert bootstrap.is_ready(str(venv_dir), str(req)) is True


def test_offline_pip_failure_says_no_network():
    msg = bootstrap.explain_pip_failure(
        "WARNING: Retrying after connection broken by ProxyError\n"
        "ERROR: Could not find a version that satisfies the requirement")
    assert "network" in msg.lower()
    assert "pip" not in msg.lower()      # no tool names in user-facing text


def test_a_bad_pin_is_not_blamed_on_the_network():
    """"No matching distribution" usually means a bad pin or an unavailable
    wheel. Sending a salesperson to IT about network access would send two
    people after the wrong fault."""
    msg = bootstrap.explain_pip_failure(
        "ERROR: Could not find a version that satisfies the requirement "
        "python-docx==9.9.9\nERROR: No matching distribution found")
    assert "network" not in msg.lower()
    assert "technical detail" in msg.lower()


def test_other_pip_failure_keeps_the_tail_for_the_report():
    msg = bootstrap.explain_pip_failure("ERROR: Something unrecognised broke")
    assert "couldn't set up" in msg.lower()
    assert "technical detail" in msg.lower()
    assert "network" not in msg.lower()


@pytest.mark.parametrize("flags", [[], ["--check"]])
def test_ready_toolbox_is_reported_and_only_refreshed_without_check(monkeypatch, capsys, flags):
    monkeypatch.setattr(bootstrap, "is_ready", lambda: True)
    monkeypatch.setattr(bootstrap, "interpreter", lambda: "existing-venv")
    provisioned = []

    def provision():
        provisioned.append(True)
        return "existing-venv"

    monkeypatch.setattr(bootstrap, "provision", provision)
    monkeypatch.setattr(sys, "argv", ["bootstrap.py", *flags])
    with pytest.raises(SystemExit) as exc:
        bootstrap.main()
    assert exc.value.code == bootstrap.EXIT_OK
    assert capsys.readouterr().out.strip() == "existing-venv"
    assert bool(provisioned) == (not flags)


def test_versions_are_available_without_pip(tmp_path, monkeypatch):
    metadata = tmp_path / "Example-1.2.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text("Metadata-Version: 2.1\nName: Example\nVersion: 1.2\n", encoding="utf-8")
    run = bootstrap.subprocess.run

    def isolated_runtime(command, **kwargs):
        # Suppress site-packages to model the installer's runtime without pip.
        env = os.environ.copy()
        env["PYTHONPATH"] = str(tmp_path)
        return run([command[0], "-S", *command[1:]], env=env, **kwargs)

    monkeypatch.setattr(bootstrap.subprocess, "run", isolated_runtime)
    assert bootstrap.installed_versions(sys.executable) == {"Example": "1.2"}


def test_check_accepts_a_system_interpreter_that_already_has_the_libraries(monkeypatch, capsys):
    monkeypatch.setattr(bootstrap, "is_ready", lambda: False)
    monkeypatch.setattr(bootstrap, "system_interpreter_ready", lambda: True)
    monkeypatch.setattr(sys, "argv", ["bootstrap.py", "--check"])
    with pytest.raises(SystemExit) as exc:
        bootstrap.main()
    assert exc.value.code == bootstrap.EXIT_OK
    assert capsys.readouterr().out.strip() == sys.executable


def test_check_reports_not_ready_without_venv_or_system_libraries(monkeypatch, capsys):
    monkeypatch.setattr(bootstrap, "is_ready", lambda: False)
    monkeypatch.setattr(bootstrap, "system_interpreter_ready", lambda: False)
    monkeypatch.setattr(sys, "argv", ["bootstrap.py", "--check"])
    with pytest.raises(SystemExit) as exc:
        bootstrap.main()
    assert exc.value.code == bootstrap.EXIT_NOT_READY


def test_failed_provisioning_falls_back_to_a_capable_system_interpreter(monkeypatch, capsys):
    def failing_provision():
        raise RuntimeError("no package index")

    monkeypatch.setattr(bootstrap, "provision", failing_provision)
    monkeypatch.setattr(bootstrap, "system_interpreter_ready", lambda: True)
    monkeypatch.setattr(sys, "argv", ["bootstrap.py"])
    with pytest.raises(SystemExit) as exc:
        bootstrap.main()
    assert exc.value.code == bootstrap.EXIT_OK
    assert capsys.readouterr().out.strip() == sys.executable


def test_failed_provisioning_without_fallback_reports_the_plain_language_error(monkeypatch, capsys):
    def failing_provision():
        raise RuntimeError("no package index")

    monkeypatch.setattr(bootstrap, "provision", failing_provision)
    monkeypatch.setattr(bootstrap, "system_interpreter_ready", lambda: False)
    monkeypatch.setattr(sys, "argv", ["bootstrap.py"])
    with pytest.raises(SystemExit) as exc:
        bootstrap.main()
    assert exc.value.code == bootstrap.EXIT_FAILED
    assert "no package index" in capsys.readouterr().err


def test_system_interpreter_probe_runs_in_a_subprocess():
    assert bootstrap.system_interpreter_ready(sys.executable) in (True, False)
    assert bootstrap.system_interpreter_ready("/definitely/not/python") is False
