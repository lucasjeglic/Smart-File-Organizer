"""Persistent history of moved files, used for the undo function."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class MoveRecord:
    """One file move: where it came from, where it went, and when."""

    source: str
    destination: str
    time: str = field(default_factory=now_iso)


@dataclass
class Session:
    """All moves made by one "Organize" run on one folder."""

    folder: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    started: str = field(default_factory=now_iso)
    moves: List[MoveRecord] = field(default_factory=list)
    created_dirs: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "Session":
        return cls(
            folder=data["folder"],
            id=data["id"],
            started=data["started"],
            moves=[MoveRecord(**m) for m in data.get("moves", [])],
            created_dirs=list(data.get("created_dirs", [])),
        )


class MoveHistory:
    """Stores sessions in a JSON file so that undo survives a restart.

    The newest session is last. ``undo`` always works on the newest one,
    optionally restricted to a given folder.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.sessions: List[Session] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.sessions = []
            return
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            self.sessions = [Session.from_dict(s) for s in raw.get("sessions", [])]
        except (OSError, ValueError, KeyError, TypeError):
            # A corrupt history file must not stop the program. Keep a copy and start fresh.
            backup = self.path.with_suffix(".corrupt.json")
            try:
                os.replace(self.path, backup)
            except OSError:
                pass
            self.sessions = []

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"sessions": [asdict(s) for s in self.sessions]}
        # Write to a temp file and rename, so a crash never leaves half a file.
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    def add(self, session: Session) -> None:
        if session.moves:
            self.sessions.append(session)
            self.save()

    def last(self, folder: Optional[Path] = None) -> Optional[Session]:
        for session in reversed(self.sessions):
            if folder is None or Path(session.folder) == Path(folder).resolve():
                return session
        return None

    def remove(self, session: Session) -> None:
        self.sessions = [s for s in self.sessions if s.id != session.id]
        self.save()

    def replace(self, session: Session) -> None:
        """Store an updated version of a session (e.g. after a partial undo)."""
        for i, s in enumerate(self.sessions):
            if s.id == session.id:
                self.sessions[i] = session
        self.save()

    def clear(self) -> None:
        self.sessions = []
        self.save()
