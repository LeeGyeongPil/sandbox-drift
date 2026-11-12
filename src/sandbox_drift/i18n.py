"""Language choice and message lookup (English and Korean).

Order: ``--lang`` option > ``SANDBOX_DRIFT_LANG`` > ``LC_ALL`` > ``LC_MESSAGES`` > ``LANG``.
Anything that is not Korean falls back to English. All user-facing text lives in
``locales/en.json`` and ``locales/ko.json``, which must have identical keys.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Mapping

SUPPORTED = ("en", "ko")
ENV_VAR = "SANDBOX_DRIFT_LANG"
_LOCALE_DIR = Path(__file__).parent / "locales"


@lru_cache(maxsize=None)
def messages(lang: str) -> dict[str, str]:
    path = _LOCALE_DIR / f"{lang}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _from_text(value: str | None) -> str | None:
    if not value:
        return None
    lowered = value.strip().lower()
    if lowered.startswith("ko"):
        return "ko"
    if lowered.startswith("en"):
        return "en"
    return "en"  # any other locale (C, POSIX, de_DE, ...) -> English


def resolve_lang(cli_value: str | None = None, env: Mapping[str, str] | None = None) -> str:
    """Return ``'en'`` or ``'ko'`` following the documented priority."""
    env = os.environ if env is None else env
    if cli_value in SUPPORTED:
        return cli_value
    for name in (ENV_VAR, "LC_ALL", "LC_MESSAGES", "LANG"):
        value = env.get(name)
        if value:
            if name == ENV_VAR and value.strip().lower() not in SUPPORTED:
                continue  # an invalid tool-specific value is ignored, the next source decides
            found = _from_text(value)
            if found:
                return found
    return "en"


def translator(lang: str):
    """Return ``tr(key, **params)`` for a language; unknown keys raise KeyError (caught by tests)."""
    table = messages(lang)

    def tr(key: str, /, **params: object) -> str:
        return table[key].format(**params)

    return tr
