"""Entry point: ``python -m smart_organizer [--cli] [--config rules.json] [folder]``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from .app_logging import setup_logging
from .organizer import FileOrganizer, default_data_dir
from .rules import Classifier


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="smart_organizer",
        description="Sort the files of a folder into subfolders by type or by custom rules.",
    )
    p.add_argument("folder", nargs="?", help="folder to organize (can also be chosen in the app)")
    p.add_argument("--cli", action="store_true", help="use the text menu instead of the GUI")
    p.add_argument("--config", type=Path, help="JSON file with custom categories and rules")
    p.add_argument("--data-dir", type=Path, help=f"where log and history are kept (default {default_data_dir()})")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    try:
        classifier = Classifier.from_config(args.config) if args.config else Classifier()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Could not load config {args.config}: {exc}", file=sys.stderr)
        return 2

    data_dir = args.data_dir or default_data_dir()
    logger = setup_logging(data_dir / "organizer.log", console=args.cli)
    organizer = FileOrganizer(classifier=classifier, data_dir=data_dir, logger=logger)
    folder = Path(args.folder) if args.folder else None

    if not args.cli:
        try:
            from .gui import launch
        except ImportError as exc:  # Python built without tkinter
            print(f"GUI not available ({exc}); starting the text menu instead.\n", file=sys.stderr)
        else:
            launch(organizer, folder)
            return 0

    from .cli import MenuApp

    MenuApp(organizer, folder).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
