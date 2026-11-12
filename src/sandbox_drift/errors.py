"""Errors carry a stable code plus parameters so the CLI can translate them."""

from __future__ import annotations


class SandboxDriftError(Exception):
    """Base error: ``code`` selects the message ``err.<code>``, ``params`` fill it in."""

    def __init__(self, code: str, **params: object) -> None:
        self.code = code
        self.params = params
        super().__init__(f"{code}: {params}")


class ExecutorUnavailable(SandboxDriftError):
    """The runner could not run the worker at all (exit 2, never reported as 'blocked')."""
