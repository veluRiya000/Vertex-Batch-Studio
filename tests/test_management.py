from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from fastapi.testclient import TestClient
from backend.api import create_app
from backend.config import Settings
from backend.models import TaskInput
from backend.service import Studio
from .fakes import FakeCloud, image_bytes


class ManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cloud = FakeCloud()
        self.studio = Studio(Settings(self.root, self.root / "data", project="demo", bucket="bucket"), self.cloud)
        self.repo = self.studio.repo

    def tearDown(self):
        self.studio.close()
        self.temp.cleanup()

    def reference(self):
        image = self.root / "人物.png"
        image.write_bytes(image_bytes((20, 60, 100)))
        return self.studio.assets.import_file(str(image), category="characters")["path"]

    def test_project_archive_delete_preserves_external_files_and_cloud_prefix(self):
        ref = self.reference()
        outside = self.root / "外部输出"
        outside.mkdir()
        image = outside / "image.png"
        image.write_bytes(image_bytes((1, 2, 3)))
        batch = self.repo.create("夏日祭", str(outside))
        child = self.repo.create("夏日祭", source_batch_id=batch["id"])
        other = self.repo.create("其他项目")
        self.repo.archive_workspace(batch["id"])
        self.assertTrue(all(self.repo.get(b["id"])["archived"] for b in [batch, child]))
        self.assertFalse(self.repo.get(other["id"])["archived"])
        self.assertEqual(self.repo.delete_workspace(batch["id"])["batch_count"], 2)
        self.assertEqual([b["id"] for b in self.repo.list()], [other["id"]])
        self.assertTrue(image.is_file())
        self.assertTrue((self.repo.settings.data_dir / ref).is_file())
        again = self.repo.create("夏日祭")
        self.assertTrue(again["folder"].endswith("_03"))
        self.assertEqual(self.cloud.creates, 0)

    def test_running_round_blocks_whole_project_before_any_move(self):
        root = self.repo.create("根项目")
        child = self.repo.create("根项目", source_batch_id=root["id"])
        child["phase"] = "monitoring"
        self.repo.save(child)
        with self.assertRaisesRegex(ValueError, "运行中"):
            self.repo.archive_workspace(root["id"])
        self.assertFalse(self.repo.get(root["id"])["archived"])
        with self.assertRaisesRegex(ValueError, "完全归档"):
            self.repo.delete_workspace(root["id"])
        self.assertEqual(len(self.repo.list()), 2)

    def test_reference_delete_updates_order_and_rejects_unsafe_paths(self):
        ref = self.reference()
        self.studio.assets.reorder("characters", [ref])
        for bad in ["../secrets/key.json", "references/characters/../characters/人物.png", "references/characters/../../outside.png"]:
            with self.assertRaises((ValueError, KeyError)):
                self.studio.assets.delete(bad)
        self.assertEqual(self.studio.assets.delete(ref), [])
        self.assertEqual(self.studio.assets._order()["characters"], [])

    def test_draft_reference_is_protected_then_can_be_deleted_when_unused(self):
        ref = self.reference()
        batch = self.repo.create("正在创作")
        task = self.studio.append_task(batch["id"], TaskInput(name="人设", prompt="draw", refs=[ref]))
        with self.assertRaisesRegex(ValueError, "正在创作"):
            self.studio.assets.delete(ref)
        self.studio.delete_task(batch["id"], task["id"])
        self.assertEqual(self.studio.assets.delete(ref), [])
        with self.assertRaisesRegex(ValueError, "已被删除"):
            self.studio.append_task(batch["id"], TaskInput(name="人设", prompt="draw", refs=[ref]))

    def test_submitted_reference_uses_frozen_bytes_after_library_deletion(self):
        ref = self.reference()
        batch = self.repo.create("已提交")
        self.studio.append_task(batch["id"], TaskInput(name="人设", prompt="draw", refs=[ref]))
        self.studio.submit(batch["id"])
        self.studio.assets.delete(ref)
        with TestClient(create_app(self.studio, "test-token", background=False)) as client:
            client.headers["X-VBS-Token"] = "test-token"
            preview = client.get("/references/file", params={"path": ref, "batch_id": batch["id"]})
            self.assertEqual(preview.status_code, 200)
            self.assertTrue(preview.content.startswith(b"\x89PNG"))
        clone = self.studio.retry(batch["id"], failed_only=False)
        copied_ref = self.repo.tasks(clone["id"])[0].refs[0]
        self.assertTrue(self.studio.assets.local(copied_ref, clone["id"]).is_file())

    def test_archived_deletion_rejects_symlink_escape(self):
        batch = self.repo.create("归档链接")
        self.repo.archive_workspace(batch["id"])
        directory = self.repo.directory(batch["id"])
        outside = self.root / "outside" / "archive" / directory.name
        outside.parent.mkdir(parents=True)
        directory.rename(outside)
        try:
            directory.symlink_to(outside, target_is_directory=True)
        except OSError:
            outside.rename(directory)
            self.skipTest("System does not permit directory symlink creation")
        with self.assertRaisesRegex(ValueError, "路径不安全"):
            self.repo.delete_workspace(batch["id"])
        self.assertTrue((outside / "batch.json").is_file())
        directory.unlink()

    def test_rename_updates_all_rounds_without_changing_files_or_cloud_identity(self):
        batch = self.repo.create("原项目")
        child = self.repo.create("原项目", source_batch_id=batch["id"])
        other = self.repo.create("其他项目")
        child["phase"] = "monitoring"
        child["job_name"] = "projects/demo/locations/global/batchPredictionJobs/123"
        self.repo.save(child)
        snapshots = {b["id"]: self.repo.get(b["id"]) for b in [batch, child]}
        paths = {b["id"]: self.repo.directory(b["id"]) for b in [batch, child]}
        frozen = paths[child["id"]] / "inputs" / "prompts.jsonl"
        frozen.write_text('original frozen request', encoding="utf-8")
        self.repo.rename_workspace(batch["id"], "新名称 中文")
        for id, before in snapshots.items():
            after = self.repo.get(id)
            self.assertEqual(after["project_name"], "新名称 中文")
            self.assertEqual(self.repo.directory(id), paths[id])
            for key in before.keys() - {"project_name", "updated_at"}:
                self.assertEqual(after[key], before[key], key)
        self.assertEqual(frozen.read_text(encoding="utf-8"), 'original frozen request')
        self.assertEqual(self.repo.get(other["id"])["project_name"], "其他项目")
        self.assertEqual(self.cloud.creates, 0)

    def test_rename_validates_name_auth_and_missing_workspace(self):
        batch = self.repo.create("原项目")
        with TestClient(create_app(self.studio, "test-token", background=False)) as client:
            path = f"/workspaces/{batch['id']}"
            self.assertEqual(client.put(path, json={"project_name": "新名称"}).status_code, 401)
            client.headers["X-VBS-Token"] = "test-token"
            for invalid in ["", "   ", "a/b", "a" * 81]:
                self.assertEqual(client.put(path, json={"project_name": invalid}).status_code, 422)
            self.assertEqual(self.repo.get(batch["id"])["project_name"], "原项目")
            self.assertEqual(client.put(path, json={"project_name": "新名称"}).status_code, 200)
            self.assertEqual(self.repo.get(batch["id"])["project_name"], "新名称")
            self.assertEqual(client.put('/workspaces/' + 'f' * 32, json={"project_name": "新"}).status_code, 404)

    def test_management_endpoints_require_auth_and_archive_before_deletion(self):
        batch = self.repo.create("接口项目")
        ref = self.reference()
        with TestClient(create_app(self.studio, "test-token", background=False)) as client:
            base = f"/workspaces/{batch['id']}"
            self.assertEqual(client.delete(base).status_code, 401)
            client.headers["X-VBS-Token"] = "test-token"
            self.assertEqual(client.delete(base).status_code, 400)
            self.assertEqual(client.post(base + "/archive").status_code, 200)
            self.assertEqual(client.delete(base).status_code, 200)
            self.assertEqual(client.delete(base).status_code, 404)
            self.assertEqual(client.delete("/references", params={"path": ref}).json(), [])
