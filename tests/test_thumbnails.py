"""Thumbnails must preserve previews and originals through repeat decode."""

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient
from PIL import Image

from backend.api import create_app
from backend.config import Settings
from backend.files import write_json
from backend.service import Studio


class ThumbnailTests(unittest.TestCase):
    def test_output_thumbnail_is_bounded_cached_and_invalidated(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            studio = Studio(Settings(root, root / "data"))
            batch = studio.repo.create("test")
            task = "f" * 32
            directory = studio.repo.directory(batch["id"])
            original = directory / "outputs/images/test.png"
            Image.new("RGB", (2048, 1024), "#f00").save(original)
            report = {"tasks": [{"task_id":task, "images":[{"path":str(original), "mime_type":"image/png"}]}]}
            write_json(directory / "outputs/results.json", report)
            route = f"/batches/{batch['id']}/images/{task}/0"
            with TestClient(create_app(studio, "local", background=False),
                            headers={"X-VBS-Token": "local"}) as client:
                self.assertEqual(client.get(route).content, original.read_bytes())
                first = client.get(route, params={"thumbnail": 160})
                self.assertEqual(first.status_code, 200)
                self.assertEqual(first.headers["content-type"], "image/webp")
                with Image.open(BytesIO(first.content)) as preview:
                    self.assertEqual(preview.size, (160, 80))
                self.assertEqual(client.get(route, params={"thumbnail": 160}).content, first.content)
                self.assertEqual(client.get(route, params={"thumbnail": 8000}).status_code, 400)
                Image.new("RGB", (2048, 1024), "#009").save(original)
                second = client.get(route, params={"thumbnail": 160})
                self.assertNotEqual(first.content, second.content)
                self.assertEqual(client.get(route).content, original.read_bytes())
                self.assertEqual(len(list((root / "data/.thumbnail-cache").glob("*.webp"))), 2)
