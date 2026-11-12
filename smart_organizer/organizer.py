"""The core engine: plan, move, and undo."""

from __future__ import annotations

import logging
import os
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from .app_logging import setup_logging
from .history import MoveHistory, MoveRecord, Session
from .rules import Classifier
from .scanner import FileScanner

# progress(done, total, message)
ProgressCallback = Callable[[int, int, str], None]


def default_data_dir() -> Path:
    """Where the log and history live. Override with SMART_ORGANIZER_HOME."""
    env = os.environ.get("SMART_ORGANIZER_HOME")
    return Path(env).expanduser() if env else Path.home() / ".smart_file_organizer"


@dataclass
class PlannedMove:
    source: Path
    category: str

    def target_dir(self) -> Path:
        return self.source.parent / self.category


@dataclass
class OrganizeResult:
    moved: List[MoveRecord] = field(default_factory=list)
    failed: List[Tuple[str, str]] = field(default_factory=list)  # (path, reason)
    renamed: List[Tuple[str, str]] = field(default_factory=list)  # (original name, new name)
    stopped: bool = False
    dry_run: bool = False

    def summary(self) -> str:
        verb = "Would move" if self.dry_run else "Moved"
        parts = [f"{verb} {len(self.moved)} file(s)"]
        if self.renamed:
            parts.append(f"{len(self.renamed)} renamed to avoid conflicts")
        if self.failed:
            parts.append(f"{len(self.failed)} failed")
        if self.stopped:
            parts.append("stopped by user")
        return ", ".join(parts) + "."


def describe_error(exc: BaseException) -> str:
    """Turn an exception into a short message a user understands."""
    if isinstance(exc, PermissionError):
        return "Permission denied"
    if isinstance(exc, FileNotFoundError):
        return "File no longer exists"
    if isinstance(exc, IsADirectoryError):
        return "Expected a file but found a folder"
    if isinstance(exc, NotADirectoryError):
        return "A file with the category name blocks the destination folder"
    if isinstance(exc, FileExistsError):
        return "Destination already exists"
    return f"{type(exc).__name__}: {exc}"


