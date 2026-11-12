"""Where the probes run: this process (self), a wrapper command, srt, or a saved snapshot.

A runner that cannot start is never reported as 'blocked'. It raises
``ExecutorUnavailable`` and the CLI exits with code 2.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from sandbox_drift import worker as worker_module
from sandbox_drift.canary import CRED_PATHS
from sandbox_drift.errors import ExecutorUnavailable, SandboxDriftError

SANDBOX_APPLY_RC = 71  # sandbox-exec exit code when it cannot apply a profile


@dataclass
class ProbeSetup:
    """Everything a worker needs to know; serialised to the worker's config file."""

    workdir: str
    outside_dir: str
    canary_token: str
    listener_port: int
    fake_home: str | None = None
    timeout: float = 2.0
    docker_socket: str | None = None
    cred_paths: list[list[str]] = field(default_factory=lambda: [list(p) for p in CRED_PATHS])

    def to_config(self) -> dict:
        return {
            "workdir": self.workdir,
            "outside_dir": self.outside_dir,
            "canary_token": self.canary_token,
            "listener_port": self.listener_port,
            "fake_home": self.fake_home,
            "timeout": self.timeout,
            "docker_socket": self.docker_socket,
            "cred_paths": self.cred_paths,
        }


def run_self(setup: ProbeSetup, connect=None) -> dict[str, dict]:
    """Run the probes in this process, inside whatever sandbox it already has."""
    return worker_module.run_probes(setup.to_config(), connect=connect)


def bundle_worker_source() -> str:
    """classify.py followed by worker.py: one dependency-free file for ``python -I``."""
    here = Path(__file__).parent
    classify = (here / "classify.py").read_text(encoding="utf-8")
    worker = (here / "worker.py").read_text(encoding="utf-8")
    return classify + "\n\n" + worker


def _write_bundle(tmp_dir: Path, setup: ProbeSetup) -> tuple[Path, Path]:
    worker_path = tmp_dir / "worker.py"
    config_path = tmp_dir / "config.json"
    worker_path.write_text(bundle_worker_source(), encoding="utf-8")
    config_path.write_text(json.dumps(setup.to_config()), encoding="utf-8")
    return worker_path, config_path


def worker_command(python: str, worker_path: Path, config_path: Path) -> list[str]:
    return [python, "-I", str(worker_path), str(config_path)]


def expand_wrap(template: str, command: list[str]) -> list[str]:
    """Replace ``{}`` in a wrapper template with the worker command (no shell involved)."""
    tokens = shlex.split(template)
    if not any("{}" in token for token in tokens):
        raise SandboxDriftError("wrap_no_placeholder")
    argv: list[str] = []
    for token in tokens:
        if token == "{}":
            argv.extend(command)
        elif "{}" in token:
            argv.append(token.replace("{}", shlex.join(command)))
        else:
            argv.append(token)
    return argv


def _tail(text: str) -> str:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return lines[-1][:200] if lines else ""


def execute(argv: list[str], env: dict[str, str], cwd: str, total_timeout: float) -> dict[str, dict]:
    """Run a runner command and parse the worker's result line, or raise ExecutorUnavailable."""
    try:
        done = subprocess.run(argv, env=env, cwd=cwd, capture_output=True, text=True, timeout=total_timeout)
    except (FileNotFoundError, PermissionError) as exc:
        raise ExecutorUnavailable("exec_not_found", command=argv[0], detail=exc.strerror or "") from exc
    except subprocess.TimeoutExpired as exc:
        raise ExecutorUnavailable("exec_timeout", seconds=int(total_timeout)) from exc
    for line in done.stdout.splitlines():
        if line.startswith(worker_module.RESULT_MARKER):
            try:
                probes = json.loads(line[len(worker_module.RESULT_MARKER):])
            except json.JSONDecodeError as exc:
                raise ExecutorUnavailable("worker_bad_json", detail=_tail(done.stdout)) from exc
            return probes
    stderr = done.stderr
    if done.returncode == SANDBOX_APPLY_RC or "sandbox_apply: Operation not permitted" in stderr:
        raise ExecutorUnavailable("nested_sandbox_apply", detail=_tail(stderr))
    if "listen EPERM" in stderr:
        raise ExecutorUnavailable("nested_listen_eperm", detail=_tail(stderr))
    raise ExecutorUnavailable("no_worker_output", rc=done.returncode, detail=_tail(stderr or done.stdout))


def run_wrap(template: str, setup: ProbeSetup, tmp_dir: Path, python: str, total_timeout: float) -> dict[str, dict]:
    worker_path, config_path = _write_bundle(tmp_dir, setup)
    argv = expand_wrap(template, worker_command(python, worker_path, config_path))
    return execute(argv, child_env(setup), setup.workdir, total_timeout)


def srt_argv(srt_bin: str, srt_settings_path: Path, command: list[str]) -> list[str]:
    return [srt_bin, "--settings", str(srt_settings_path), "-c", shlex.join(command)]


def run_srt(srt_bin: str, srt_settings: dict, setup: ProbeSetup, tmp_dir: Path, python: str,
            total_timeout: float) -> dict[str, dict]:
    worker_path, config_path = _write_bundle(tmp_dir, setup)
    settings_path = tmp_dir / "srt.json"
    settings_path.write_text(json.dumps(srt_settings), encoding="utf-8")
    argv = srt_argv(srt_bin, settings_path, worker_command(python, worker_path, config_path))
    return execute(argv, child_env(setup), setup.workdir, total_timeout)


def child_env(setup: ProbeSetup) -> dict[str, str]:
    """The runner's environment: a copy of ours with HOME pointing at the fake HOME."""
    env = dict(os.environ)
    if setup.fake_home:
        env["HOME"] = setup.fake_home
    return env


def engine_version(srt_bin: str) -> str:
    """Best effort ``srt --version``; 'unknown' when it cannot be asked."""
    try:
        done = subprocess.run([srt_bin, "--version"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return _tail(done.stdout) or "unknown"


def load_replay(path: str | Path) -> dict:
    from sandbox_drift.snapshot import load_snapshot

    return load_snapshot(path)


def default_python() -> str:
    return sys.executable
