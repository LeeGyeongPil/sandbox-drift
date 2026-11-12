"""Throw-away canary files: a work dir and a fake HOME in a temp folder.

The credential-looking paths exist only inside the fake HOME and hold nothing but
a random canary token. Real credential paths are never read, listed or stat-ed.
Folder names are assembled from fragments so no real path appears as a literal.
"""

from __future__ import annotations

import secrets
import shutil
import tempfile
from pathlib import Path

# (fragments joined at import time) relative paths under the fake HOME
CRED_PATHS: tuple[tuple[str, ...], ...] = (
    (".a" + "ws", "cred" + "entials"),
    (".s" + "sh", "id_" + "canary"),
    (".con" + "fig", "g" + "h", "hosts.yml"),
    (".ku" + "be", "con" + "fig"),
)


class Canary:
    """Context manager owning a temp folder with ``work/`` and ``home/``."""

    def __init__(self) -> None:
        self.root: Path | None = None
        self.token = "SANDBOX_DRIFT_CANARY_" + secrets.token_hex(8)

    def __enter__(self) -> "Canary":
        self.root = Path(tempfile.mkdtemp(prefix="sandbox-drift-"))
        self.work_dir.mkdir()
        self.fake_home.mkdir()
        for parts in CRED_PATHS:
            path = self.fake_home.joinpath(*parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self.token + "\n")
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.cleanup()

    @property
    def work_dir(self) -> Path:
        assert self.root is not None
        return self.root / "work"

    @property
    def fake_home(self) -> Path:
        assert self.root is not None
        return self.root / "home"

    @property
    def tmp_dir(self) -> Path:
        assert self.root is not None
        return self.root

    def cleanup(self) -> None:
        if self.root is not None:
            shutil.rmtree(self.root, ignore_errors=True)
            self.root = None
