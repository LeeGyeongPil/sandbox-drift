"""Command line interface: argparse sub-commands and exit codes (0 ok, 1 mismatch, 2 cannot run)."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
from pathlib import Path

from sandbox_drift import __version__, targets
from sandbox_drift.canary import Canary
from sandbox_drift.convert import claude_to_srt, load_json
from sandbox_drift.errors import ExecutorUnavailable, SandboxDriftError
from sandbox_drift.fingerprint import fingerprint_sbpl, fingerprint_settings
from sandbox_drift.i18n import SUPPORTED, resolve_lang, translator
from sandbox_drift.listener import CanaryListener
from sandbox_drift.policy import PRESETS, load_policy, parse_policy, policy_hash
from sandbox_drift.report import evaluate, exit_code, note_line, render_diff, render_run
from sandbox_drift.snapshot import (
    diff_snapshots,
    key_differences,
    load_snapshot,
    new_snapshot,
    save_snapshot,
    should_fail,
)

FORMATS = ("table", "md", "json")
_TR = translator("en")  # replaced in main() once the language is known


# ------------------------------------------------------------------ argparse

class _Formatter(argparse.HelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):  # noqa: ANN001
        # argparse passes prefix="" when it builds a sub-command's prog; only replace the default
        return super().add_usage(usage, actions, groups, _TR("arg.usage") + " " if prefix is None else prefix)


class _Parser(argparse.ArgumentParser):
    """ArgumentParser whose fixed phrases (usage, options, errors, -h) are translated."""

    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        kwargs.setdefault("formatter_class", _Formatter)
        kwargs["add_help"] = False
        kwargs["allow_abbrev"] = False
        if sys.version_info >= (3, 14):
            kwargs["color"] = False
        super().__init__(*args, **kwargs)
        self._positionals.title = _TR("arg.positionals")
        self._optionals.title = _TR("arg.options")
        self.add_argument("-h", "--help", action="help", default=argparse.SUPPRESS, help=_TR("arg.help_help"))

    def error(self, message: str):  # noqa: ANN201
        self.print_usage(sys.stderr)
        self.exit(2, _TR("arg.error_prefix") + " " + _translate_argparse(message) + "\n")


_ARG_PATTERNS = (
    (re.compile(r"the following arguments are required: (.+)"), "arg.required", ("names",)),
    (re.compile(r"argument (.+?): invalid choice: (.+?) \(choose from (.+)\)"), "arg.invalid_choice",
     ("name", "value", "choices")),
    (re.compile(r"unrecognized arguments: (.+)"), "arg.unrecognized", ("names",)),
    (re.compile(r"argument (.+?): expected one argument"), "arg.expected_one", ("name",)),
    (re.compile(r"argument (.+?): invalid (?:float|int) value: (.+)"), "arg.invalid_number", ("name", "value")),
    (re.compile(r"one of the arguments (.+) is required"), "arg.one_required", ("names",)),
    (re.compile(r"argument (.+?): not allowed with argument (.+)"), "arg.not_allowed", ("name", "other")),
)


def _translate_argparse(message: str) -> str:
    """Map argparse's fixed English sentences onto translated messages."""
    for pattern, key, names in _ARG_PATTERNS:
        found = pattern.fullmatch(message)
        if found:
            return _TR(key, **dict(zip(names, found.groups())))
    return _TR("arg.generic", message=message)


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--policy", metavar="FILE", help=_TR("opt.policy"))
    parser.add_argument("--baseline", metavar="DIR", help=_TR("opt.baseline"))
    parser.add_argument("--update-baseline", action="store_true", help=_TR("opt.update_baseline"))
    parser.add_argument("--outside-dir", metavar="DIR", help=_TR("opt.outside_dir"))
    parser.add_argument("--workdir", metavar="DIR", help=_TR("opt.workdir"))
    parser.add_argument("--format", choices=FORMATS, default="table", help=_TR("opt.format"))
    parser.add_argument("--out", metavar="FILE", help=_TR("opt.out"))
    parser.add_argument("--strict", action="store_true", help=_TR("opt.strict"))
    parser.add_argument("--exit-zero", action="store_true", help=_TR("opt.exit_zero"))
    parser.add_argument("--timeout", type=float, default=2.0, metavar="SEC", help=_TR("opt.timeout"))
    parser.add_argument("--total-timeout", type=float, default=60.0, metavar="SEC", help=_TR("opt.total_timeout"))
    parser.add_argument("--agent-version", metavar="TEXT", help=_TR("opt.agent_version"))
    parser.add_argument("--docker-socket", metavar="PATH", help=_TR("opt.docker_socket"))


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="sandbox-drift", description=_TR("help.description"), epilog=_TR("help.epilog"))
    parser.add_argument("--lang", choices=SUPPORTED, help=_TR("opt.lang"))
    parser.add_argument("--version", action="version", version=f"sandbox-drift {__version__}",
                        help=_TR("opt.version"))
    sub = parser.add_subparsers(dest="command", metavar="<command>", parser_class=_Parser, required=True)

    p_self = sub.add_parser("self", help=_TR("help.self"), description=_TR("help.self"))
    _add_common(p_self)

    p_run = sub.add_parser("run", help=_TR("help.run"), description=_TR("help.run"))
    p_run.add_argument("--target", required=True, choices=("wrap", "srt", "replay"), help=_TR("opt.target"))
    p_run.add_argument("--wrap", metavar="TEMPLATE", help=_TR("opt.wrap"))
    p_run.add_argument("--settings", metavar="FILE", help=_TR("opt.settings"))
    p_run.add_argument("--srt-bin", default="srt", metavar="PATH", help=_TR("opt.srt_bin"))
    p_run.add_argument("--replay", metavar="FILE", help=_TR("opt.replay"))
    p_run.add_argument("--python", metavar="PATH", help=_TR("opt.python"))
    _add_common(p_run)

    p_diff = sub.add_parser("diff", help=_TR("help.diff"), description=_TR("help.diff"))
    p_diff.add_argument("old", metavar="OLD.json", help=_TR("opt.old"))
    p_diff.add_argument("new", metavar="NEW.json", help=_TR("opt.new"))
    p_diff.add_argument("--strict", action="store_true", help=_TR("opt.strict"))
    p_diff.add_argument("--exit-zero", action="store_true", help=_TR("opt.exit_zero"))
    p_diff.add_argument("--format", choices=FORMATS, default="table", help=_TR("opt.format"))

    p_init = sub.add_parser("init", help=_TR("help.init"), description=_TR("help.init"))
    p_init.add_argument("--preset", choices=tuple(PRESETS), default="self-basic", help=_TR("opt.preset"))
    p_init.add_argument("--out", metavar="FILE", help=_TR("opt.init_out"))
    p_init.add_argument("--force", action="store_true", help=_TR("opt.force"))

    p_fp = sub.add_parser("fingerprint", help=_TR("help.fingerprint"), description=_TR("help.fingerprint"))
    group = p_fp.add_mutually_exclusive_group(required=True)
    group.add_argument("--settings", metavar="FILE", help=_TR("opt.fp_settings"))
    group.add_argument("--sbpl", metavar="FILE", help=_TR("opt.fp_sbpl"))

    p_conv = sub.add_parser("convert", help=_TR("help.convert"), description=_TR("help.convert"))
    p_conv.add_argument("--from-claude", required=True, metavar="FILE", help=_TR("opt.from_claude"))
    p_conv.add_argument("--fake-home", metavar="DIR", help=_TR("opt.fake_home"))
    for child in (p_self, p_run, p_diff, p_init, p_fp, p_conv):  # --lang also works after the command
        child.add_argument("--lang", choices=SUPPORTED, default=argparse.SUPPRESS, help=_TR("opt.lang"))
    return parser


