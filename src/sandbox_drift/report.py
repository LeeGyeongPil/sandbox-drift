"""Per-probe verdicts and the three output formats (table, Markdown, JSON)."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Callable

from sandbox_drift.classify import ALLOWED, BLOCKED, ERROR, NOT_APPLICABLE
from sandbox_drift.i18n import messages
from sandbox_drift.snapshot import CHANGED, OPENED, TIGHTENED, Change, should_fail
from sandbox_drift.worker import DETAIL_EN

Translator = Callable[..., str]

PASS, FAIL, FLIP, ERR, SKIP, INFO = "PASS", "FAIL", "FLIP", "ERROR", "SKIP", "INFO"
ARROW = "\u2192"

_COLORS = {PASS: "32", FAIL: "31", FLIP: "1;31", ERR: "33", SKIP: "90", INFO: "36",
           "TIGHTENED": "32", "CHANGED": "33"}


@dataclass
class Row:
    probe: str
    expect: str
    observed: str
    detail: str
    verdict: str
    change: str = ""  # "blocked -> allowed" when the baseline differs, else ""
    detail_code: str = ""  # machine key of the detail text; "" for old snapshots
    detail_args: dict | None = None


def judge(expect: str, observed: str) -> str:
    """Compare one expectation with one observation."""
    if observed == NOT_APPLICABLE:
        return SKIP
    if expect == "info":
        return INFO
    if observed == ERROR:
        return ERR
    wanted = BLOCKED if expect == "block" else ALLOWED
    return PASS if observed == wanted else FAIL


def _template_pattern(template: str) -> re.Pattern[str]:
    """'read denied for {count} canary file(s)' -> regex with one named group per placeholder."""
    parts = re.split(r"\{(\w+)\}", template)
    # 짝수 칸은 고정 문구(글자 그대로 일치), 홀수 칸은 자리표시자 이름(아무 글자나 받는다)
    body = "".join(re.escape(part) if i % 2 == 0 else f"(?P<{part}>.+?)" for i, part in enumerate(parts))
    return re.compile(body)


# os_error ("{text}") would match any text, so it is never guessed: unknown text is shown raw anyway.
_DETAIL_PATTERNS = [(code, _template_pattern(text)) for code, text in DETAIL_EN.items() if code != "os_error"]


def infer_detail(text: str) -> tuple[str, dict] | None:
    """Recover ``(code, args)`` from the English detail of a file written without detail codes.

    Snapshots and replay files from before the codes existed only store the English sentence.
    The worker builds that sentence from ``DETAIL_EN``, so the sentence can be matched back.
    """
    for code, pattern in _DETAIL_PATTERNS:
        found = pattern.fullmatch(text)
        if found:
            # 숫자 인자(count, status)는 워커가 int 로 내므로 똑같이 되돌린다
            args = {key: int(value) if value.isdigit() else value for key, value in found.groupdict().items()}
            return code, args
    return None


def evaluate(probes: dict[str, dict], policy: dict[str, str], changes: list[Change] | None = None) -> list[Row]:
    """Build rows. A baseline change from blocked to allowed is a FLIP unless the policy wants it open."""
    by_probe = {c.probe: c for c in (changes or [])}
    rows = []
    for name, entry in probes.items():
        expect = policy.get(name, "info")
        verdict = judge(expect, entry["observed"])
        change = by_probe.get(name)
        text = ""
        if change is not None:
            text = f"{change.old} {ARROW} {change.new}"
            if change.kind == OPENED and expect != "allow":
                verdict = FLIP
        detail = entry.get("detail", "")
        code, args = entry.get("detail_code", ""), entry.get("detail_args") or {}
        if code not in DETAIL_EN:
            # 코드가 없는(또는 모르는) 옛 파일: 영어 원문을 코드로 되돌려 본다. 못 맞추면 원문 그대로 보여 준다.
            code, args = infer_detail(detail) or (code, args)
        rows.append(Row(name, expect, entry["observed"], detail, verdict, text, code, args))
    return rows


def exit_code(rows: list[Row], changes: list[Change] | None = None, strict: bool = False) -> int:
    """0 everything matches, 1 a mismatch or regression (2 is reserved for 'could not run')."""
    if any(row.verdict in (FAIL, FLIP, ERR) for row in rows):
        return 1
    if strict and changes:
        return 1 if should_fail(changes, True) else 0
    return 0


def count_verdicts(rows: list[Row]) -> dict[str, int]:
    counts = {PASS: 0, FAIL: 0, FLIP: 0, ERR: 0, SKIP: 0, INFO: 0}
    for row in rows:
        counts[row.verdict] += 1
    return counts


# ---------------------------------------------------------------- rendering

def display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * (width - display_width(text))


def _paint(text: str, verdict: str, color: bool) -> str:
    if color and verdict in _COLORS:
        return f"\x1b[{_COLORS[verdict]}m{text}\x1b[0m"
    return text


def _table(headers: list[str], body: list[list[str]], color_col: int | None, color: bool) -> str:
    widths = [max(display_width(h), *(display_width(r[i]) for r in body)) if body else display_width(h)
              for i, h in enumerate(headers)]
    lines = ["  ".join(_pad(h, widths[i]) for i, h in enumerate(headers)).rstrip(),
             "  ".join("-" * w for w in widths)]
    for row in body:
        cells = [_pad(cell, widths[i]) for i, cell in enumerate(row)]
        if color_col is not None:
            cells[color_col] = _paint(cells[color_col], row[color_col], color)
        lines.append("  ".join(cells).rstrip())
    return "\n".join(lines)


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _md_table(headers: list[str], body: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(_md_escape(cell) for cell in row) + " |" for row in body]
    return "\n".join(out)


def _identity_line(doc: dict, tr: Translator) -> str:
    return tr("report.identity", target=doc.get("target", "-"), agent=doc.get("agent_version", "-"),
              engine=doc.get("engine_version", "-"), os=doc.get("os", "-"), arch=doc.get("arch", "-"))


def detail_text(row: Row, tr: Translator) -> str:
    """Translate the detail of a row; fall back to the stored English text (old snapshots, unknown codes)."""
    if row.detail_code:
        try:
            return tr("detail." + row.detail_code, **(row.detail_args or {}))
        except (KeyError, IndexError):
            return row.detail
    return row.detail


# English note text -> note code, for replay files that only store the sentence (no note_code).
_NOTE_CODES = {text: key[len("note."):] for key, text in messages("en").items() if key.startswith("note.")}


def note_text(doc: dict, tr: Translator) -> str | None:
    """The translated note of a file this tool ships (by ``note_code`` or its exact English text), else None."""
    # note_code 를 먼저, 모르는 코드면 영어 원문으로 한 번 더 찾는다
    for code in (doc.get("note_code"), _NOTE_CODES.get(str(doc.get("note") or ""))):
        if code:
            try:
                return tr("note." + code)
            except KeyError:
                continue
    return None


def note_line(doc: dict, tr: Translator) -> str:
    """The note as a report line. A free-text note written by a user is data: shown raw, labelled as such."""
    known = note_text(doc, tr)
    if known:
        return known
    raw = str(doc.get("note") or "")
    return tr("report.note_raw", note=raw) if raw else ""


def render_run(doc: dict, rows: list[Row], fmt: str, tr: Translator, *, color: bool = False,
               notes: list[str] | None = None, baseline_note: str = "") -> str:
    """Render a ``run``/``self`` result. ``doc`` is the snapshot dictionary."""
    counts = count_verdicts(rows)
    if fmt == "json":
        payload = dict(doc)
        payload["probes"] = {
            r.probe: {"observed": r.observed, "detail": detail_text(r, tr), "expect": r.expect, "verdict": r.verdict,
                      "change": r.change}
            | ({"detail_code": r.detail_code, "detail_args": r.detail_args or {}} if r.detail_code else {})
            for r in rows}
        if note_text(doc, tr):
            payload["note"] = note_text(doc, tr)  # same rule as detail: our own texts follow --lang
        payload["summary"] = counts
        return json.dumps(payload, indent=2, ensure_ascii=False)
    headers = [tr("col.probe"), tr("col.expect"), tr("col.observed"), tr("col.verdict"), tr("col.change"),
               tr("col.detail")]
    body = [[r.probe, r.expect, r.observed, r.verdict, r.change, detail_text(r, tr)] for r in rows]
    summary = tr("report.summary", **{k.lower(): v for k, v in counts.items()})
    extras = [baseline_note] if baseline_note else []
    extras += notes or []
    if fmt == "md":
        parts = ["### " + tr("report.title"), "", _identity_line(doc, tr), "", _md_table(headers, body), "", summary]
        parts += ["", *["- " + e for e in extras]] if extras else []
        parts += ["", "_" + tr("report.scope") + "_"]
        return "\n".join(parts)
    parts = [tr("report.title"), _identity_line(doc, tr), "", _table(headers, body, 3, color), "", summary]
    parts += extras
    parts += ["", tr("report.scope")]
    return "\n".join(parts)


def render_diff(old: dict, new: dict, changes: list[Change], key_diffs: list[tuple[str, str, str]], fmt: str,
                tr: Translator, *, color: bool = False, strict: bool = False) -> str:
    labels = {OPENED: FLIP, TIGHTENED: "TIGHTENED", CHANGED: "CHANGED"}
    opened = sum(1 for c in changes if c.kind == OPENED)
    tightened = sum(1 for c in changes if c.kind == TIGHTENED)
    if fmt == "json":
        return json.dumps({
            "changes": [{"probe": c.probe, "old": c.old, "new": c.new, "kind": c.kind} for c in changes],
            "key_differences": [{"field": f, "old": a, "new": b} for f, a, b in key_diffs],
            "opened": opened, "tightened": tightened, "strict": strict}, indent=2, ensure_ascii=False)
    headers = [tr("col.probe"), tr("col.verdict"), tr("col.change")]
    body = [[c.probe, labels[c.kind], f"{c.old} {ARROW} {c.new}"] for c in changes]
    lines = []
    for field, a, b in key_diffs:
        lines.append(tr("diff.key_changed", field=field, old=a, new=b))
    if not changes:
        summary = tr("diff.no_changes")
    else:
        summary = tr("diff.summary", opened=tr_plural(tr, "diff.opened", opened),
                     tightened=tr_plural(tr, "diff.tightened", tightened))
    if fmt == "md":
        parts = ["### " + tr("diff.title"), ""]
        parts += ["- " + line for line in lines] + [""] if lines else []
        parts += [_md_table(headers, body), ""] if changes else []
        parts += [summary]
        return "\n".join(parts)
    parts = [tr("diff.title")] + lines + [""]
    if changes:
        parts += [_table(headers, body, 1, color), ""]
    parts.append(summary)
    return "\n".join(parts)


def tr_plural(tr: Translator, base: str, count: int) -> str:
    """Pick ``<base>.one`` for exactly one, ``<base>.other`` otherwise."""
    return tr(base + (".one" if count == 1 else ".other"), n=count)
