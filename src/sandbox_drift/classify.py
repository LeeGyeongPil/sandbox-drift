"""Turn exceptions and HTTP codes into one of four observations.

This file is also prepended to the worker at run time, so it must stay
standard-library only and self-contained.

Observations: ``blocked`` (the sandbox said no), ``allowed`` (the packet or write
got through), ``error`` (we cannot tell), ``n/a`` (nothing to probe).
"""

from __future__ import annotations

import errno

BLOCKED = "blocked"
ALLOWED = "allowed"
ERROR = "error"
NOT_APPLICABLE = "n/a"
OBSERVATIONS = (BLOCKED, ALLOWED, ERROR, NOT_APPLICABLE)

_DENIED_ERRNOS = (errno.EPERM, errno.EACCES)
# Errors that mean "the connection attempt left the sandbox but nobody answered".
_REACHED_ERRNOS = (errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ECONNREFUSED, errno.ETIMEDOUT)


def is_denied(exc: BaseException) -> bool:
    """True for EPERM / EACCES style errors (the way sandboxes deny things)."""
    return isinstance(exc, PermissionError) or getattr(exc, "errno", None) in _DENIED_ERRNOS


def classify_oserror(exc: BaseException) -> str:
    """File-system style errors: denied -> blocked, anything else -> error."""
    return BLOCKED if is_denied(exc) else ERROR


def classify_http(status: int) -> str:
    """HTTP status from a filtering proxy: 403/407 -> blocked, 2xx -> allowed."""
    if status in (403, 407):
        return BLOCKED
    if 200 <= status < 300:
        return ALLOWED
    return ERROR


def classify_connect(exc: BaseException | None) -> str:
    """A direct connection to an unroutable address.

    Success, a timeout, ENETUNREACH or ECONNREFUSED all mean the packet left the
    sandbox (there is simply nobody at that address), so they count as ``allowed``.
    """
    if exc is None:
        return ALLOWED
    if is_denied(exc):
        return BLOCKED
    if isinstance(exc, TimeoutError) or getattr(exc, "errno", None) in _REACHED_ERRNOS:
        return ALLOWED
    return ERROR


def classify_unix_socket(exc: BaseException | None) -> str:
    """A connect() to a Unix socket path (docker socket)."""
    if exc is None:
        return ALLOWED
    if isinstance(exc, FileNotFoundError):
        return NOT_APPLICABLE
    if is_denied(exc):
        return BLOCKED
    if isinstance(exc, ConnectionRefusedError):
        return ALLOWED
    return ERROR
