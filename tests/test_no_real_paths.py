"""No real user paths or credential folder names may appear as literals in the repository."""

from pathlib import Path

from sandbox_drift.policy import PRESETS

ROOT = Path(__file__).resolve().parent.parent

# Patterns are assembled from fragments so this file does not contain them itself.
FORBIDDEN = [
    "/Us" + "ers/",
    "/Vol" + "umes/",
    ".a" + "ws",
    ".s" + "sh",
    ".gnu" + "pg",
    ".ku" + "be",
    "/.dock" + "er",
    ".net" + "rc",
    ".git-cred" + "entials",
    "config/g" + "h",
]
SCANNED = (".py", ".toml", ".json", ".md", ".yml", ".sb")
SKIP_PARTS = {".git", ".venv", "__pycache__", ".pytest_cache", "uv.lock", "docs"}


def test_no_forbidden_literals():
    offenders = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in SCANNED:
            continue
        if SKIP_PARTS & set(path.relative_to(ROOT).parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in FORBIDDEN:
            if pattern in text:
                offenders.append((str(path.relative_to(ROOT)), pattern))
    assert offenders == []


def test_example_policies_match_presets():
    for name, text in PRESETS.items():
        assert (ROOT / "examples" / "policies" / f"{name}.toml").read_text() == text


def test_replay_files_are_labelled_as_mock():
    import json

    for name in ("before", "after"):
        data = json.loads((ROOT / "examples" / "replay" / f"{name}.json").read_text())
        assert "Practice mock" in data["note"]
