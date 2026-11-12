"""Text menu interface."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from .organizer import FileOrganizer, OrganizeResult


class MenuApp:
    """Interactive console menu around a :class:`FileOrganizer`."""

    def __init__(
        self,
        organizer: FileOrganizer,
        folder: Optional[Path] = None,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
    ) -> None:
        self.organizer = organizer
        self.folder: Optional[Path] = Path(folder).expanduser().resolve() if folder else None
        self.input = input_fn
        self.print = output_fn
        self.running = True
        self.actions: Dict[str, Tuple[str, Callable[[], None]]] = {
            "1": ("Choose folder to organize", self.choose_folder),
            "2": ("Preview (dry run, nothing is moved)", self.preview),
            "3": ("Organize now", self.organize),
            "4": ("Undo last organize", self.undo),
            "5": ("Show history", self.show_history),
            "6": ("Show categories and rules", self.show_categories),
            "0": ("Exit", self.exit),
        }

    def run(self) -> None:
        self.print("\n=== Smart File Organizer ===")
        while self.running:
            self.print("")
            self.print(f"Current folder: {self.folder or '(none selected)'}")
            for key, (label, _) in self.actions.items():
                self.print(f"  {key}. {label}")
            try:
                choice = self.input("Choose an option: ").strip()
            except (EOFError, KeyboardInterrupt):
                self.print("")
                break
            action = self.actions.get(choice)
            if action is None:
                self.print("Invalid choice, please type one of the numbers above.")
                continue
            action[1]()

    # ---- actions -------------------------------------------------------

    def choose_folder(self) -> None:
        raw = self.input("Folder path: ").strip().strip('"').strip("'")
        if not raw:
            return
        path = Path(raw).expanduser()
        if not path.is_dir():
            self.print(f"Not an existing folder: {path}")
            return
        self.folder = path.resolve()
        self.print(f"Selected: {self.folder}")

    def _require_folder(self) -> bool:
        if self.folder is None:
            self.print("Choose a folder first (option 1).")
            return False
        return True

    def preview(self) -> None:
        if not self._require_folder():
            return
        result = self.organizer.organize(self.folder, dry_run=True)
        if not result.moved and not result.failed:
            self.print("Nothing to organize: no files found at the top level of this folder.")
            return
        for rec in result.moved:
            dest = Path(rec.destination)
            self.print(f"  {Path(rec.source).name:40}  ->  {dest.parent.name}/")
        counts = Counter(Path(r.destination).parent.name for r in result.moved)
        self.print("Summary: " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
        self._print_failures(result)

    def organize(self) -> None:
        if not self._require_folder():
            return
        try:
            files = self.organizer.plan(self.folder)
        except OSError as exc:
            self.print(f"Cannot read folder: {exc}")
            return
        if not files:
            self.print("Nothing to organize: no files found at the top level of this folder.")
            return
        answer = self.input(f"Move {len(files)} file(s) in {self.folder}? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            self.print("Cancelled.")
            return
        result = self.organizer.organize(self.folder, progress=self._progress)
        self._report(result)

    def undo(self) -> None:
        session = self.organizer.history.last(self.folder) if self.folder else self.organizer.history.last()
        if session is None:
            self.print("Nothing to undo.")
            return
        answer = self.input(
            f"Undo {len(session.moves)} move(s) made on {session.started} in {session.folder}? [y/N] "
        ).strip().lower()
        if answer not in ("y", "yes"):
            self.print("Cancelled.")
            return
        result = self.organizer.undo_last(Path(session.folder), progress=self._progress)
        self._report(result, undo=True)

    def show_history(self) -> None:
        sessions = self.organizer.history.sessions
        if not sessions:
            self.print("History is empty.")
            return
        for s in sessions:
            self.print(f"[{s.id}] {s.started}  {s.folder}  ({len(s.moves)} file(s))")
            for m in s.moves[:5]:
                self.print(f"     {m.time}  {Path(m.source).name}  ->  {m.destination}")
            if len(s.moves) > 5:
                self.print(f"     ... and {len(s.moves) - 5} more")
        self.print(f"Full log: {self.organizer.log_file}")

    def show_categories(self) -> None:
        c = self.organizer.classifier
        for name, exts in c.categories.items():
            self.print(f"  {name:14} {' '.join(exts)}")
        for rule in c.rules:
            self.print(f"  rule: '{rule.pattern}' -> {rule.folder}")
        self.print(f"  everything else -> {c.fallback}")

    def exit(self) -> None:
        self.running = False
        self.print("Goodbye.")

    # ---- output helpers ------------------------------------------------

    def _progress(self, done: int, total: int, message: str) -> None:
        self.print(f"  [{done}/{total}] {message}")

    def _print_failures(self, result: OrganizeResult) -> None:
        for path, reason in result.failed:
            self.print(f"  ! {path}: {reason}")

    def _report(self, result: OrganizeResult, undo: bool = False) -> None:
        summary = result.summary()
        if undo:
            summary = summary.replace("Moved", "Restored", 1)
        self.print(summary)
        for old, new in result.renamed:
            self.print(f"  renamed: {old} -> {new}")
        self._print_failures(result)
