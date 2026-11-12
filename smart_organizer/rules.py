"""Classification of files into categories (destination folder names)."""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

# Default extension -> category mapping. Extensions are lower case, with the dot.
DEFAULT_CATEGORIES: Dict[str, List[str]] = {
    "Images": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp", ".svg", ".heic", ".ico"],
    "Documents": [".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md", ".pages", ".tex"],
    "Spreadsheets": [".xls", ".xlsx", ".ods", ".csv", ".numbers"],
    "Presentations": [".ppt", ".pptx", ".odp", ".key"],
    "Audio": [".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"],
    "Video": [".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".webm", ".m4v"],
    "Archives": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".tar.gz", ".tgz"],
    "Code": [".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".cs", ".html", ".css",
             ".json", ".xml", ".yaml", ".yml", ".sh", ".sql"],
    "Executables": [".exe", ".msi", ".dmg", ".pkg", ".app", ".deb", ".apk"],
    "CAD": [".dwg", ".dxf", ".step", ".stp", ".iges", ".igs", ".stl", ".rvt", ".ifc"],
}

OTHERS = "Others"


@dataclass(frozen=True)
class Rule:
    """A custom rule: files whose name matches ``pattern`` go to ``folder``.

    ``pattern`` is a shell-style wildcard (``invoice_*.pdf``, ``*report*``),
    matched case-insensitively against the file name.
    """

    pattern: str
    folder: str

    def matches(self, filename: str) -> bool:
        return fnmatch.fnmatch(filename.lower(), self.pattern.lower())


class Classifier:
    """Decides which category folder a file belongs in.

    Custom rules are checked first (in order); if none match, the file's
    extension is looked up. Unknown extensions go to ``Others``.
    """

    def __init__(
        self,
        categories: Optional[Dict[str, Iterable[str]]] = None,
        rules: Optional[Iterable[Rule]] = None,
        fallback: str = OTHERS,
    ) -> None:
        self.categories: Dict[str, List[str]] = {
            name: [self._normalise_ext(e) for e in exts]
            for name, exts in (categories or DEFAULT_CATEGORIES).items()
        }
        self.rules: List[Rule] = list(rules or [])
        self.fallback = fallback
        self._ext_map: Dict[str, str] = {}
        for name, exts in self.categories.items():
            for ext in exts:
                self._ext_map[ext] = name

    @staticmethod
    def _normalise_ext(ext: str) -> str:
        ext = ext.strip().lower()
        return ext if ext.startswith(".") else "." + ext

    @staticmethod
    def extension_of(path: Path) -> str:
        """Lower-case extension, keeping compound ones such as ``.tar.gz``."""
        suffixes = [s.lower() for s in path.suffixes]
        if len(suffixes) >= 2 and suffixes[-2] == ".tar":
            return "".join(suffixes[-2:])
        return suffixes[-1] if suffixes else ""

    def classify(self, path: Path) -> str:
        for rule in self.rules:
            if rule.matches(path.name):
                return rule.folder
        ext = self.extension_of(path)
        if ext in self._ext_map:
            return self._ext_map[ext]
        # e.g. ".tar.gz" not configured but ".gz" is
        if path.suffix.lower() in self._ext_map:
            return self._ext_map[path.suffix.lower()]
        return self.fallback

    def folder_names(self) -> List[str]:
        """Every folder name this classifier can produce."""
        names = list(self.categories) + [r.folder for r in self.rules] + [self.fallback]
        return list(dict.fromkeys(names))

    # ---- configuration -------------------------------------------------

    @classmethod
    def from_config(cls, config_path: Path) -> "Classifier":
        """Build a classifier from a JSON file.

        Format (both keys optional)::

            {
              "categories": {"Images": [".jpg", ".png"], ...},
              "rules": [{"pattern": "invoice*", "folder": "Invoices"}]
            }

        If ``categories`` is missing the defaults are used.
        """
        with open(config_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("Config file must contain a JSON object")
        categories = data.get("categories") or DEFAULT_CATEGORIES
        rules = [Rule(r["pattern"], r["folder"]) for r in data.get("rules", [])]
        return cls(categories=categories, rules=rules)
