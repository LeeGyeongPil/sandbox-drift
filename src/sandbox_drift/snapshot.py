"""Snapshots of one run, and the comparison between two of them."""

from __future__ import annotations

import json
import platform
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sandbox_drift.classify import ALLOWED, BLOCKED, OBSERVATIONS
from sandbox_drift.errors import SandboxDriftError

KEY_FIELDS = ("target", "agent_version", "engine_version", "os", "arch", "policy_hash", "settings_fingerprint")

OPENED = "opened"  # blocked -> allowed: the regression we care about
TIGHTENED = "tightened"  # allowed -> blocked
CHANGED = "changed"  # any other difference


@dataclass(frozen=True)
class Change:
    probe: str
    old: str
    new: str
    kind: str


def _probe_entry(p: dict) -> dict:
    entry = {"observed": p["observed"], "detail": p.get("detail", "")}
    if p.get("detail_code"):  # older snapshots have no code; their English detail is used as is
        entry["detail_code"] = p["detail_code"]
        entry["detail_args"] = p.get("detail_args", {})
    return entry


def new_snapshot(target: str, probes: dict[str, dict], *, agent_version: str = "unknown",
                 engine_version: str = "unknown", policy_hash: str = "", settings_fingerprint: str = "none",
                 note: str | None = None, note_code: str | None = None) -> dict:
    snapshot: dict = {
        "schema": 1,
        "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "target": target,
        "agent_version": agent_version,
        "engine_version": engine_version,
        "os": platform.system().lower(),
        "arch": platform.machine().lower(),
        "policy_hash": policy_hash,
        "settings_fingerprint": settings_fingerprint,
        "probes": {name: _probe_entry(p) for name, p in probes.items()},
    }
    if note:
        snapshot["note"] = note
    if note_code:  # machine key of a note this tool ships; the report translates ``note.<code>``
        snapshot["note_code"] = note_code
    return snapshot


def load_snapshot(path: str | Path) -> dict:
    file = Path(path)
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SandboxDriftError("snapshot_not_found", path=str(file)) from exc
    except OSError as exc:
        raise SandboxDriftError("file_unreadable", path=str(file), detail=exc.strerror or "") from exc
    except json.JSONDecodeError as exc:
        raise SandboxDriftError("snapshot_invalid_json", path=str(file), detail=str(exc)) from exc
    probes = data.get("probes") if isinstance(data, dict) else None
    if not isinstance(probes, dict) or not probes:
        raise SandboxDriftError("snapshot_no_probes", path=str(file))
    for name, entry in probes.items():
        if not isinstance(entry, dict) or entry.get("observed") not in OBSERVATIONS:
            raise SandboxDriftError("snapshot_bad_observation", path=str(file), probe=name,
                                    allowed=", ".join(OBSERVATIONS))
    return data


def save_snapshot(path: str | Path, snapshot: dict) -> None:
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def observed_map(snapshot: dict) -> dict[str, str]:
    return {name: entry["observed"] for name, entry in snapshot["probes"].items()}


def diff_snapshots(old: dict, new: dict) -> list[Change]:
    """Every probe whose observation differs, classified as opened / tightened / changed."""
    before, after = observed_map(old), observed_map(new)
    changes = []
    for probe in sorted(set(before) | set(after)):
        a, b = before.get(probe, "-"), after.get(probe, "-")
        if a == b:
            continue
        if (a, b) == (BLOCKED, ALLOWED):
            kind = OPENED
        elif (a, b) == (ALLOWED, BLOCKED):
            kind = TIGHTENED
        else:
            kind = CHANGED
        changes.append(Change(probe, a, b, kind))
    return changes


def key_differences(old: dict, new: dict) -> list[tuple[str, str, str]]:
    """Identity fields (versions, policy hash, ...) that differ between two snapshots."""
    return [(field, str(old.get(field, "-")), str(new.get(field, "-")))
            for field in KEY_FIELDS if old.get(field) != new.get(field)]


def should_fail(changes: list[Change], strict: bool) -> bool:
    """Opened cells always fail; with ``strict`` every difference does."""
    return any(c.kind == OPENED or strict for c in changes)
