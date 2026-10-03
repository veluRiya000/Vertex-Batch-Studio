from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import copy
import json
import unittest
import time
from backend.assets import inspect_image
from backend.config import Settings
from backend.files import BusyError, read_json, write_json, operation_lock
from backend.jsonl import import_jsonl
from backend.models import TaskInput
from backend.service import Studio
from .fakes import FakeCloud, image_bytes, response


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = Settings(self.root, self.root / "data", project="demo", bucket="bucket")
        self.cloud = FakeCloud()
        self.studio = Studio(self.settings, self.cloud)
        self.repo = self.studio.repo

    def tearDown(self):
        self.studio.close()
        self.temp.cleanup()

    def make(self, tasks=None):
        batch = self.repo.create("中文 项目")
        self.repo.replace_tasks(batch["id"], tasks or [TaskInput(name="图一", prompt="draw a lantern")])
        return batch["id"]

    def submitted(self, tasks=None):
        bid = self.make(tasks)
        self.studio.submit(bid)
        return bid, self.repo.get(bid), self.studio.manifest(bid)

    def image(self, name="中文 图片.png", color=(1, 2, 3)):
        path = self.root / name
        path.write_bytes(image_bytes(color))
        return path

    def test_names_collisions_and_archive_reservation(self):
        a = self.repo.create("中文 项目")
        b = self.repo.create("中文 项目")
        self.assertTrue(b["folder"].endswith("_02"))
        self.repo.archive(a["id"])
        c = self.repo.create("中文 项目")
        self.assertTrue(c["folder"].endswith("_03"))
        self.assertNotIn(a["id"], a["folder"])

    def test_invalid_names(self):
        for name in ["", " ", "x/y", "x\\y", "x.", "x "]:
            with self.assertRaises(ValueError):
                self.repo.create(name)

    def test_lesson_metadata_is_read_without_overwriting(self):
        batch = self.repo.create("练习")
        p = self.repo.directory(batch["id"]) / "batch.json"
        old = {k: batch[k] for k in ["id", "project_name", "folder", "created_at", "phase"]}
        write_json(p, old)
        self.assertFalse(self.repo.get(batch["id"])["archived"])
        self.assertEqual(read_json(p), old)

    def test_image_import_detects_format_and_avoids_overwrite(self):
        source = self.image("wrong.jpg")
        first = self.studio.assets.import_file(str(source), category="styles")
        self.assertTrue(first["path"].endswith(".png"))
        second = self.studio.assets.import_file(str(source), category="styles")
        self.assertEqual(first["path"], second["path"])
        source.write_bytes(image_bytes((3, 2, 1)))
        third = self.studio.assets.import_file(str(source), category="styles")
        self.assertNotEqual(first["path"], third["path"])

    def test_same_size_content_change_creates_new_cloud_object(self):
        first_data, second_data = image_bytes((1, 2, 3)), image_bytes((3, 2, 1))
        self.assertEqual(len(first_data), len(second_data))
        source = self.image()
        ref = self.studio.assets.import_file(str(source), category="styles")["path"]
        bid = self.make([TaskInput(name="图", prompt="draw", refs=[ref])])
        self.studio.submit(bid)
        asset1 = self.studio.manifest(bid)["assets"][0]
        (self.settings.data_dir / ref).write_bytes(second_data)
        bid2 = self.make([TaskInput(name="图", prompt="draw", refs=[ref])])
        self.studio.submit(bid2)
        asset2 = self.studio.manifest(bid2)["assets"][0]
        self.assertNotEqual(asset1["object_name"], asset2["object_name"])

    def test_prepare_snapshot_and_upload_allowlist(self):
        ref = self.studio.assets.import_file(str(self.image()), category="characters")["path"]
        bid = self.make([TaskInput(name="图", prompt="hello\nworld", refs=[ref])])
        manifest = self.studio.prepare(bid)
        original = manifest["assets"][0]["sha256"]
        (self.settings.data_dir / ref).write_bytes(image_bytes((9, 9, 9)))
        (self.settings.data_dir / "secret.json").write_text("secret")
        self.studio.submit(bid)
        self.assertEqual(self.cloud.uploads[0][3], original)
        self.assertEqual(len(self.cloud.uploads), 2)
        self.assertTrue(self.cloud.uploads[-1][1].endswith("inputs/prompts.jsonl"))
        self.assertFalse(any("secret" in row[1] for row in self.cloud.uploads))
        lines = (self.repo.directory(bid) / "inputs/prompts.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["request"]["contents"][0]["parts"][0]["text"], "hello\nworld")

    def test_reference_order_and_generation_config(self):
        refs = [self.studio.assets.import_file(str(self.image(f"{i}.png", (i, 2, 3))), category="styles")["path"]
                for i in [1, 2]]
        bid = self.make([TaskInput(name="图", prompt="draw", refs=refs, temperature=0.35)])
        manifest = self.studio.prepare(bid)
        request = manifest["requests"][0]["request"]
        self.assertEqual(request["generationConfig"]["temperature"], 0.35)
        self.assertEqual(request["generationConfig"]["imageConfig"]["imageSize"], "1K")
        for asset, part in zip(manifest["assets"], request["contents"][0]["parts"][1:]):
            self.assertTrue(part["fileData"]["fileUri"].endswith(asset["object_name"]))

    def test_path_escape_rejected(self):
        bid = self.make([TaskInput(name="图", prompt="draw", refs=["../secret.png"])])
        with self.assertRaises(ValueError):
            self.studio.prepare(bid)

    def test_duplicate_submit_is_idempotent(self):
        bid, batch, manifest = self.submitted()
        self.studio.submit(bid)
        self.assertEqual(self.cloud.creates, 1)
        with self.assertRaises(ValueError):
            self.repo.replace_tasks(bid, [TaskInput(name="改", prompt="changed")])

    def test_timeout_reconciles_after_restart_without_resubmission(self):
        self.cloud.create_timeout = True
        bid = self.make()
        with self.assertRaises(TimeoutError):
            self.studio.submit(bid)
        self.assertEqual(self.repo.get(bid)["phase"], "submission_unknown")
        self.studio.close()
        self.studio = Studio(self.settings, self.cloud)
        self.repo = self.studio.repo
        batch = self.studio.submit(bid)
        self.assertIsNotNone(batch["job_name"])
        self.assertEqual(self.cloud.creates, 1)

    def test_upload_failure_prevents_creation_and_can_resume(self):
        self.cloud.upload_error = True
        bid = self.make()
        with self.assertRaises(ConnectionError):
            self.studio.submit(bid)
        self.assertEqual(self.cloud.creates, 0)
        self.assertEqual(self.repo.get(bid)["phase"], "upload_failed")
        self.cloud.upload_error = False
        self.studio.submit(bid)
        self.assertEqual(self.cloud.creates, 1)

    def test_input_tampering_prevents_submission(self):
        bid = self.make()
        self.studio.prepare(bid)
        (self.repo.directory(bid) / "inputs/prompts.jsonl").write_text("{}")
        with self.assertRaises(ValueError):
            self.studio.submit(bid)
        self.assertEqual(self.cloud.creates, 0)

    def test_definite_rejection_is_visible_and_retryable(self):
        class Denied(Exception):
            code = 403
        bid = self.make()
        self.cloud.create_error = Denied("denied")
        with self.assertRaises(Denied):
            self.studio.submit(bid)
        self.assertEqual(self.repo.get(bid)["phase"], "submission_failed")
        self.cloud.create_error = None
        self.assertIsNotNone(self.studio.submit(bid)["job_name"])

    def test_all_shards_out_of_order_and_multiple_formats(self):
        bid, batch, manifest = self.submitted([TaskInput(name="同名", prompt=p) for p in ["first", "second"]])
        requests = manifest["requests"]
        self.cloud.finish(batch["job_name"], {
            "z.jsonl": [response(requests[0]["request"], format="JPEG")],
            "a.jsonl": [response(requests[1]["request"], format="WEBP")],
        })
        done = self.studio.poll(bid)
        report = self.studio.results(bid)
        self.assertEqual(done["phase"], "completed")
        self.assertEqual(report["counts"]["succeeded"], 2)
        self.assertTrue(report["tasks"][0]["images"][0]["path"].endswith(".jpg"))
        self.assertTrue(report["tasks"][1]["images"][0]["path"].endswith(".webp"))
        self.assertIn("actual-output", done["actual_output_uri"])

    def test_duplicate_requests_incremental_results_keep_assignments(self):
        bid, batch, manifest = self.submitted([TaskInput(name="重复", prompt="same") for _ in range(2)])
        row1 = response(manifest["requests"][0]["request"], (1, 2, 3))
        row2 = response(manifest["requests"][0]["request"], (3, 2, 1))
        self.cloud.finish(batch["job_name"], {"part.jsonl": [row1]}, state="JOB_STATE_RUNNING")
        first = self.studio.poll(bid)
        assignment = dict(first["row_assignments"])
        report = self.studio.results(bid)
        first_image = next(t["images"][0]["path"] for t in report["tasks"] if t["images"])
        timestamp = Path(first_image).stat().st_mtime_ns
        self.assertEqual(report["counts"]["pending"], 1)
        self.cloud.finish(batch["job_name"], {"part.jsonl": [row1, row2]})
        done = self.studio.poll(bid)
        for key, tid in assignment.items():
            self.assertEqual(done["row_assignments"][key], tid)
        self.assertEqual(Path(first_image).stat().st_mtime_ns, timestamp)
        downloads = len(self.cloud.downloads)
        self.studio.poll(bid)
        self.assertEqual(len(self.cloud.downloads), downloads)
        self.assertEqual(self.studio.results(bid)["counts"]["images"], 2)

    def test_snake_case_echo_and_null_defaults_match(self):
        bid, batch, manifest = self.submitted()
        row = response(manifest["requests"][0]["request"])
        row["request"]["generation_config"] = row["request"].pop("generationConfig")
        row["request"]["generation_config"]["topP"] = 0.95
        row["request"]["contents"][0]["parts"][0]["file_data"] = None
        self.cloud.finish(batch["job_name"], {"part.jsonl": [row]})
        self.assertEqual(self.studio.poll(bid)["phase"], "completed")

    def test_multiple_images_and_partial_error(self):
        bid, batch, manifest = self.submitted([TaskInput(name="好", prompt="good"), TaskInput(name="坏", prompt="bad")])
        good = response(manifest["requests"][0]["request"])
        good["response"]["candidates"][0]["content"]["parts"].append(
            response(manifest["requests"][0]["request"], (4, 5, 6))["response"]["candidates"][0]["content"]["parts"][0])
        bad = {"request": manifest["requests"][1]["request"], "status": "blocked", "response": {}}
        self.cloud.finish(batch["job_name"], {"part.jsonl": [bad, good]})
        self.assertEqual(self.studio.poll(bid)["phase"], "completed_with_errors")
        report = self.studio.results(bid)
        self.assertEqual(report["counts"]["images"], 2)
        retried = self.studio.retry(bid)
        self.assertEqual(len(self.repo.tasks(retried["id"])), 1)
        self.assertEqual(retried["source_batch_id"], bid)

    def test_damaged_response_and_missing_results_are_recorded(self):
        bid, batch, manifest = self.submitted([TaskInput(name="图", prompt=p) for p in ["first", "second"]])
        bad = response(manifest["requests"][0]["request"])
        bad["response"] = "invalid"
        self.cloud.finish(batch["job_name"], {"part.jsonl": [bad, {"request": "invalid"}]})
        self.assertEqual(self.studio.poll(bid)["phase"], "completed_with_errors")
        report = self.studio.results(bid)
        self.assertEqual(report["counts"]["error"], 1)
        self.assertEqual(report["counts"]["missing"], 1)
        self.assertEqual(len(report["row_errors"]), 1)

    def test_corrupted_base64_does_not_abort_other_tasks(self):
        bid, batch, manifest = self.submitted([TaskInput(name="图", prompt=p) for p in ["first", "second"]])
        bad = response(manifest["requests"][0]["request"])
        bad["response"]["candidates"][0]["content"]["parts"][0]["inlineData"]["data"] = "!invalid!"
        self.cloud.finish(batch["job_name"], {"part.jsonl": [bad, response(manifest["requests"][1]["request"])]})
        self.studio.poll(bid)
        self.assertEqual(self.studio.results(bid)["counts"]["images"], 1)

    def test_download_failure_and_local_export_recover_without_generation(self):
        bid, batch, manifest = self.submitted()
        self.cloud.finish(batch["job_name"], {"part.jsonl": [response(manifest["requests"][0]["request"])]})
        self.cloud.download_error = ConnectionError("offline")
        with self.assertRaises(ConnectionError):
            self.studio.poll(bid)
        self.cloud.download_error = None
        blocked = self.root / "not-a-folder"
        blocked.write_text("file")
        self.repo.set_output(bid, str(blocked))
        with self.assertRaises(OSError):
            self.studio.poll(bid)
        self.repo.set_output(bid, str(self.root / "export"))
        self.assertEqual(self.studio.poll(bid)["phase"], "completed")
        self.assertEqual(self.cloud.creates, 1)

    def test_empty_output_settles_before_marking_missing(self):
        bid, batch, manifest = self.submitted()
        self.cloud.finish(batch["job_name"], {})
        self.assertEqual(self.studio.poll(bid)["phase"], "downloading")
        self.studio.poll(bid)
        self.assertEqual(self.studio.poll(bid)["phase"], "completed_with_errors")

    def test_archive_keeps_images_accessible(self):
        bid, batch, manifest = self.submitted()
        self.cloud.finish(batch["job_name"], {"part.jsonl": [response(manifest["requests"][0]["request"])]})
        self.studio.poll(bid)
        self.repo.archive(bid)
        image = self.studio.results(bid)["tasks"][0]["images"][0]["path"]
        self.assertTrue(Path(image).is_file())
        self.assertIn("archive", image)

    def test_archived_draft_can_clone_custom_reference(self):
        bid = self.make()
        ref = self.studio.assets.import_file(str(self.image()), batch_id=bid)["path"]
        self.repo.replace_tasks(bid, [TaskInput(name="图", prompt="draw", refs=[ref])])
        self.repo.archive(bid)
        cloned = self.studio.retry(bid, failed_only=False)
        new_ref = self.repo.tasks(cloned["id"])[0].refs[0]
        self.assertTrue((self.settings.data_dir / new_ref).is_file())

    def test_cancellation_collects_partial_results(self):
        bid, batch, manifest = self.submitted()
        self.cloud.finish(batch["job_name"], {"part.jsonl": [response(manifest["requests"][0]["request"])]},
                          state="JOB_STATE_RUNNING")
        self.studio.cancel(bid)
        self.assertEqual(self.studio.poll(bid)["phase"], "cancelled")
        self.assertEqual(self.studio.results(bid)["counts"]["images"], 1)

    def test_legacy_jsonl_import_keeps_temperature(self):
        p = self.root / "legacy.jsonl"
        write = {"request": {"contents": [{"role": "user", "parts": [{"text": "draw"}]}],
                             "generationConfig": {"temperature": 0.35}}}
        p.write_text(json.dumps(write) + "\n", encoding="utf-8")
        bid = self.repo.create("导入")["id"]
        import_jsonl(self.repo, bid, str(p))
        self.assertEqual(self.repo.tasks(bid)[0].temperature, 0.35)

    def test_operation_lock_rejects_second_writer(self):
        lock = self.root / "operation.lock"
        with operation_lock(lock):
            with self.assertRaises(BusyError):
                with operation_lock(lock):
                    pass

    def test_monitor_recovers_persisted_job_on_restart(self):
        bid, batch, manifest = self.submitted()
        self.cloud.finish(batch["job_name"], {"part.jsonl": [response(manifest["requests"][0]["request"])]})
        self.studio.close()
        self.studio = Studio(replace(self.settings, poll_seconds=0.02), self.cloud)
        self.repo = self.studio.repo
        self.studio.start()
        deadline = time.monotonic() + 5
        while self.repo.get(bid)["phase"] != "completed" and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(self.repo.get(bid)["phase"], "completed")
        self.assertEqual(self.cloud.creates, 1)

    def test_local_cache_corruption_is_redownloaded(self):
        bid, batch, manifest = self.submitted()
        self.cloud.finish(batch["job_name"], {"part.jsonl": [response(manifest["requests"][0]["request"])]})
        done = self.studio.poll(bid)
        metadata = next(iter(done["downloaded_objects"].values()))
        path = self.repo.directory(bid) / metadata["local_path"]
        path.write_text("broken", encoding="utf-8")
        self.studio.poll(bid)
        self.assertEqual(len(self.cloud.downloads), 2)
        self.assertEqual(self.studio.results(bid)["counts"]["images"], 1)

    def test_same_prompt_with_different_generation_settings_matches(self):
        bid, batch, manifest = self.submitted([
            TaskInput(name="默认", prompt="same"),
            TaskInput(name="低温", prompt="same", temperature=0.35),
        ])
        default = response(manifest["requests"][0]["request"])
        default["request"]["generationConfig"]["temperature"] = 1.0
        explicit = response(manifest["requests"][1]["request"], (3, 2, 1))
        self.cloud.finish(batch["job_name"], {"part.jsonl": [explicit, default]})
        self.assertEqual(self.studio.poll(bid)["phase"], "completed")
        report = self.studio.results(bid)
        self.assertEqual(report["counts"]["succeeded"], 2)
        self.assertEqual(report["tasks"][0]["source_line"], 2)
        self.assertEqual(report["tasks"][1]["source_line"], 1)

    def test_equivalent_explicit_default_can_share_echoed_group(self):
        bid, batch, manifest = self.submitted([
            TaskInput(name="默认", prompt="same"), TaskInput(name="显式默认", prompt="same", temperature=1.0),
        ])
        row1 = response(manifest["requests"][0]["request"])
        row1["request"]["generationConfig"]["temperature"] = 1.0
        row2 = response(manifest["requests"][1]["request"], (3, 2, 1))
        self.cloud.finish(batch["job_name"], {"part.jsonl": [row1, row2]})
        self.assertEqual(self.studio.poll(bid)["phase"], "completed")
        self.assertEqual(self.studio.results(bid)["counts"]["images"], 2)


if __name__ == "__main__":
    unittest.main()