def _prescan_lang(argv: list[str]) -> str | None:
    """Find ``--lang`` before the real parser exists (the parser itself needs the language)."""
    for i, arg in enumerate(argv):
        if arg == "--lang" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--lang="):
            return arg.split("=", 1)[1]
    return None


# ------------------------------------------------------------------ helpers

def _fail(exc: SandboxDriftError) -> int:
    message = _TR("err." + exc.code, **exc.params)
    if isinstance(exc, ExecutorUnavailable):
        message += " " + _TR("err.hint_self")
    print(_TR("err.prefix") + " " + message, file=sys.stderr)
    return 2


def _emit(text: str, out: str | None) -> None:
    if out:
        path = Path(out)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text + "\n", encoding="utf-8")
        except OSError as exc:
            raise SandboxDriftError("output_unwritable", path=out, detail=exc.strerror or "") from exc
        print(_TR("out.written", path=out))
    else:
        print(text)


def _use_color() -> bool:
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def _need(value: object, option: str, target: str) -> None:
    if not value:
        raise SandboxDriftError("missing_option", option=option, target=target)


def _collect(args: argparse.Namespace, target: str, policy: dict[str, str]) -> dict:
    """Run the chosen target and return a snapshot document."""
    agent = args.agent_version or os.environ.get("SANDBOX_DRIFT_AGENT_VERSION") or "unknown"
    phash = policy_hash(policy)

    if target == "replay":
        _need(args.replay, "--replay", target)
        saved = targets.load_replay(args.replay)
        doc = new_snapshot(saved.get("target", "replay"), saved["probes"],
                           agent_version=saved.get("agent_version", agent),
                           engine_version=saved.get("engine_version", "unknown"), policy_hash=phash,
                           settings_fingerprint=saved.get("settings_fingerprint", "none"), note=saved.get("note"),
                           note_code=saved.get("note_code"))
        for field in ("os", "arch"):
            doc[field] = saved.get(field, doc[field])
        return doc

    outside = args.outside_dir or str(Path.home())
    with CanaryListener() as listener:
        if target == "self":
            setup = targets.ProbeSetup(workdir=args.workdir or os.getcwd(), outside_dir=outside,
                                       canary_token="SANDBOX_DRIFT_CANARY_" + secrets.token_hex(8),
                                       listener_port=listener.port, timeout=args.timeout,
                                       docker_socket=args.docker_socket)
            probes = targets.run_self(setup)
            return new_snapshot("self", probes, agent_version=agent, policy_hash=phash)

        with Canary() as canary:
            setup = targets.ProbeSetup(workdir=args.workdir or str(canary.work_dir), outside_dir=outside,
                                       canary_token=canary.token, listener_port=listener.port,
                                       fake_home=str(canary.fake_home), timeout=args.timeout,
                                       docker_socket=args.docker_socket)
            python = args.python or targets.default_python()
            if target == "wrap":
                _need(args.wrap, "--wrap", target)
                probes = targets.run_wrap(args.wrap, setup, canary.tmp_dir, python, args.total_timeout)
                return new_snapshot("wrap", probes, agent_version=agent, policy_hash=phash)
            _need(args.settings, "--settings", target)
            settings = load_json(args.settings)
            srt_settings, warnings = claude_to_srt(settings, setup.fake_home)
            for key, code in warnings:
                print(_TR("warn." + code, key=key), file=sys.stderr)
            allow_write = srt_settings["filesystem"].setdefault("allowWrite", [])
            if setup.workdir not in allow_write:
                allow_write.append(setup.workdir)  # the positive control needs a writable work dir
            probes = targets.run_srt(args.srt_bin, srt_settings, setup, canary.tmp_dir, python, args.total_timeout)
            return new_snapshot("srt", probes, agent_version=agent,
                                engine_version=targets.engine_version(args.srt_bin), policy_hash=phash,
                                settings_fingerprint=fingerprint_settings(srt_settings))


