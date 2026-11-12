"""Shared fixtures: pinned language, helpers to call the CLI and to build fake runners."""

from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest

from sandbox_drift.cli import main

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
REPLAY_BEFORE = ROOT / "examples" / "replay" / "before.json"
REPLAY_AFTER = ROOT / "examples" / "replay" / "after.json"
OLD_SNAPSHOT = FIXTURES / "old-snapshot.json"  # written before detail codes existed: English detail only
SELF_POLICY = ROOT / "examples" / "policies" / "self-basic.toml"
NO_SOCKET = "/nonexistent-sandbox-drift/docker.sock"  # short path: AF_UNIX paths are limited to ~104 bytes


@pytest.fixture(autouse=True)
def pinned_language(monkeypatch):
    """Tests must not depend on the developer's locale: force English."""
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SANDBOX_DRIFT_LANG", "en")
    monkeypatch.delenv("SANDBOX_DRIFT_AGENT_VERSION", raising=False)


@pytest.fixture
def cli(capsys):
    """Call ``main`` and return ``(exit_code, stdout, stderr)``."""

    def call(*argv: str):
        try:
            code = main(list(argv))
        except SystemExit as exit_:  # argparse exits with SystemExit
            code = int(exit_.code or 0)
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return call


@pytest.fixture
def make_script(tmp_path):
    """Create an executable Python script that acts as a fake runner."""

    def build(name: str, body: str) -> Path:
        path = tmp_path / name
        path.write_text(f"#!{sys.executable}\n" + body)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    return build


@pytest.fixture
def fast_args(tmp_path):
    """Options that keep real probes quick and contained inside tmp_path."""
    outside = tmp_path / "outside"
    outside.mkdir()
    work = tmp_path / "workdir"
    work.mkdir()
    return ["--outside-dir", str(outside), "--workdir", str(work), "--timeout", "0.3",
            "--docker-socket", NO_SOCKET]
