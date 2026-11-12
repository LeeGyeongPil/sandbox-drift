"""The probes. Standard library only, no ``from __future__`` import.

This file runs *inside* the sandbox under test. For ``wrap`` and ``srt`` targets
it is copied next to a config file, with ``classify.py`` prepended, and started
with ``python -I``. For ``self`` it is imported and called in-process.

Every probe is harmless: it writes a throw-away file, reads a fake canary file,
or connects to localhost, the reserved ``.invalid`` TLD (through the proxy) or
TEST-NET-1 (RFC 5737, never routed). No real credential path is touched.
"""

import errno
import json
import os
import secrets
import socket
import subprocess
import sys
import urllib.error
import urllib.request

if "classify_oserror" not in globals():  # imported as a module, not bundled
    from sandbox_drift.classify import (
        ALLOWED,
        BLOCKED,
        ERROR,
        NOT_APPLICABLE,
        classify_connect,
        classify_http,
        classify_oserror,
        classify_unix_socket,
        is_denied,
    )

RESULT_MARKER = "SANDBOX_DRIFT_RESULT="

PROBE_IDS = (
    "fs.write_inside_workdir",
    "fs.write_outside_workdir",
    "cred.read_fake_home_canary",
    "net.localhost_listener",
    "net.proxy_reserved_host",
    "net.direct_egress_testnet",
    "proc.docker_socket",
    "proc.nested_sandbox",
)

TESTNET_ADDRESS = ("192.0.2.1", 9)  # RFC 5737 TEST-NET-1, not routed
RESERVED_URL = "http://canary.invalid/probe"  # RFC 6761 reserved TLD
DEFAULT_DOCKER_SOCKET = "/var/run/docker.sock"
PROXY_VARIABLES = ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy")

# Human-readable detail texts. The worker reports a (code, args) pair; the English text is
# kept as a fallback and the report layer translates ``detail.<code>`` from the locale files.
DETAIL_EN = {
    "no_directory": "directory does not exist",
    "write_ok": "file written and removed",
    "self_no_home": "self mode cannot swap HOME; run with --target wrap or srt",
    "canary_readable": "canary token readable={readable}",
    "read_denied": "read denied for {count} canary file(s)",
    "no_canary_files": "no canary files configured",
    "no_listener": "no listener",
    "localhost_ok": "connected to the localhost canary listener",
    "no_proxy": "no proxy variable set (the sandbox gave this process no proxy)",
    "http_status": "HTTP {status}",
    "connected": "connected",
    "packet_left": "packet left the sandbox ({text})",
    "socket_connected": "connected (no request sent)",
    "no_docker_socket": "no docker socket on this machine",
    "macos_only": "sandbox-exec exists on macOS only",
    "nested_ok": "a nested sandbox could be created",
    "os_error": "{text}",  # raw OS or tool message, never translated
}


def _d(code, **args):
    return code, args


def _os(exc, scrub):
    return _d("os_error", text=describe(exc, scrub))


def describe(exc, scrub=()):
    """Short, path-free description of an exception for the detail column."""
    code = errno.errorcode.get(getattr(exc, "errno", None) or 0, type(exc).__name__)
    text = getattr(exc, "strerror", None) or str(exc) or type(exc).__name__
    for secret, label in scrub:
        if secret:
            text = text.replace(secret, label)
    return ("%s: %s" % (code, text))[:160]


def _scrub_list(config):
    home = os.path.expanduser("~")
    return [(config.get("fake_home") or "", "<FAKE_HOME>"), (config.get("workdir") or "", "<WORK>"),
            (config.get("outside_dir") or "", "<OUTSIDE>"), (home, "<HOME>")]


def _write_and_remove(directory):
    path = os.path.join(directory, ".sandbox-drift-canary-" + secrets.token_hex(4))
    try:
        with open(path, "w") as handle:
            handle.write("canary")
    finally:
        # If the write succeeded the file exists; never leave it behind.
        try:
            os.remove(path)
        except OSError:
            pass


def probe_write(directory, scrub):
    if not directory or not os.path.isdir(directory):
        return NOT_APPLICABLE, _d("no_directory")
    try:
        _write_and_remove(directory)
    except OSError as exc:
        return classify_oserror(exc), _os(exc, scrub)
    return ALLOWED, _d("write_ok")


