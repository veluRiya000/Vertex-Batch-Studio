from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from backend.config import Settings
from backend.repository import Repository
from backend.assets import Assets
from .fakes import image_bytes


class FolderImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.assets = Assets(Repository(Settings(self.root, self.root / "data")))
        self.source = self.root / "人设参考"
        self.source.mkdir()
        (self.source / "人物.PNG").write_bytes(image_bytes((1, 2, 3)))
        (self.source / "说明.txt").write_text("ignore", encoding="utf-8")
        (self.source / "子目录").mkdir()
        (self.source / "子目录/不导入.png").write_bytes(image_bytes((4, 5, 6)))

    def tearDown(self):
        self.temp.cleanup()

    def test_selection_only_reads_names_and_can_be_discarded(self):
        before = sorted(p.relative_to(self.root / "data").as_posix()
                        for p in (self.root / "data").rglob("*"))
        result = self.assets.scan_folder(str(self.source))
        self.assertEqual(result["label"], "人设参考")
        self.assertEqual(result["files"], ["人物.PNG"])
        self.assertEqual(result["skipped"], 1)
        after = sorted(p.relative_to(self.root / "data").as_posix()
                       for p in (self.root / "data").rglob("*"))
        self.assertEqual(before, after)

    def test_local_import_skips_corrupt_images_and_retry_deduplicates(self):
        categories = self.assets.add_category(self.source.name)
        category = next(c["id"] for c in categories if c["label"] == self.source.name)
        (self.source / "坏图.png").write_text("invalid", encoding="utf-8")
        result = self.assets.import_folder_files(str(self.source), category, ["人物.PNG", "坏图.png"])
        self.assertEqual(len(result["references"]), 1)
        self.assertEqual(result["references"][0]["category_id"], category)
        self.assertEqual(result["failed"][0]["name"], "坏图.png")
        retry = self.assets.import_folder_files(str(self.source), category, ["人物.PNG"])
        self.assertEqual(retry["references"], result["references"])
        self.assertEqual(len(self.assets.list()), 1)
        self.assertTrue((self.source / "人物.PNG").exists())

    def test_rejects_nested_paths_before_any_image_is_copied(self):
        for name in ("../人物.png", "子目录/不导入.png", "C:\\outside.png"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.assets.import_folder_files(str(self.source), "characters", ["人物.PNG", name])
            self.assertEqual(self.assets.list(), [])
