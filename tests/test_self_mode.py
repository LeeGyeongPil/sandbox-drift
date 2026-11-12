import json

from sandbox_drift.classify import OBSERVATIONS
from sandbox_drift.worker import PROBE_IDS

from conftest import SELF_POLICY


def test_self_mode_runs_all_probes(cli, tmp_path, fast_args):
    out = tmp_path / "self.json"
    code, stdout, stderr = cli("self", "--policy", str(SELF_POLICY), "--format", "json", "--out", str(out),
                               *fast_args)
    assert code in (0, 1), stderr  # 2 would mean "could not run"
    data = json.loads(out.read_text())
    assert set(data["probes"]) == set(PROBE_IDS)
    assert len(data["probes"]) == 8
    assert all(p["observed"] in OBSERVATIONS for p in data["probes"].values())
    # self mode cannot swap HOME, so the credential canary is skipped
    assert data["probes"]["cred.read_fake_home_canary"]["observed"] == "n/a"
    assert data["probes"]["cred.read_fake_home_canary"]["verdict"] == "SKIP"
    # no canary file may be left behind in the folders we probed
    assert list((tmp_path / "outside").iterdir()) == []
    assert list((tmp_path / "workdir").iterdir()) == []


def test_self_mode_table_output(cli, fast_args):
    code, stdout, _ = cli("self", *fast_args)
    assert code in (0, 1)
    assert "fs.write_outside_workdir" in stdout
    assert "Bash/command boundary" in stdout