class FileOrganizer:
    """Organizes a folder by moving each file into a category subfolder.

    Every real run is recorded in a :class:`MoveHistory` so it can be undone,
    and every move is logged with source, destination and time.
    """

    def __init__(
        self,
        classifier: Optional[Classifier] = None,
        scanner: Optional[FileScanner] = None,
        data_dir: Optional[Path] = None,
        history: Optional[MoveHistory] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.data_dir = Path(data_dir) if data_dir else default_data_dir()
        self.classifier = classifier or Classifier()
        self.scanner = scanner or FileScanner()
        self.history = history or MoveHistory(self.data_dir / "history.json")
        self.log_file = self.data_dir / "organizer.log"
        self.logger = logger or setup_logging(self.log_file)

    # ---- helpers -------------------------------------------------------

    @staticmethod
    def unique_destination(path: Path) -> Path:
        """Return ``path`` or, if taken, ``name (1).ext``, ``name (2).ext`` ..."""
        if not path.exists():
            return path
        stem, suffix = path.stem, path.suffix
        if path.name.lower().endswith(".tar.gz"):
            stem, suffix = path.name[: -len(".tar.gz")], ".tar.gz"
        n = 1
        while True:
            candidate = path.with_name(f"{stem} ({n}){suffix}")
            if not candidate.exists():
                return candidate
            n += 1

    @staticmethod
    def _short(path: Path, folder: str) -> str:
        """Path relative to the organized folder, for compact progress messages."""
        try:
            return str(Path(path).relative_to(folder))
        except ValueError:
            return str(path)

    # ---- organize ------------------------------------------------------

    def plan(self, folder: Path) -> List[PlannedMove]:
        """Work out where each file would go, without touching anything."""
        folder = Path(folder).expanduser().resolve()
        return [PlannedMove(f, self.classifier.classify(f)) for f in self.scanner.scan(folder)]

    def organize(
        self,
        folder: Path,
        dry_run: bool = False,
        stop_event: Optional[threading.Event] = None,
        progress: Optional[ProgressCallback] = None,
    ) -> OrganizeResult:
        folder = Path(folder).expanduser().resolve()
        result = OrganizeResult(dry_run=dry_run)

        try:
            planned = self.plan(folder)
        except (OSError, ValueError) as exc:
            self.logger.error("SCAN FAILED  %s  (%s)", folder, describe_error(exc))
            result.failed.append((str(folder), describe_error(exc)))
            return result

        total = len(planned)
        session = Session(folder=str(folder))
        self.logger.info(
            "%s  %s  (%d file(s))", "PREVIEW" if dry_run else "ORGANIZE START", folder, total
        )

        try:
            for i, item in enumerate(planned, start=1):
                if stop_event is not None and stop_event.is_set():
                    result.stopped = True
                    self.logger.info("STOPPED by user after %d of %d file(s)", i - 1, total)
                    break

                if dry_run:
                    dest = item.target_dir() / item.source.name
                    result.moved.append(MoveRecord(str(item.source), str(dest)))
                    if progress:
                        progress(i, total, f"{item.source.name}  ->  {item.category}/")
                    continue

                record = self._move_one(item, session, result)
                if progress:
                    if record:
                        msg = f"{item.source.name}  ->  {Path(record.destination).relative_to(folder)}"
                    else:
                        msg = f"FAILED {item.source.name}: {result.failed[-1][1]}"
                    progress(i, total, msg)
        finally:
            # Save even when interrupted, so whatever was moved can still be undone.
            if not dry_run:
                self.history.add(session)
                self.logger.info("ORGANIZE END  %s  %s", folder, result.summary())

        return result

    def _move_one(self, item: PlannedMove, session: Session, result: OrganizeResult) -> Optional[MoveRecord]:
        target_dir = item.target_dir()
        try:
            if not target_dir.exists():
                target_dir.mkdir()
                session.created_dirs.append(str(target_dir))
            elif not target_dir.is_dir():
                raise NotADirectoryError(str(target_dir))

            wanted = target_dir / item.source.name
            dest = self.unique_destination(wanted)
            if dest != wanted:
                result.renamed.append((item.source.name, dest.name))
                self.logger.warning("NAME CONFLICT  %s exists, using %s", wanted, dest.name)

            shutil.move(str(item.source), str(dest))
        except (OSError, shutil.Error) as exc:
            reason = describe_error(exc)
            result.failed.append((str(item.source), reason))
            self.logger.error("FAILED  %s  (%s)", item.source, reason)
            return None

        record = MoveRecord(source=str(item.source), destination=str(dest))
        session.moves.append(record)
        result.moved.append(record)
        self.logger.info("MOVED  %s  ->  %s", record.source, record.destination)
        return record

    # ---- undo ----------------------------------------------------------

    def undo_last(
        self,
        folder: Optional[Path] = None,
        progress: Optional[ProgressCallback] = None,
    ) -> OrganizeResult:
        """Move the files of the most recent session back where they came from.

        If ``folder`` is given, the most recent session *for that folder* is undone.
        Files that cannot be moved back stay in the history so undo can be retried.
        """
        result = OrganizeResult()
        folder = Path(folder).expanduser().resolve() if folder else None
        session = self.history.last(folder)
        if session is None:
            return result

        self.logger.info("UNDO START  session %s  (%s)", session.id, session.folder)
        remaining: List[MoveRecord] = []
        moves = list(reversed(session.moves))
        total = len(moves)

        for i, record in enumerate(moves, start=1):
            src, dst = Path(record.source), Path(record.destination)
            if not dst.exists():
                reason = "File no longer exists (moved or deleted after organizing)"
                result.failed.append((str(dst), reason))
                self.logger.warning("UNDO SKIPPED  %s  (%s)", dst, reason)
                if progress:
                    progress(i, total, f"SKIPPED {dst.name}: {reason}")
                continue
            try:
                back = self.unique_destination(src)
                if back != src:
                    result.renamed.append((src.name, back.name))
                    self.logger.warning("NAME CONFLICT  %s exists, restoring as %s", src, back.name)
                src.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dst), str(back))
            except (OSError, shutil.Error) as exc:
                reason = describe_error(exc)
                result.failed.append((str(dst), reason))
                remaining.append(record)
                self.logger.error("UNDO FAILED  %s  (%s)", dst, reason)
                if progress:
                    progress(i, total, f"FAILED {dst.name}: {reason}")
                continue

            undone = MoveRecord(source=str(dst), destination=str(back))
            result.moved.append(undone)
            self.logger.info("RESTORED  %s  ->  %s", undone.source, undone.destination)
            if progress:
                progress(i, total, f"{self._short(dst, session.folder)}  ->  {self._short(back, session.folder)}")

        # Remove category folders this session created, if they are now empty.
        for d in reversed(session.created_dirs):
            try:
                Path(d).rmdir()
            except OSError:
                pass  # not empty or already gone: leave it

        if remaining:
            session.moves = list(reversed(remaining))
            self.history.replace(session)
        else:
            self.history.remove(session)
        self.logger.info("UNDO END  session %s  %s", session.id, result.summary())
        return result
