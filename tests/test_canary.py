import json
from pathlib import Path

from sandbox_drift.canary import CRED_PATHS, Canary
from sandbox_drift.listener import CanaryListener


def test_fake_home_only_under_tmp_and_cleaned():
    with Canary() as canary:
        root = canary.root
        assert root is not None and root.name.startswith("sandbox-drift-")
        assert canary.fake_home.parent == root
        for parts in CRED_PATHS:
            file = canary.fake_home.joinpath(*parts)
            assert file.is_file()
            assert file.read_text().strip() == canary.token  # nothing but the canary token
        assert canary.token.startswith("SANDBOX_DRIFT_CANARY_") and len(canary.token) == 21 + 16
    assert not root.exists()


def test_tokens_are_random():
    with Canary() as a, Canary() as b:
        assert a.token != b.token


def test_identity_wrap_sees_canary(cli, make_script, tmp_path, fast_args):
    # a runner that records HOME then starts the worker unchanged = no sandbox at all
    record = tmp_path / "home.txt"
    runner = make_script("record_home.py", (
        "import os, sys\n"
        f"open({str(record)!r}, 'w').write(os.environ['HOME'])\n"
        "os.execv(sys.argv[1], sys.argv[1:])\n"))
    out = tmp_path / "result.json"
    code, _, err = cli("run", "--target", "wrap", "--wrap", f"{runner} {{}}", "--format", "json", "--out", str(out),
                       *fast_args)
    assert code == 1, err  # the negative control: no sandbox means the canary IS readable -> FAIL
    data = json.loads(out.read_text())
    cred = data["probes"]["cred.read_fake_home_canary"]
    assert cred["observed"] == "allowed" and cred["verdict"] == "FAIL"
    child_home = Path(record.read_text())
    assert child_home.name == "home" and child_home.parent.name.startswith("sandbox-drift-")
    assert not child_home.exists()  # temp folder removed after the run


def test_listener_records_hits_and_stops():
    import socket

    with CanaryListener() as listener:
        with socket.create_connection(("127.0.0.1", listener.port), timeout=2) as conn:
            conn.sendall(b"GET /canary HTTP/1.0\r\n\r\n")
            conn.recv(64)
        assert "/canary" in listener.hits
        port = listener.port
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
        raise AssertionError("listener still open")
    except OSError:
        pass
