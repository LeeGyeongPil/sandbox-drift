import json
import re
from pathlib import Path

import pytest

from sandbox_drift.i18n import messages, resolve_lang, translator

from conftest import OLD_SNAPSHOT, REPLAY_AFTER, REPLAY_BEFORE, ROOT

SRC = Path(__file__).resolve().parent.parent / "src" / "sandbox_drift"


def test_key_sets_are_identical():
    assert set(messages("en")) == set(messages("ko"))


def test_placeholders_match_between_languages():
    field = re.compile(r"\{(\w*)\}")
    en, ko = messages("en"), messages("ko")
    for key in en:
        assert set(field.findall(en[key])) == set(field.findall(ko[key])), key


def test_every_translated_key_used_in_code_exists():
    table = messages("en")
    used = set()
    for file in SRC.glob("*.py"):
        text = file.read_text()
        used |= set(re.findall(r'_?TR\(\s*"([\w.]+)"', text))
        used |= {"err." + code for code in re.findall(r'(?:SandboxDriftError|ExecutorUnavailable)\(\s*"(\w+)"', text)}
        used |= {"warn." + code for code in re.findall(r'warnings\.append\(\(.*?, "(\w+)"\)\)', text)}
        used |= set(re.findall(r'tr\(\s*"([\w.]+)"', text))
    assert used, "scan found nothing"
    missing = sorted(key for key in used if key not in table and not key.endswith("."))
    assert missing == []
    # keys built by concatenation in report.py: <base>.one / <base>.other
    for base in ("diff.opened", "diff.tightened"):
        assert base + ".one" in table and base + ".other" in table


def test_english_singular_has_no_plural_noun():
    en = messages("en")
    assert "cells" not in en["diff.opened.one"] and "cells" not in en["diff.tightened.one"]
    assert "cells" in en["diff.opened.other"]


@pytest.mark.parametrize("env,expected", [
    ({"SANDBOX_DRIFT_LANG": "ko", "LANG": "en_US.UTF-8"}, "ko"),
    ({"SANDBOX_DRIFT_LANG": "en", "LANG": "ko_KR.UTF-8"}, "en"),
    ({"LC_ALL": "ko_KR.UTF-8", "LC_MESSAGES": "en_US", "LANG": "en_US"}, "ko"),
    ({"LC_MESSAGES": "ko_KR", "LANG": "en_US"}, "ko"),
    ({"LANG": "ko_KR.UTF-8"}, "ko"),
    ({"LANG": "de_DE.UTF-8"}, "en"),
    ({"LANG": "C"}, "en"),
    ({}, "en"),
    ({"SANDBOX_DRIFT_LANG": "fr", "LANG": "ko_KR"}, "ko"),  # invalid tool value is ignored
])
def test_env_priority(env, expected):
    assert resolve_lang(None, env) == expected


def test_option_beats_environment():
    assert resolve_lang("en", {"SANDBOX_DRIFT_LANG": "ko"}) == "en"
    assert resolve_lang("ko", {"SANDBOX_DRIFT_LANG": "en"}) == "ko"


def test_translator_formats_params():
    assert translator("ko")("out.written", path="x") == "x 에 썼습니다"


def test_diff_headers_switch_language(cli):
    _, ko, _ = cli("--lang", "ko", "diff", str(REPLAY_BEFORE), str(REPLAY_AFTER), "--exit-zero")
    _, en, _ = cli("--lang", "en", "diff", str(REPLAY_BEFORE), str(REPLAY_AFTER), "--exit-zero")
    assert "프로브" in ko and "Probe" not in ko
    assert "Probe" in en and "프로브" not in en
    assert "열린 칸 1개" in ko and "1 cell opened" in en


def test_environment_variable_selects_language(cli, monkeypatch):
    monkeypatch.setenv("SANDBOX_DRIFT_LANG", "ko")
    _, out, _ = cli("diff", str(REPLAY_BEFORE), str(REPLAY_AFTER), "--exit-zero")
    assert "프로브" in out


