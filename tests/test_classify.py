import errno
import socket

import pytest

from sandbox_drift import classify as c


def os_error(code):
    return OSError(code, "x")


@pytest.mark.parametrize("exc,expected", [
    (os_error(errno.EPERM), c.BLOCKED),
    (os_error(errno.EACCES), c.BLOCKED),
    (PermissionError(), c.BLOCKED),
    (os_error(errno.ENOENT), c.ERROR),
])
def test_oserror(exc, expected):
    assert c.classify_oserror(exc) == expected


@pytest.mark.parametrize("status,expected", [
    (403, c.BLOCKED), (407, c.BLOCKED), (200, c.ALLOWED), (204, c.ALLOWED), (500, c.ERROR), (404, c.ERROR),
])
def test_http(status, expected):
    assert c.classify_http(status) == expected


@pytest.mark.parametrize("exc,expected", [
    (None, c.ALLOWED),
    (socket.timeout(), c.ALLOWED),
    (TimeoutError(), c.ALLOWED),
    (os_error(errno.ENETUNREACH), c.ALLOWED),
    (os_error(errno.ECONNREFUSED), c.ALLOWED),
    (os_error(errno.EPERM), c.BLOCKED),
    (os_error(errno.EACCES), c.BLOCKED),
    (os_error(errno.EIO), c.ERROR),
])
def test_connect(exc, expected):
    assert c.classify_connect(exc) == expected


@pytest.mark.parametrize("exc,expected", [
    (None, c.ALLOWED),
    (FileNotFoundError(), c.NOT_APPLICABLE),
    (os_error(errno.EPERM), c.BLOCKED),
    (ConnectionRefusedError(), c.ALLOWED),
    (os_error(errno.EIO), c.ERROR),
])
def test_unix_socket(exc, expected):
    assert c.classify_unix_socket(exc) == expected


def test_proxy_probe_without_proxy_env_is_not_applicable(monkeypatch):
    from sandbox_drift import worker

    for name in worker.PROXY_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    observed, _ = worker.probe_proxy_reserved_host({}, [])
    assert observed == c.NOT_APPLICABLE


def test_docker_socket_missing_is_not_applicable():
    from sandbox_drift import worker

    observed, _ = worker.probe_docker_socket({"docker_socket": "/nonexistent-sandbox-drift/docker.sock"}, [])
    assert observed == c.NOT_APPLICABLE


def test_direct_egress_uses_injected_connect_without_waiting():
    from sandbox_drift import worker

    def timeout(_address):
        raise socket.timeout()

    def denied(_address):
        raise os_error(errno.EPERM)

    assert worker.probe_direct_egress({}, [], connect=timeout)[0] == c.ALLOWED
    assert worker.probe_direct_egress({}, [], connect=denied)[0] == c.BLOCKED
