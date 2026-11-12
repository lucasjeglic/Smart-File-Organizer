"""Create a folder of sample files to try the organizer on (and take screenshots).

Usage:  python3 tools/make_demo_folder.py [target]     (default: ./demo-folder)
"""

import sys
from pathlib import Path

SAMPLES = [
    "holiday.jpg", "Screenshot 2026-11-03.png", "Invoice_0042.pdf", "CV.docx",
    "budget_2026.xlsx", "site_plan.dwg", "kickoff.pptx", "podcast.mp3",
    "demo.mp4", "photos.zip", "backup.tar.gz", "script.py", "notes.txt", "mystery.xyz",
]


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "demo-folder").resolve()
    target.mkdir(parents=True, exist_ok=True)
    for name in SAMPLES:
        (target / name).write_text(f"sample file {name}\n", encoding="utf-8")
    # An existing Images/holiday.jpg forces a name conflict, to show conflict handling.
    (target / "Images").mkdir(exist_ok=True)
    (target / "Images" / "holiday.jpg").write_text("an older holiday photo\n", encoding="utf-8")
    print(f"Demo folder ready: {target}  ({len(SAMPLES)} files)")


if __name__ == "__main__":
    main()