def test_help_is_translated(cli):
    _, en, _ = cli("--lang", "en", "--help")
    _, ko, _ = cli("--lang", "ko", "--help")
    assert "usage:" in en and "options:" in en and "show this help message and exit" in en
    assert "사용법:" in ko and "옵션:" in ko and "usage:" not in ko and "options:" not in ko
    assert "show this help" not in ko
    _, sub, _ = cli("--lang", "ko", "run", "--help")
    assert "사용법:" in sub and "usage:" not in sub


def test_argparse_errors_are_translated(cli):
    code, _, err = cli("--lang", "ko", "run")
    assert code == 2 and "오류:" in err and "다음 인자가 필요합니다" in err and "required" not in err
    code, _, err = cli("--lang", "ko", "run", "--target", "nope")
    assert "잘못된 선택" in err and "invalid choice" not in err
    code, _, err = cli("--lang", "ko", "self", "--bogus")
    assert "알 수 없는 인자" in err and "unrecognized" not in err
    code, _, err = cli("--lang", "ko", "self", "--timeout", "abc")
    assert "숫자가 아닙니다" in err
    code, _, err = cli("--lang", "ko", "self", "--format")
    assert "값이 하나 필요합니다" in err
    code, _, err = cli("--lang", "en", "self", "--bogus")
    assert "unrecognized arguments: --bogus" in err


def test_loader_errors_are_translated(cli, tmp_path):
    bad = tmp_path / "p.toml"
    bad.write_text('[expect]\n"no.such.probe" = "block"\n')
    code, _, err = cli("--lang", "ko", "self", "--policy", str(bad))
    assert code == 2 and "알 수 없는 프로브" in err and "no.such.probe" in err
    code, _, err = cli("--lang", "en", "self", "--policy", str(bad))
    assert "unknown probe no.such.probe" in err
    bad.write_text('[expect]\n"fs.write_inside_workdir" = "maybe"\n')
    code, _, err = cli("--lang", "ko", "self", "--policy", str(bad))
    assert "잘못되었습니다" in err
    bad.write_text("not toml [")
    code, _, err = cli("--lang", "ko", "self", "--policy", str(bad))
    assert "TOML" in err and "올바른" in err
    code, _, err = cli("--lang", "ko", "self", "--policy", str(tmp_path / "gone.toml"))
    assert "찾을 수 없습니다" in err


def test_init_writes_and_protects_policy(cli, tmp_path):
    target = tmp_path / "policy.toml"
    code, out, _ = cli("init", "--preset", "claude-srt", "--out", str(target))
    assert code == 0 and "[expect]" in target.read_text()
    code, _, err = cli("init", "--out", str(target))
    assert code == 2 and "--force" in err
    code, _, _ = cli("init", "--out", str(target), "--force")
    assert code == 0
    code, out, _ = cli("init")
    assert code == 0 and out.startswith("# Expected results")


def test_every_worker_detail_code_has_both_translations():
    from sandbox_drift.worker import DETAIL_EN
    en, ko = messages("en"), messages("ko")
    for code, text in DETAIL_EN.items():
        assert en["detail." + code] == text  # worker fallback and English table never drift apart
        assert "detail." + code in ko
    codes = {key[len("detail."):] for key in en if key.startswith("detail.")}
    assert codes == set(DETAIL_EN)


