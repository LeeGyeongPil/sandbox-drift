"""Expected policy: for every probe, should the sandbox block it, allow it, or just inform."""

from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

from sandbox_drift.errors import SandboxDriftError
from sandbox_drift.worker import PROBE_IDS

EXPECTATIONS = ("block", "allow", "info")

PRESETS: dict[str, str] = {
    "self-basic": """\
# Expected results for `sandbox-drift self` (the sandbox you are already inside).
# block = the sandbox must refuse it, allow = it must work, info = just record it.
[expect]
"fs.write_inside_workdir" = "allow"
"fs.write_outside_workdir" = "block"
"cred.read_fake_home_canary" = "block"   # skipped in self mode (HOME cannot be swapped)
"net.localhost_listener" = "allow"
"net.proxy_reserved_host" = "block"
"net.direct_egress_testnet" = "block"
"proc.docker_socket" = "block"
"proc.nested_sandbox" = "info"
""",
    "claude-srt": """\
# Expected results for `sandbox-drift run --target srt` with an agent settings style
# sandbox block (workdir writable, everything else closed, only localhost open).
[expect]
"fs.write_inside_workdir" = "allow"
"fs.write_outside_workdir" = "block"
"cred.read_fake_home_canary" = "block"
"net.localhost_listener" = "allow"
"net.proxy_reserved_host" = "block"
"net.direct_egress_testnet" = "block"
"proc.docker_socket" = "block"
"proc.nested_sandbox" = "info"
""",
}


def parse_policy(text: str, source: str = "<policy>") -> dict[str, str]:
    """Parse TOML text into ``{probe_id: expectation}``; probes not listed default to ``info``."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise SandboxDriftError("policy_invalid_toml", path=source, detail=str(exc)) from exc
    expect = data.get("expect")
    if not isinstance(expect, dict):
        raise SandboxDriftError("policy_no_expect", path=source)
    result = {probe: "info" for probe in PROBE_IDS}
    for probe, value in expect.items():
        if probe not in PROBE_IDS:
            raise SandboxDriftError("policy_unknown_probe", path=source, probe=probe, known=", ".join(PROBE_IDS))
        if value not in EXPECTATIONS:
            raise SandboxDriftError("policy_bad_value", path=source, probe=probe, value=str(value),
                                    allowed=", ".join(EXPECTATIONS))
        result[probe] = value
    return result


def load_policy(path: str | Path) -> dict[str, str]:
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SandboxDriftError("policy_not_found", path=str(file)) from exc
    except OSError as exc:
        raise SandboxDriftError("file_unreadable", path=str(file), detail=exc.strerror or "") from exc
    return parse_policy(text, str(file))


def policy_hash(policy: dict[str, str]) -> str:
    """Stable hash of the expectations (key order and file formatting do not matter)."""
    canonical = json.dumps(policy, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()
