"""Smart File Organizer - sort the files of a folder into category subfolders."""

from .rules import Classifier, Rule
from .scanner import FileScanner
from .history import MoveRecord, MoveHistory, Session
from .organizer import FileOrganizer, OrganizeResult, PlannedMove

__all__ = [
    "Classifier",
    "Rule",
    "FileScanner",
    "MoveRecord",
    "MoveHistory",
    "Session",
    "FileOrganizer",
    "OrganizeResult",
    "PlannedMove",
]

__version__ = "1.0.0"
