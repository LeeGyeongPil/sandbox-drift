import json

import pytest

from sandbox_drift.errors import ExecutorUnavailable
from sandbox_drift.targets import bundle_worker_source, expand_wrap

from conftest import SELF_POLICY

RC71 = "import sys\nsys.stderr.write('sandbox-exec: sandbox_apply: Operation not permitted\\n')\nsys.exit(71)\n"
LISTEN = "import sys\nsys.stderr.write('Error: listen EPERM: operation not permitted 127.0.0.1\\n')\nsys.exit(1)\n"
SILENT = "import sys\nsys.exit(0)\n"
GARBAGE = "print('SANDBOX_DRIFT_RESULT={not json')\n"


@pytest.mark.parametrize("body,fragment", [
    (RC71, "cannot be created inside this sandbox"),
    (LISTEN, "proxy socket"),
    (SILENT, "without a result"),
    (GARBAGE, "unreadable result"),
])
def test_executor_failure_is_exit_2(cli, make_script, fast_args, body, fragment):
    runner = make_script("runner.py", body)
    code, out, err = cli("run", "--target", "wrap", "--wrap", f"{runner} {{}}", "--policy", str(SELF_POLICY),
                         *fast_args)
    assert code == 2
    assert fragment in err
    assert "sandbox-drift self" in err  # tells the user what to do instead
    assert "PASS" not in out and "blocked" not in out  # nothing is reported as a result


def test_missing_runner_is_exit_2(cli, fast_args):
    code, out, err = cli("run", "--target", "wrap", "--wrap", "/nonexistent/runner {}", *fast_args)
    assert code == 2 and "sandbox-drift self" in err and out == ""


def test_exit_zero_does_not_hide_an_unrunnable_runner(cli, fast_args):
    code, _, _ = cli("run", "--target", "wrap", "--wrap", "/nonexistent/runner {}", "--exit-zero", *fast_args)
    assert code == 2


def test_runner_timeout_is_exit_2(cli, make_script, fast_args):
    runner = make_script("slow.py", "import time\ntime.sleep(30)\n")
    code, _, err = cli("run", "--target", "wrap", "--wrap", f"{runner} {{}}", "--total-timeout", "0.5", *fast_args)
    assert code == 2 and "did not finish" in err


def test_wrap_requires_placeholder(cli, fast_args):
    code, _, err = cli("run", "--target", "wrap", "--wrap", "echo hi", *fast_args)
    assert code == 2 and "{}" in err


def test_missing_option_for_target(cli):
    code, _, err = cli("run", "--target", "srt")
    assert code == 2 and "--settings" in err
    code, _, err = cli("run", "--target", "wrap")
    assert code == 2 and "--wrap" in err


def test_expand_wrap_forms():
    command = ["py", "-I", "w.py", "c.json"]
    assert expand_wrap("runner --x {}", command) == ["runner", "--x", "py", "-I", "w.py", "c.json"]
    assert expand_wrap("{}", command) == command
    assert expand_wrap("sh -c 'echo {}'", command) == ["sh", "-c", "echo py -I w.py c.json"]


def test_bundle_is_valid_python_and_standalone():
    source = bundle_worker_source()
    compile(source, "worker-bundle", "exec")
    assert [l for l in source.splitlines() if l.startswith("from __future__")] == ["from __future__ import annotations"]  # only classify.py's, which must stay first


def test_wrap_runs_the_bundled_worker_with_a_json_result(cli, tmp_path, fast_args):
    out = tmp_path / "wrap.json"
    code, _, err = cli("run", "--target", "wrap", "--wrap", "{}", "--format", "json", "--out", str(out), *fast_args)
    assert code in (0, 1), err
    data = json.loads(out.read_text())
    assert data["target"] == "wrap" and len(data["probes"]) == 8
    assert isinstance(ExecutorUnavailable("x"), Exception)
