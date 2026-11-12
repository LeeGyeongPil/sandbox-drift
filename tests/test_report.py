import pytest

from sandbox_drift.policy import PRESETS, parse_policy
from sandbox_drift.report import ERR, FAIL, FLIP, INFO, PASS, SKIP, evaluate, exit_code, judge
from sandbox_drift.snapshot import Change


def probes(**observed):
    return {name.replace("__", "."): {"observed": value, "detail": ""} for name, value in observed.items()}


@pytest.mark.parametrize("expect,observed,verdict", [
    ("block", "blocked", PASS), ("block", "allowed", FAIL),
    ("allow", "allowed", PASS), ("allow", "blocked", FAIL),
    ("info", "allowed", INFO), ("info", "blocked", INFO),
    ("block", "n/a", SKIP), ("allow", "n/a", SKIP), ("info", "n/a", SKIP),
    ("block", "error", ERR),
])
def test_judge(expect, observed, verdict):
    assert judge(expect, observed) == verdict


def test_verdicts_and_exit_codes():
    policy = parse_policy(PRESETS["self-basic"])
    ok = probes(fs__write_inside_workdir="allowed", fs__write_outside_workdir="blocked",
                cred__read_fake_home_canary="n/a", proc__nested_sandbox="allowed")
    rows = evaluate(ok, policy)
    assert [r.verdict for r in rows] == [PASS, PASS, SKIP, INFO]
    assert exit_code(rows) == 0

    bad = probes(fs__write_inside_workdir="allowed", fs__write_outside_workdir="allowed")
    rows = evaluate(bad, policy)
    assert rows[1].verdict == FAIL
    assert exit_code(rows) == 1


def test_flip_needs_a_policy_that_does_not_want_it_open():
    policy = parse_policy(PRESETS["self-basic"])
    now = probes(fs__write_outside_workdir="allowed", fs__write_inside_workdir="allowed")
    changes = [Change("fs.write_outside_workdir", "blocked", "allowed", "opened"),
               Change("fs.write_inside_workdir", "blocked", "allowed", "opened")]
    rows = {r.probe: r for r in evaluate(now, policy, changes)}
    assert rows["fs.write_outside_workdir"].verdict == FLIP
    assert rows["fs.write_outside_workdir"].change == "blocked → allowed"
    assert rows["fs.write_inside_workdir"].verdict == PASS  # expected to be allowed
    assert exit_code(list(rows.values()), changes) == 1


def test_strict_fails_on_tightening_only():
    policy = parse_policy(PRESETS["self-basic"])
    now = probes(fs__write_outside_workdir="blocked")
    changes = [Change("fs.write_outside_workdir", "allowed", "blocked", "tightened")]
    rows = evaluate(now, policy, changes)
    assert exit_code(rows, changes) == 0
    assert exit_code(rows, changes, strict=True) == 1
