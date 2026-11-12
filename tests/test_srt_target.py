import json
from pathlib import Path

from sandbox_drift.convert import claude_to_srt, load_json

from conftest import FIXTURES

FAKE_SRT = """\
import json, os, subprocess, sys
if sys.argv[1:] == ['--version']:
    print('9.9.9')
    sys.exit(0)
argv = sys.argv[1:]
settings_path = argv[argv.index('--settings') + 1]
command = argv[argv.index('-c') + 1]
record = {'argv': argv, 'home': os.environ['HOME'], 'settings': json.load(open(settings_path))}
json.dump(record, open(%r, 'w'))
sys.exit(subprocess.run(command, shell=True).returncode)
"""


def test_convert_claude_settings(cli):
    srt, warnings = claude_to_srt(load_json(FIXTURES / "claude-settings.json"), "/fake/home")
    assert srt["network"] == {"allowedDomains": ["example.com"], "allowLocalBinding": True}
    assert srt["filesystem"]["allowWrite"] == ["/fake/home/scratch", "/opt/shared"]
    assert srt["filesystem"]["denyRead"] == ["/fake/home/.canary-secrets"]
    keys = dict(warnings)
    assert keys["sandbox.network.futureOption"] == "unknown_key"
    assert keys["sandbox.enabled"] == "not_translated"
    assert "sandbox.filesystem" not in keys

    code, out, err = cli("convert", "--from-claude", str(FIXTURES / "claude-settings.json"))
    assert code == 0
    printed = json.loads(out)
    assert "network" in printed and "filesystem" in printed
    assert "futureOption" in err  # warning on stderr, setting left out


def test_srt_settings_pass_through():
    srt, warnings = claude_to_srt({"network": {"allowedDomains": []}, "filesystem": {"allowWrite": ["."]}})
    assert srt["filesystem"]["allowWrite"] == ["."] and warnings == []


def test_convert_rejects_files_without_sandbox_block(cli, tmp_path):
    bad = tmp_path / "s.json"
    bad.write_text('{"model": "x"}')
    code, _, err = cli("convert", "--from-claude", str(bad))
    assert code == 2 and "No sandbox block" in err


def test_srt_argv_and_env_with_fake_srt(cli, make_script, tmp_path, fast_args):
    record = tmp_path / "record.json"
    srt = make_script("fake-srt", FAKE_SRT % str(record))
    out = tmp_path / "out.json"
    code, _, err = cli("run", "--target", "srt", "--settings", str(FIXTURES / "claude-settings.json"),
                       "--srt-bin", str(srt), "--format", "json", "--out", str(out), *fast_args)
    assert code in (0, 1), err
    data = json.loads(out.read_text())
    assert data["target"] == "srt" and data["engine_version"] == "9.9.9"
    assert data["settings_fingerprint"].startswith("sha256:")
    assert len(data["probes"]) == 8

    rec = json.loads(record.read_text())
    argv = rec["argv"]
    assert argv[0] == "--settings" and argv[2] == "-c"
    assert "-I" in argv[3] and "worker.py" in argv[3] and "config.json" in argv[3]
    home = Path(rec["home"])
    assert home.name == "home" and home.parent.name.startswith("sandbox-drift-")
    # the settings given to srt use the fake HOME and include the work dir for the positive control
    assert rec["settings"]["filesystem"]["allowWrite"][0] == str(home / "scratch")
    assert str(tmp_path / "workdir") in rec["settings"]["filesystem"]["allowWrite"]
    assert rec["settings"]["filesystem"]["denyRead"] == [str(home / ".canary-secrets")]


def test_missing_srt_is_exit_2(cli, tmp_path, fast_args):
    code, _, err = cli("run", "--target", "srt", "--settings", str(FIXTURES / "claude-settings.json"),
                       "--srt-bin", str(tmp_path / "no-srt"), *fast_args)
    assert code == 2 and "sandbox-drift self" in err
