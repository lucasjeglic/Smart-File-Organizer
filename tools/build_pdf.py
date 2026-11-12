"""Build the submission PDF from README.md (needs pandoc and Google Chrome).

Usage:
    python3 tools/build_pdf.py --author "Your Name" --repo https://github.com/you/Smart-File-Organizer
Output: Smart-File-Organizer.pdf in the repository root.
"""

from __future__ import annotations

import argparse
import datetime
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome", "chromium", "chromium-browser", "chrome",
]

CSS = """
@page { size: A4; margin: 18mm 16mm 18mm 16mm; }
body { font-family: -apple-system, "Helvetica Neue", Arial, sans-serif; font-size: 10.5pt;
       line-height: 1.45; color: #1d1d1f; max-width: none; margin: 0; }
h1 { font-size: 22pt; margin: 0 0 4pt; }
h2 { font-size: 14pt; margin: 18pt 0 6pt; padding-bottom: 3pt; border-bottom: 1px solid #ddd;
     break-after: avoid; }
h3 { font-size: 11.5pt; margin: 12pt 0 4pt; break-after: avoid; }
p, li { orphans: 3; widows: 3; }
code { font-family: Menlo, Consolas, monospace; font-size: 9pt; background: #f3f3f5;
       padding: 0 2pt; border-radius: 2pt; }
pre { background: #f6f6f8; border: 1px solid #e3e3e8; border-radius: 4pt; padding: 7pt 9pt;
      font-size: 8.3pt; line-height: 1.35; white-space: pre-wrap; word-break: break-all;
      break-inside: avoid; }
pre code { background: none; padding: 0; font-size: inherit; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0 10pt; font-size: 9.5pt;
        break-inside: auto; }
th, td { border: 1px solid #ddd; padding: 4pt 6pt; vertical-align: top; text-align: left; }
th { background: #f3f3f5; }
tr { break-inside: avoid; }
img { max-width: 100%; border: 1px solid #ccc; border-radius: 4pt; }
td img { display: block; margin-top: 4pt; }
.cover { border-left: 4pt solid #1565c0; padding: 4pt 0 4pt 10pt; margin-bottom: 14pt; color: #444; }
.cover b { color: #1d1d1f; }
a { color: #1565c0; text-decoration: none; }
"""


def find_chrome() -> str:
    for c in CHROME_CANDIDATES:
        path = c if os.path.isabs(c) else shutil.which(c)
        if path and os.path.exists(path):
            return path
    sys.exit("Google Chrome / Chromium not found.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--author", required=True)
    ap.add_argument("--repo", help="URL of the Git repository with the code")
    ap.add_argument("--out", type=Path, default=ROOT / "Smart-File-Organizer.pdf")
    args = ap.parse_args()

    if not shutil.which("pandoc"):
        sys.exit("pandoc not found (brew install pandoc).")

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    title, _, body = readme.partition("\n")
    today = datetime.date.today().strftime("%d %B %Y")
    lines = [f"<b>Internship assignment</b> &middot; EUtech Engineers",
             f"<b>Author:</b> {args.author} &middot; <b>Date:</b> {today}"]
    if args.repo:
        lines.append(f'<b>Repository:</b> <a href="{args.repo}">{args.repo}</a>')
    cover = '<div class="cover">' + "<br>".join(lines) + "</div>\n"
    if args.repo:
        body = body.replace("https://github.com/Kurai-bit/Smart-File-Organizer.git", args.repo)
    markdown = f"{title}\n\n{cover}\n{body}"

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "style.css").write_text(CSS, encoding="utf-8")
        html = tmp / "report.html"
        subprocess.run(
            ["pandoc", "-f", "gfm", "-t", "html5", "--standalone", "--embed-resources",
             f"--resource-path={ROOT}", "--css", str(tmp / "style.css"),
             "--metadata", "pagetitle=Smart File Organizer", "-o", str(html)],
            input=markdown, text=True, check=True, cwd=ROOT,
        )
        subprocess.run(
            [find_chrome(), "--headless", "--disable-gpu", "--no-pdf-header-footer",
             f"--print-to-pdf={args.out}", html.as_uri()],
            check=True, capture_output=True,
        )
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
