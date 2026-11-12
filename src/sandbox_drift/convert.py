"""agent CLI ``sandbox`` settings block -> sandbox-runtime (srt) settings."""

from __future__ import annotations

import json
from pathlib import Path

from sandbox_drift.errors import SandboxDriftError

NETWORK_KEYS = ("allowedDomains", "deniedDomains", "allowUnixSockets", "allowAllUnixSockets",
                "allowLocalBinding", "httpProxyPort", "socksProxyPort")
FILESYSTEM_KEYS = ("denyRead", "allowRead", "allowWrite", "denyWrite")
PATH_KEYS = ("denyRead", "allowRead", "allowWrite", "denyWrite", "allowUnixSockets")


def load_json(path: str | Path) -> dict:
    file = Path(path)
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SandboxDriftError("settings_not_found", path=str(file)) from exc
    except OSError as exc:
        raise SandboxDriftError("file_unreadable", path=str(file), detail=exc.strerror or "") from exc
    except json.JSONDecodeError as exc:
        raise SandboxDriftError("settings_invalid_json", path=str(file), detail=str(exc)) from exc
    if not isinstance(data, dict):
        raise SandboxDriftError("settings_not_object", path=str(file))
    return data


def expand_path(value: str, fake_home: str | None) -> str:
    """``~`` becomes the fake HOME; a leading ``//`` means an absolute path (agent CLI convention)."""
    if fake_home and (value == "~" or value.startswith("~/")):
        return fake_home + value[1:]
    if value.startswith("//"):
        return value[1:]
    return value


def _pick(section: object, allowed: tuple[str, ...], where: str, warnings: list[tuple[str, str]],
          fake_home: str | None) -> dict:
    result: dict = {}
    if not isinstance(section, dict):
        return result
    for key, value in section.items():
        if key not in allowed:
            warnings.append((where + "." + key, "unknown_key"))
            continue
        if key in PATH_KEYS and isinstance(value, list):
            value = [expand_path(item, fake_home) if isinstance(item, str) else item for item in value]
        result[key] = value
    return result


def claude_to_srt(settings: dict, fake_home: str | None = None) -> tuple[dict, list[tuple[str, str]]]:
    """Return ``(srt_settings, warnings)``; warnings are ``(dotted key, code)`` pairs.

    Accepts an agent CLI settings file (``sandbox`` block) or an srt settings file
    (top-level ``network`` / ``filesystem``).
    """
    warnings: list[tuple[str, str]] = []
    if isinstance(settings.get("sandbox"), dict):
        block = settings["sandbox"]
        prefix = "sandbox."
        for key in block:
            if key not in ("network", "filesystem"):
                warnings.append((prefix + key, "not_translated"))
    elif "network" in settings or "filesystem" in settings:
        block = settings
        prefix = ""
    else:
        raise SandboxDriftError("settings_no_sandbox")
    srt = {
        "network": _pick(block.get("network"), NETWORK_KEYS, prefix + "network", warnings, fake_home),
        "filesystem": _pick(block.get("filesystem"), FILESYSTEM_KEYS, prefix + "filesystem", warnings, fake_home),
    }
    return srt, warnings
