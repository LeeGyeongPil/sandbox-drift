from sandbox_drift.fingerprint import fingerprint_sbpl, fingerprint_settings

from conftest import FIXTURES


def read(name):
    return (FIXTURES / name).read_text()


def test_sbpl_ignores_random_tags_ports_and_temp_paths():
    assert fingerprint_sbpl(read("profile-a1.sb")) == fingerprint_sbpl(read("profile-a2.sb"))


def test_sbpl_changes_when_a_rule_changes():
    assert fingerprint_sbpl(read("profile-a1.sb")) != fingerprint_sbpl(read("profile-b.sb"))


def test_settings_fingerprint_ignores_order_and_spacing():
    assert fingerprint_settings({"a": 1, "b": {"x": [1, 2], "y": 2}}) == \
        fingerprint_settings({"b": {"y": 2, "x": [1, 2]}, "a": 1})
    assert fingerprint_settings({"a": 1}) != fingerprint_settings({"a": 2})
    assert fingerprint_settings({"a": 1}).startswith("sha256:")


def test_fingerprint_command(cli):
    code1, out1, _ = cli("fingerprint", "--sbpl", str(FIXTURES / "profile-a1.sb"))
    code2, out2, _ = cli("fingerprint", "--sbpl", str(FIXTURES / "profile-a2.sb"))
    assert code1 == code2 == 0
    assert out1 == out2 and out1.startswith("sha256:")
    code, out3, _ = cli("fingerprint", "--settings", str(FIXTURES / "claude-settings.json"))
    assert code == 0 and out3.startswith("sha256:")
    code, _, err = cli("fingerprint")
    assert code == 2 and "required" in err
