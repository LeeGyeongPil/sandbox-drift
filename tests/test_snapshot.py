import json

from sandbox_drift.snapshot import KEY_FIELDS, diff_snapshots, load_snapshot, should_fail

from conftest import REPLAY_AFTER, REPLAY_BEFORE


def snap(**observed):
    return {"probes": {name.replace("__", "."): {"observed": value} for name, value in observed.items()}}


def test_diff_opened_tightened_strict(cli):
    old = snap(a__x="blocked", b__y="allowed", c__z="allowed")
    new = snap(a__x="allowed", b__y="blocked", c__z="allowed")
    kinds = {c.probe: c.kind for c in diff_snapshots(old, new)}
    assert kinds == {"a.x": "opened", "b.y": "tightened"}

    only_tightened = diff_snapshots(snap(b__y="allowed"), snap(b__y="blocked"))
    assert not should_fail(only_tightened, strict=False)
    assert should_fail(only_tightened, strict=True)

    # command line: the practice mock pair has exactly one flip
    code, out, _ = cli("diff", str(REPLAY_BEFORE), str(REPLAY_AFTER), "--lang", "en")
    assert code == 1
    assert "FLIP" in out and "fs.write_outside_workdir" in out and "blocked → allowed" in out
    code, out, _ = cli("diff", str(REPLAY_BEFORE), str(REPLAY_AFTER), "--exit-zero")
    assert code == 0 and "FLIP" in out
    code, out, _ = cli("diff", str(REPLAY_AFTER), str(REPLAY_BEFORE))
    assert code == 0 and "1 cell tightened" in out
    code, out, _ = cli("diff", str(REPLAY_AFTER), str(REPLAY_BEFORE), "--strict")
    assert code == 1


def test_baseline_roundtrip_detects_flip(cli, tmp_path):
    baseline = tmp_path / "base"
    code, out, _ = cli("run", "--target", "replay", "--replay", str(REPLAY_BEFORE), "--baseline", str(baseline))
    assert code == 0, out
    stored = baseline / "baseline-srt.json"
    assert stored.exists()
    saved = json.loads(stored.read_text())
    assert all(key in saved for key in KEY_FIELDS)
    assert "Baseline saved" in out

    # same input again: no flip
    code, out, _ = cli("run", "--target", "replay", "--replay", str(REPLAY_BEFORE), "--baseline", str(baseline))
    assert code == 0 and "Compared with baseline" in out

    # a changed replay file flips a cell
    code, out, _ = cli("run", "--target", "replay", "--replay", str(REPLAY_AFTER), "--baseline", str(baseline))
    assert code == 1
    assert "FLIP" in out and "blocked → allowed" in out

    # the baseline was not overwritten without --update-baseline
    assert json.loads(stored.read_text())["agent_version"] == saved["agent_version"]
    code, out, _ = cli("run", "--target", "replay", "--replay", str(REPLAY_AFTER), "--baseline", str(baseline),
                       "--update-baseline", "--exit-zero")
    assert code == 0
    assert load_snapshot(stored)["agent_version"] == "example-1.1.0"


def test_replay_marks_itself_as_a_mock(cli):
    code, out, _ = cli("run", "--target", "replay", "--replay", str(REPLAY_BEFORE))
    assert "Practice mock" in out


def test_invalid_snapshot_is_reported(cli, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"probes": {"x.y": {"observed": "maybe"}}}))
    code, _, err = cli("diff", str(bad), str(bad))
    assert code == 2 and "invalid observation" in err
    code, _, err = cli("diff", str(tmp_path / "missing.json"), str(bad))
    assert code == 2 and "Snapshot not found" in err