def probe_credential_canary(config, scrub):
    fake_home = config.get("fake_home")
    if not fake_home:
        return NOT_APPLICABLE, _d("self_no_home")
    token = config.get("canary_token", "")
    seen_blocked = 0
    last_error = None
    for parts in config.get("cred_paths", []):
        path = os.path.join(fake_home, *parts)
        try:
            with open(path) as handle:
                data = handle.read()
        except OSError as exc:
            if is_denied(exc):
                seen_blocked += 1
            else:
                last_error = exc
            continue
        return ALLOWED, _d("canary_readable", readable=str(token in data))
    if seen_blocked and last_error is None:
        return BLOCKED, _d("read_denied", count=seen_blocked)
    if last_error is not None:
        return ERROR, _os(last_error, scrub)
    return NOT_APPLICABLE, _d("no_canary_files")


def probe_localhost(config, scrub):
    port = config.get("listener_port")
    if not port:
        return NOT_APPLICABLE, _d("no_listener")
    timeout = config.get("timeout", 2)
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as conn:
            conn.sendall(b"GET /canary?token=" + config.get("canary_token", "x").encode() + b" HTTP/1.0\r\nHost: localhost\r\n\r\n")
            conn.recv(64)
    except OSError as exc:
        return classify_oserror(exc), _os(exc, scrub)
    return ALLOWED, _d("localhost_ok")


def probe_proxy_reserved_host(config, scrub):
    proxies = [name for name in PROXY_VARIABLES if os.environ.get(name)]
    if not proxies:
        return NOT_APPLICABLE, _d("no_proxy")
    try:
        with urllib.request.urlopen(RESERVED_URL, timeout=config.get("timeout", 2) + 3) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        return classify_http(exc.code), _d("http_status", status=exc.code)
    except Exception as exc:  # noqa: BLE001 - any failure here is just "cannot tell"
        return ERROR, _os(exc, scrub)
    return classify_http(status), _d("http_status", status=status)


def probe_direct_egress(config, scrub, connect=None):
    timeout = config.get("timeout", 2)
    sock = socket.socket()
    sock.settimeout(timeout)
    outcome = None
    try:
        (connect or sock.connect)(TESTNET_ADDRESS)
    except OSError as exc:
        outcome = exc
    finally:
        sock.close()
    observed = classify_connect(outcome)
    if outcome is None:
        return observed, _d("connected")
    if observed == ALLOWED:
        return observed, _d("packet_left", text=describe(outcome, scrub))
    return observed, _os(outcome, scrub)


def probe_docker_socket(config, scrub):
    path = config.get("docker_socket") or DEFAULT_DOCKER_SOCKET
    sock = socket.socket(socket.AF_UNIX)
    sock.settimeout(config.get("timeout", 2))
    outcome = None
    try:
        sock.connect(path)  # connect only, never send a request
    except OSError as exc:
        outcome = exc
    finally:
        sock.close()
    observed = classify_unix_socket(outcome)
    if outcome is None:
        return observed, _d("socket_connected")
    if observed == NOT_APPLICABLE:
        return observed, _d("no_docker_socket")
    return observed, _os(outcome, scrub)


def probe_nested_sandbox(config, scrub):
    tool = "/usr/bin/sandbox-exec"
    if sys.platform != "darwin" or not os.path.exists(tool):
        return NOT_APPLICABLE, _d("macos_only")
    try:
        done = subprocess.run([tool, "-p", "(version 1)(allow default)", "/usr/bin/true"],
                              capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        return ERROR, _os(exc, scrub)
    if done.returncode == 0:
        return ALLOWED, _d("nested_ok")
    return BLOCKED, _d("os_error", text=(done.stderr.strip().splitlines() or ["rc=%d" % done.returncode])[-1][:160])


def run_probes(config, connect=None):
    """Run all probes. ``connect`` lets tests replace the TEST-NET connection."""
    scrub = _scrub_list(config)
    outcomes = {
        "fs.write_inside_workdir": probe_write(config.get("workdir"), scrub),
        "fs.write_outside_workdir": probe_write(config.get("outside_dir"), scrub),
        "cred.read_fake_home_canary": probe_credential_canary(config, scrub),
        "net.localhost_listener": probe_localhost(config, scrub),
        "net.proxy_reserved_host": probe_proxy_reserved_host(config, scrub),
        "net.direct_egress_testnet": probe_direct_egress(config, scrub, connect),
        "proc.docker_socket": probe_docker_socket(config, scrub),
        "proc.nested_sandbox": probe_nested_sandbox(config, scrub),
    }
    return {name: {"observed": observed, "detail": DETAIL_EN[code].format(**args), "detail_code": code,
                   "detail_args": args} for name, (observed, (code, args)) in outcomes.items()}


def main(argv):
    with open(argv[1]) as handle:
        config = json.load(handle)
    print(RESULT_MARKER + json.dumps(run_probes(config)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
