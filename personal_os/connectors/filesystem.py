"""Filesystem-Connector: ein Ordner (z. B. Obsidian-/Notes-Vault) wird gescannt."""

from __future__ import annotations

from pathlib import Path

from ..inbox import TEXT_EXTENSIONS
from .base import Connector


class FilesystemConnector(Connector):
    """Scannt rekursiv Textdateien und erfasst neue/geaenderte Inhalte."""

    name = "filesystem"

    def sync(self) -> int:
        root = Path(self.config.get("path", "")).expanduser()
        if not root.is_dir():
            return 0
        exts = set(self.config.get("extensions") or TEXT_EXTENSIONS)
        captured = 0
        for p in sorted(root.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in exts:
                continue
            if any(part.startswith(".") for part in p.parts):
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            item = self.core.capture(
                text, kind="file", source=str(p), meta={"filename": p.name}
            )
            if not item.get("duplicate"):
                captured += 1
        self.core.store.kv_set(self.state_key(), str(len(list(root.rglob("*")))))
        return captured


class GitConnector(Connector):
    """Git-Connector: neue Commits eines Repos landen als Wissenseintraege."""

    name = "git"

    def sync(self) -> int:
        import subprocess

        path = self.config.get("path", ".")
        last = self.core.store.kv_get(self.state_key())
        cmd = [
            "git",
            "-C",
            path,
            "log",
            "--format=%H%x1f%an%x1f%ad%x1f%s%x1f%b",
            "--date=iso",
        ]
        if last:
            cmd.append(f"{last}..HEAD")
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"git log fehlgeschlagen: {exc}") from exc
        if out.returncode != 0:
            raise RuntimeError(f"git log Fehler: {out.stderr.strip()}")
        captured = 0
        raw_entries = out.stdout.strip().split("\n") if out.stdout.strip() else []
        head = subprocess.run(
            ["git", "-C", path, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()
        for line in raw_entries:
            if not line.strip():
                continue
            parts = line.split("\x1f")
            if len(parts) < 4:
                continue
            sha, author, date_, subject = parts[0], parts[1], parts[2], parts[3]
            body = parts[4] if len(parts) > 4 else ""
            content = (
                f"Commit {sha[:8]} von {author} ({date_}): {subject}\n{body}".strip()
            )
            item = self.core.capture(
                content, kind="commit", source=f"git:{path}", tags=["git"]
            )
            if not item.get("duplicate"):
                captured += 1
        if head:
            self.core.store.kv_set(self.state_key(), head)
        return captured
