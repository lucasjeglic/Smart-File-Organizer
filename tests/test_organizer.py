"""Tests for Smart File Organizer. Run with:  python -m unittest -v"""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from smart_organizer import Classifier, FileOrganizer, FileScanner, MoveHistory, Rule
from smart_organizer.cli import MenuApp


def touch(folder: Path, *names: str) -> None:
    for name in names:
        (folder / name).write_text(f"content of {name}", encoding="utf-8")


class TempDirTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name).resolve()
        self.folder = root / "inbox"
        self.folder.mkdir()
        self.data_dir = root / "appdata"
        self.addCleanup(self._tmp.cleanup)

    def make_organizer(self, **kwargs) -> FileOrganizer:
        return FileOrganizer(data_dir=self.data_dir, **kwargs)


class ClassifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.c = Classifier()

    def test_known_extensions(self):
        self.assertEqual(self.c.classify(Path("photo.jpg")), "Images")
        self.assertEqual(self.c.classify(Path("report.pdf")), "Documents")
        self.assertEqual(self.c.classify(Path("song.mp3")), "Audio")
        self.assertEqual(self.c.classify(Path("plan.dwg")), "CAD")

    def test_case_insensitive(self):
        self.assertEqual(self.c.classify(Path("PHOTO.JPG")), "Images")

    def test_compound_extension(self):
        self.assertEqual(Classifier.extension_of(Path("backup.tar.gz")), ".tar.gz")
        self.assertEqual(self.c.classify(Path("backup.tar.gz")), "Archives")

    def test_unknown_and_no_extension(self):
        self.assertEqual(self.c.classify(Path("data.xyz")), "Others")
        self.assertEqual(self.c.classify(Path("Makefile")), "Others")

    def test_rules_take_priority(self):
        c = Classifier(rules=[Rule("invoice*", "Invoices")])
        self.assertEqual(c.classify(Path("Invoice_2024.pdf")), "Invoices")
        self.assertEqual(c.classify(Path("other.pdf")), "Documents")

    def test_config_file(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "rules.json"
            cfg.write_text(json.dumps({
                "categories": {"Pictures": ["jpg", ".PNG"]},
                "rules": [{"pattern": "*draft*", "folder": "Drafts"}],
            }))
            c = Classifier.from_config(cfg)
        self.assertEqual(c.classify(Path("a.png")), "Pictures")
        self.assertEqual(c.classify(Path("my_draft.png")), "Drafts")
        self.assertEqual(c.classify(Path("a.pdf")), "Others")


class ScannerTests(TempDirTest):
    def test_only_top_level_visible_files(self):
        touch(self.folder, "a.txt", "b.jpg", ".DS_Store")
        (self.folder / "sub").mkdir()
        touch(self.folder / "sub", "nested.txt")
        names = [p.name for p in FileScanner().scan(self.folder)]
        self.assertEqual(names, ["a.txt", "b.jpg"])

    def test_missing_folder(self):
        with self.assertRaises(FileNotFoundError):
            FileScanner().scan(self.folder / "nope")

    def test_not_a_folder(self):
        touch(self.folder, "a.txt")
        with self.assertRaises(NotADirectoryError):
            FileScanner().scan(self.folder / "a.txt")


class OrganizeTests(TempDirTest):
    def test_moves_files_into_categories(self):
        touch(self.folder, "photo.jpg", "doc.pdf", "song.mp3", "weird.xyz")
        result = self.make_organizer().organize(self.folder)

        self.assertEqual(len(result.moved), 4)
        self.assertFalse(result.failed)
        self.assertTrue((self.folder / "Images" / "photo.jpg").exists())
        self.assertTrue((self.folder / "Documents" / "doc.pdf").exists())
        self.assertTrue((self.folder / "Audio" / "song.mp3").exists())
        self.assertTrue((self.folder / "Others" / "weird.xyz").exists())
        self.assertFalse((self.folder / "photo.jpg").exists())

    def test_running_twice_leaves_category_folders_alone(self):
        touch(self.folder, "photo.jpg")
        org = self.make_organizer()
        org.organize(self.folder)
        result = org.organize(self.folder)
        self.assertEqual(result.moved, [])
        self.assertTrue((self.folder / "Images" / "photo.jpg").exists())

    def test_dry_run_moves_nothing(self):
        touch(self.folder, "photo.jpg")
        org = self.make_organizer()
        result = org.organize(self.folder, dry_run=True)
        self.assertEqual(len(result.moved), 1)
        self.assertTrue((self.folder / "photo.jpg").exists())
        self.assertFalse((self.folder / "Images").exists())
        self.assertEqual(org.history.sessions, [])

    def test_log_contains_source_destination_and_time(self):
        touch(self.folder, "photo.jpg")
        org = self.make_organizer()
        org.organize(self.folder)
        for h in org.logger.handlers:
            h.flush()
        log = org.log_file.read_text(encoding="utf-8")
        line = next(l for l in log.splitlines() if "MOVED" in l)
        self.assertIn(str(self.folder / "photo.jpg"), line)
        self.assertIn(str(self.folder / "Images" / "photo.jpg"), line)
        self.assertRegex(line, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")

    def test_name_conflict_gets_unique_name(self):
        (self.folder / "Images").mkdir()
        touch(self.folder / "Images", "photo.jpg", "photo (1).jpg")
        touch(self.folder, "photo.jpg")
        result = self.make_organizer().organize(self.folder)
        self.assertEqual(result.renamed, [("photo.jpg", "photo (2).jpg")])
        self.assertTrue((self.folder / "Images" / "photo (2).jpg").exists())
        # the existing files were not overwritten
        self.assertEqual((self.folder / "Images" / "photo.jpg").read_text(), "content of photo.jpg")

    def test_file_blocking_category_folder_is_reported(self):
        # A file with no extension called "Others" belongs in the folder "Others",
        # which cannot be created because the file itself occupies that name.
        touch(self.folder, "Others", "photo.jpg")
        result = self.make_organizer().organize(self.folder)
        self.assertEqual([p for p, _ in result.failed], [str(self.folder / "Others")])
        self.assertTrue((self.folder / "Others").is_file())
        self.assertTrue((self.folder / "Images" / "photo.jpg").exists())  # others still processed

    @unittest.skipIf(sys.platform == "win32" or os.geteuid() == 0, "needs POSIX permissions as non-root")
    def test_permission_error_is_reported_and_others_continue(self):
        docs = self.folder / "Documents"
        docs.mkdir()
        docs.chmod(stat.S_IRUSR | stat.S_IXUSR)  # read-only folder
        self.addCleanup(docs.chmod, stat.S_IRWXU)
        touch(self.folder, "doc.pdf", "photo.jpg")

        result = self.make_organizer().organize(self.folder)

        self.assertEqual(result.failed, [(str(self.folder / "doc.pdf"), "Permission denied")])
        self.assertTrue((self.folder / "doc.pdf").exists())
        self.assertTrue((self.folder / "Images" / "photo.jpg").exists())

    def test_missing_folder_is_reported_not_raised(self):
        result = self.make_organizer().organize(self.folder / "missing")
        self.assertEqual(len(result.failed), 1)

    def test_stop_event(self):
        touch(self.folder, *[f"f{i}.txt" for i in range(10)])
        stop = threading.Event()

        def progress(done, total, msg):
            if done == 3:
                stop.set()

        result = self.make_organizer().organize(self.folder, stop_event=stop, progress=progress)
        self.assertTrue(result.stopped)
        self.assertEqual(len(result.moved), 3)
        self.assertEqual(len(list((self.folder / "Documents").iterdir())), 3)


class UndoTests(TempDirTest):
    def test_undo_restores_everything_and_removes_empty_folders(self):
        touch(self.folder, "photo.jpg", "doc.pdf")
        org = self.make_organizer()
        org.organize(self.folder)
        result = org.undo_last()

        self.assertEqual(len(result.moved), 2)
        self.assertTrue((self.folder / "photo.jpg").exists())
        self.assertTrue((self.folder / "doc.pdf").exists())
        self.assertFalse((self.folder / "Images").exists())
        self.assertFalse((self.folder / "Documents").exists())
        self.assertEqual(org.history.sessions, [])

    def test_undo_keeps_preexisting_folders(self):
        (self.folder / "Images").mkdir()
        touch(self.folder, "photo.jpg")
        org = self.make_organizer()
        org.organize(self.folder)
        org.undo_last()
        self.assertTrue((self.folder / "Images").is_dir())

    def test_undo_survives_restart(self):
        touch(self.folder, "photo.jpg")
        self.make_organizer().organize(self.folder)
        fresh = self.make_organizer()  # new instance reads history.json
        fresh.undo_last(self.folder)
        self.assertTrue((self.folder / "photo.jpg").exists())

    def test_undo_only_last_session(self):
        org = self.make_organizer()
        touch(self.folder, "a.jpg")
        org.organize(self.folder)
        touch(self.folder, "b.jpg")
        org.organize(self.folder)
        org.undo_last()
        self.assertTrue((self.folder / "b.jpg").exists())
        self.assertTrue((self.folder / "Images" / "a.jpg").exists())

    def test_undo_when_original_name_is_taken(self):
        touch(self.folder, "photo.jpg")
        org = self.make_organizer()
        org.organize(self.folder)
        touch(self.folder, "photo.jpg")  # a new file appears with the same name
        result = org.undo_last()
        self.assertEqual(result.renamed, [("photo.jpg", "photo (1).jpg")])
        self.assertTrue((self.folder / "photo (1).jpg").exists())

    def test_undo_when_file_was_deleted(self):
        touch(self.folder, "photo.jpg", "doc.pdf")
        org = self.make_organizer()
        org.organize(self.folder)
        (self.folder / "Images" / "photo.jpg").unlink()
        result = org.undo_last()
        self.assertEqual(len(result.moved), 1)
        self.assertEqual(len(result.failed), 1)
        self.assertTrue((self.folder / "doc.pdf").exists())

    def test_nothing_to_undo(self):
        result = self.make_organizer().undo_last()
        self.assertEqual(result.moved, [])


class HistoryTests(TempDirTest):
    def test_corrupt_history_is_backed_up(self):
        self.data_dir.mkdir()
        (self.data_dir / "history.json").write_text("{ not json")
        h = MoveHistory(self.data_dir / "history.json")
        self.assertEqual(h.sessions, [])
        self.assertTrue((self.data_dir / "history.corrupt.json").exists())


class MenuTests(TempDirTest):
    def run_menu(self, *inputs: str):
        answers = iter(inputs)
        out = []
        app = MenuApp(self.make_organizer(), input_fn=lambda _: next(answers), output_fn=out.append)
        app.run()
        return "\n".join(out)

    def test_choose_organize_undo_exit(self):
        touch(self.folder, "photo.jpg")
        out = self.run_menu("1", str(self.folder), "3", "y", "4", "y", "0")
        self.assertIn("Moved 1 file(s)", out)
        self.assertIn("Restored 1 file(s)", out)
        self.assertTrue((self.folder / "photo.jpg").exists())

    def test_invalid_input(self):
        out = self.run_menu("9", "1", str(self.folder / "missing"), "3", "0")
        self.assertIn("Invalid choice", out)
        self.assertIn("Not an existing folder", out)
        self.assertIn("Choose a folder first", out)


if __name__ == "__main__":
    unittest.main()
