"""Stable fingerprints so 'did the sandbox configuration change?' has a yes/no answer."""

from __future__ import annotations

import hashlib
import json
import re

_LOG_TAG = re.compile(r'\(with message "[^"]*"\)')
_PROXY_PORT = re.compile(r"(localhost|127\.0\.0\.1|\[::1\]):\d+")
_TEMP_PATH = re.compile(r"/(?:private/)?(?:var/folders|tmp)/[^\s\"')]*")
_SPACES = re.compile(r"[ \t]+")


def _digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def fingerprint_settings(data: object) -> str:
    """Hash of a settings object; key order and whitespace do not matter."""
    return _digest(json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def normalize_sbpl(text: str) -> str:
    """Remove the parts of a Seatbelt profile that change on every run.

    Random log tags, the proxy port and temp paths differ between runs even when
    the rules are identical, so they are replaced with placeholders.
    """
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        line = _LOG_TAG.sub('(with message "<TAG>")', line)
        line = _PROXY_PORT.sub(r"\1:<PORT>", line)
        line = _TEMP_PATH.sub("<TMP>", line)
        lines.append(_SPACES.sub(" ", line))
    return "\n".join(lines)


def fingerprint_sbpl(text: str) -> str:
    return _digest(normalize_sbpl(text))