def test_ko_detail_text_is_translated_in_table_and_json():
    from sandbox_drift.report import evaluate, render_run
    probes = {
        "fs.write_inside_workdir": {"observed": "allowed", "detail": "file written and removed",
                                    "detail_code": "write_ok", "detail_args": {}},
        "cred.read_fake_home_canary": {"observed": "blocked", "detail": "read denied for 4 canary file(s)",
                                       "detail_code": "read_denied", "detail_args": {"count": 4}},
        "fs.write_outside_workdir": {"observed": "blocked", "detail": "EPERM: Operation not permitted",
                                     "detail_code": "os_error",
                                     "detail_args": {"text": "EPERM: Operation not permitted"}},
        "net.localhost_listener": {"observed": "allowed", "detail": "old English text"},  # unknown, no code
        "proc.docker_socket": {"observed": "n/a", "detail": "no docker socket on this machine"},  # known, no code
    }
    rows = evaluate(probes, {})
    doc = {"target": "self"}
    for fmt in ("table", "md", "json"):
        out = render_run(doc, rows, fmt, translator("ko"))
        assert "파일을 쓰고 지웠습니다" in out and "카나리 파일 4개 읽기 거부됨" in out
        assert "file written and removed" not in out and "read denied" not in out
        assert "EPERM: Operation not permitted" in out  # raw OS text stays as is
        assert "old English text" in out  # no code and no known sentence: fall back to the stored text
        assert "이 컴퓨터에 docker 소켓이 없습니다" in out and "no docker socket" not in out  # matched back
    english = render_run(doc, rows, "table", translator("en"))
    assert "file written and removed" in english and "read denied for 4 canary file(s)" in english


# ----------------------------------------------------- shipped data must not leak English into ko output

SAMPLE_ARGS = {"count": 4, "status": 403, "readable": "False", "text": "ETIMEDOUT: timed out"}


def test_infer_detail_matches_every_english_sentence_back_to_its_code():
    from sandbox_drift.report import infer_detail
    from sandbox_drift.worker import DETAIL_EN
    for code, template in DETAIL_EN.items():
        if code == "os_error":
            continue  # matches anything, so it is never guessed
        names = re.findall(r"\{(\w+)\}", template)
        args = {name: SAMPLE_ARGS[name] for name in names}
        assert infer_detail(template.format(**args)) == (code, args), code
    assert infer_detail("EPERM: Operation not permitted") is None  # raw OS text: no code
    assert infer_detail("file written and removed, then more") is None  # only whole sentences match
    assert infer_detail("") is None


def _example_data_files():
    """Every snapshot-shaped JSON file this repository ships to users, plus the old-format fixture."""
    files = sorted((ROOT / "examples").rglob("*.json"))
    assert files, "no example data found"
    return files + [OLD_SNAPSHOT]


def _english_fragments():
    """Fixed English phrases of our own texts whose Korean translation is different."""
    en, ko = messages("en"), messages("ko")
    fragments = set()
    for key in en:
        if not key.startswith(("detail.", "note.")) or en[key] == ko[key]:
            continue  # e.g. "HTTP {status}" and "{text}" are the same in both languages
        for part in re.split(r"\{\w+\}", en[key]):
            part = part.strip(" ()=")
            if len(part) >= 6:
                fragments.add(part)
    return sorted(fragments)


def _shown_texts(fmt, out):
    """The texts a user reads. JSON: only the detail and note values (keys and codes are machine data)."""
    if fmt != "json":
        return out
    doc = json.loads(out)
    return "\n".join([entry["detail"] for entry in doc["probes"].values()] + [str(doc.get("note", ""))])


def test_example_files_carry_detail_codes_that_match_their_english_text():
    from sandbox_drift.worker import DETAIL_EN
    en, ko = messages("en"), messages("ko")
    for file in sorted((ROOT / "examples").rglob("*.json")):
        data = json.loads(file.read_text())
        for name, entry in data["probes"].items():
            code = entry.get("detail_code")
            assert code in DETAIL_EN, (file.name, name)
            assert DETAIL_EN[code].format(**entry["detail_args"]) == entry["detail"], (file.name, name)
        if data.get("note"):
            key = "note." + data["note_code"]
            assert en[key] == data["note"] and key in ko, file.name


