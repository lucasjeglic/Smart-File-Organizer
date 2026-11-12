"""Scanning a folder for the files that should be organized."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional


class FileScanner:
    """Lists the files directly inside a folder.

    Only the top level is scanned: subfolders (including the category folders
    created by a previous run) are left alone. Hidden files (``.DS_Store``,
    ``.gitignore`` ...) are skipped unless ``include_hidden`` is set.
    """

    def __init__(self, include_hidden: bool = False, ignore_names: Optional[Iterable[str]] = None) -> None:
        self.include_hidden = include_hidden
        self.ignore_names = {n.lower() for n in (ignore_names or [])}

    def scan(self, folder: Path) -> List[Path]:
        folder = Path(folder).expanduser()
        if not folder.exists():
            raise FileNotFoundError(f"Folder does not exist: {folder}")
        if not folder.is_dir():
            raise NotADirectoryError(f"Not a folder: {folder}")

        files: List[Path] = []
        for entry in folder.iterdir():  # may raise PermissionError, handled by caller
            if not self.include_hidden and entry.name.startswith("."):
                continue
            if entry.name.lower() in self.ignore_names:
                continue
            if entry.is_symlink():
                continue
            if entry.is_file():
                files.append(entry)
        return sorted(files, key=lambda p: p.name.lower())