def _run_command(args: argparse.Namespace, target: str) -> int:
    if args.policy:
        policy = load_policy(args.policy)
    else:
        policy = parse_policy(PRESETS["claude-srt" if target == "srt" else "self-basic"], "<preset>")
    doc = _collect(args, target, policy)

    changes, key_diffs, baseline_note = [], [], ""
    if args.baseline:
        path = Path(args.baseline) / f"baseline-{doc['target']}.json"
        if path.exists():
            old = load_snapshot(path)
            changes = diff_snapshots(old, doc)
            key_diffs = key_differences(old, doc)
            baseline_note = _TR("baseline.compared", path=str(path))
            if args.update_baseline:
                save_snapshot(path, doc)
                baseline_note += " " + _TR("baseline.updated")
        else:
            save_snapshot(path, doc)
            baseline_note = _TR("baseline.created", path=str(path))
    rows = evaluate(doc["probes"], policy, changes)
    notes = [_TR("diff.key_changed", field=f, old=a, new=b) for f, a, b in key_diffs]
    if target == "replay":
        notes.append(_TR("report.replay_mock"))
        if note_line(doc, _TR):
            notes.append(note_line(doc, _TR))  # our example notes are translated, a user's own note is shown raw
    text = render_run(doc, rows, args.format, _TR, color=_use_color() and not args.out, notes=notes,
                      baseline_note=baseline_note)
    _emit(text, args.out)
    code = exit_code(rows, changes, args.strict)
    return 0 if args.exit_zero else code


def _diff_command(args: argparse.Namespace) -> int:
    old, new = load_snapshot(args.old), load_snapshot(args.new)
    changes = diff_snapshots(old, new)
    text = render_diff(old, new, changes, key_differences(old, new), args.format, _TR, color=_use_color(),
                       strict=args.strict)
    print(text)
    failed = should_fail(changes, args.strict)
    return 1 if failed and not args.exit_zero else 0


def _init_command(args: argparse.Namespace) -> int:
    text = PRESETS[args.preset]
    if not args.out:
        print(text, end="")
        return 0
    path = Path(args.out)
    if path.exists() and not args.force:
        raise SandboxDriftError("init_exists", path=str(path))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise SandboxDriftError("output_unwritable", path=str(path), detail=exc.strerror or "") from exc
    print(_TR("out.written", path=str(path)))
    return 0


def _read_text(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SandboxDriftError("settings_not_found", path=path) from exc
    except OSError as exc:
        raise SandboxDriftError("file_unreadable", path=path, detail=exc.strerror or "") from exc


def _fingerprint_command(args: argparse.Namespace) -> int:
    if args.sbpl:
        print(fingerprint_sbpl(_read_text(args.sbpl)))
    else:
        print(fingerprint_settings(load_json(args.settings)))
    return 0


def _convert_command(args: argparse.Namespace) -> int:
    srt_settings, warnings = claude_to_srt(load_json(args.from_claude), args.fake_home)
    for key, code in warnings:
        print(_TR("warn." + code, key=key), file=sys.stderr)
    print(json.dumps(srt_settings, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    global _TR
    argv = list(sys.argv[1:] if argv is None else argv)
    _TR = translator(resolve_lang(_prescan_lang(argv)))
    args = build_parser().parse_args(argv)
    try:
        if args.command == "self":
            return _run_command(args, "self")
        if args.command == "run":
            return _run_command(args, args.target)
        if args.command == "diff":
            return _diff_command(args)
        if args.command == "init":
            return _init_command(args)
        if args.command == "fingerprint":
            return _fingerprint_command(args)
        return _convert_command(args)
    except SandboxDriftError as exc:
        return _fail(exc)