@pytest.mark.parametrize("fmt", ["table", "md", "json"])
def test_shipped_example_data_has_no_english_fixed_text_in_ko(cli, fmt):
    fragments = _english_fragments()
    assert "file written and removed" in fragments and "read denied for" in fragments
    for file in _example_data_files():
        code, out, _ = cli("--lang", "ko", "run", "--target", "replay", "--replay", str(file), "--format", fmt)
        assert code in (0, 1), file.name
        shown = _shown_texts(fmt, out)
        leaked = [part for part in fragments if part in shown]
        assert leaked == [], (file.name, leaked)
        assert "Practice mock" not in shown  # the replay note is translated too, not repeated in English
        assert "파일을 쓰고 지웠습니다" in shown and "카나리 파일 4개 읽기 거부됨" in shown
        assert "localhost 카나리 리스너에 연결됨" in shown and "연습용 목(mock): 관찰 모양은" in shown
        assert "EPERM: Operation not permitted" in shown  # raw OS errors are never translated


def test_baseline_flip_in_ko_has_no_english_fixed_text(cli, tmp_path):
    """The README scene: save a baseline from before.json, then replay after.json against it."""
    policy = str(ROOT / "examples" / "policies" / "claude-srt.toml")
    common = ["--policy", policy, "--baseline", str(tmp_path / "base")]
    code, _, _ = cli("--lang", "ko", "run", "--target", "replay", "--replay", str(REPLAY_BEFORE), *common)
    assert code == 0
    code, out, _ = cli("--lang", "ko", "run", "--target", "replay", "--replay", str(REPLAY_AFTER), *common)
    assert code == 1 and "FLIP 1" in out
    for phrase in ("file written and removed", "read denied for", "connected to the localhost", "Practice mock"):
        assert phrase not in out, phrase
    flip_line = next(line for line in out.splitlines() if line.startswith("fs.write_outside_workdir"))
    assert "FLIP" in flip_line and "파일을 쓰고 지웠습니다" in flip_line
    _, en, _ = cli("--lang", "en", "run", "--target", "replay", "--replay", str(REPLAY_AFTER), *common)
    assert "file written and removed" in en and "Practice mock: the observation shapes" in en


def test_user_written_note_is_shown_raw_with_a_label(cli, tmp_path):
    data = json.loads(OLD_SNAPSHOT.read_text())
    data["note"] = "nightly run on the build machine"
    data["probes"]["proc.docker_socket"]["detail"] = "custom runner message"
    own = tmp_path / "own.json"
    own.write_text(json.dumps(data))
    _, ko, _ = cli("--lang", "ko", "run", "--target", "replay", "--replay", str(own))
    assert "파일에 적힌 메모(번역하지 않음): nightly run on the build machine" in ko
    assert "custom runner message" in ko  # unknown detail text: shown as stored
    _, en, _ = cli("--lang", "en", "run", "--target", "replay", "--replay", str(own))
    assert "Note from the file (not translated): nightly run on the build machine" in en
    _, js, _ = cli("--lang", "ko", "run", "--target", "replay", "--replay", str(own), "--format", "json")
    assert json.loads(js)["note"] == "nightly run on the build machine"  # JSON keeps the raw note, no label


def test_unknown_codes_fall_back_to_the_english_sentence(cli, tmp_path):
    """A file from a newer version may carry codes this version does not know."""
    data = json.loads(REPLAY_BEFORE.read_text())
    data["note_code"] = "from_a_newer_version"
    data["probes"]["fs.write_inside_workdir"]["detail_code"] = "from_a_newer_version"
    newer = tmp_path / "newer.json"
    newer.write_text(json.dumps(data))
    code, ko, _ = cli("--lang", "ko", "run", "--target", "replay", "--replay", str(newer))
    assert code == 0
    assert "파일을 쓰고 지웠습니다" in ko and "file written and removed" not in ko  # matched by its sentence
    assert "연습용 목(mock): 관찰 모양은" in ko and "Practice mock" not in ko


def test_self_mode_ko_has_no_english_detail_text(cli, fast_args):
    from sandbox_drift.worker import DETAIL_EN
    code, stdout, _ = cli("--lang", "ko", "self", *fast_args)
    assert code in (0, 1)
    assert "파일을 쓰고" in stdout or "차단" in stdout or "거부" in stdout or "없습니다" in stdout
    for code, text in DETAIL_EN.items():
        if code in ("os_error", "http_status", "connected", "canary_readable"):
            continue
        assert text not in stdout, code
