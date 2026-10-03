"""Image count survives editing while a task remains exactly one cloud request."""

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from fastapi.testclient import TestClient
from backend.api import create_app
from backend.config import Settings
from backend.files import read_json, write_json
from backend.jsonl import fingerprint, import_jsonl
from backend.models import TaskInput
from backend.service import Studio
from .fakes import FakeCloud, response


class ImageCountTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        root = Path(self.temp.name)
        self.cloud = FakeCloud()
        self.studio = Studio(Settings(root, root / "data", project="demo", bucket="bucket"), self.cloud)
        self.repo = self.studio.repo
        self.bid = self.repo.create("数量测试")["id"]

    def tearDown(self):
        self.studio.close()
        self.temp.cleanup()

    def compiled(self):
        manifest = self.studio.prepare(self.bid)
        lines = (self.repo.directory(self.bid) / "inputs/prompts.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        request = json.loads(lines[0])["request"]
        self.assertEqual(manifest["requests"][0]["fingerprint"], fingerprint(request))
        return request["contents"][0]["parts"][0]["text"]

    def test_legacy_tasks_default_to_one_without_rewriting(self):
        path = self.repo.directory(self.bid) / "inputs/tasks.json"
        self.repo.replace_tasks(self.bid, [TaskInput(name="旧任务", prompt="原始提示词\n  ")])
        old = read_json(path)
        old[0].pop("image_count")
        write_json(path, old)
        before = path.read_bytes()
        self.assertEqual(self.repo.tasks(self.bid)[0].image_count, 1)
        self.assertEqual(self.compiled(), "原始提示词\n  ")
        self.assertEqual(path.read_bytes(), before)

    def test_all_counts_preserve_source_and_one_jsonl_line(self):
        original = "街道全景\n保留这一行和末尾空格  "
        for count in range(1, 5):
            with self.subTest(count=count):
                self.repo.replace_tasks(self.bid, [TaskInput(name="街道", prompt=original, image_count=count)])
                expected = original if count == 1 else original + f"\n\n请生成{count}张独立图片，每张单独输出，不要将多张图片拼成一张。"
                self.assertEqual(self.compiled(), expected)
                self.assertEqual(self.repo.tasks(self.bid)[0].prompt, original)
                self.assertEqual(self.repo.tasks(self.bid)[0].image_count, count)

    def test_reprepare_and_switching_never_accumulate_suffixes(self):
        task = self.repo.replace_tasks(self.bid, [TaskInput(name="图", prompt="draw", image_count=4)])[0]
        first = self.compiled()
        self.assertEqual(self.compiled(), first)
        self.studio.update_task(self.bid, task.id, TaskInput(name="图", prompt="draw", image_count=2))
        self.assertEqual(self.compiled(), "draw\n\n请生成2张独立图片，每张单独输出，不要将多张图片拼成一张。")
        self.studio.update_task(self.bid, task.id, TaskInput(name="图", prompt="draw", image_count=1))
        self.assertEqual(self.compiled(), "draw")
        self.assertEqual(self.repo.tasks(self.bid)[0].id, task.id)

    def test_different_counts_match_out_of_order_and_keep_every_returned_image(self):
        tasks = self.repo.replace_tasks(self.bid, [
            TaskInput(name="一张", prompt="same", image_count=1),
            TaskInput(name="四张", prompt="same", image_count=4)])
        batch = self.studio.submit(self.bid)
        requests = self.studio.manifest(self.bid)["requests"]
        multiple = response(requests[1]["request"])
        parts = multiple["response"]["candidates"][0]["content"]["parts"]
        parts.append(response(requests[1]["request"], (4, 5, 6))["response"]["candidates"][0]["content"]["parts"][0])
        self.cloud.finish(batch["job_name"], {"shard.jsonl": [multiple, response(requests[0]["request"])]})
        self.assertEqual(self.studio.poll(self.bid)["phase"], "completed")
        results = {t["task_id"]: t for t in self.studio.results(self.bid)["tasks"]}
        self.assertEqual(len(results[tasks[0].id]["images"]), 1)
        self.assertEqual(len(results[tasks[1].id]["images"]), 2)
        self.assertEqual(self.cloud.creates, 1)  # Fewer images do not cause another paid generation.

    def test_clone_and_failed_retry_preserve_count(self):
        self.repo.replace_tasks(self.bid, [TaskInput(name="图", prompt="draw", image_count=3)])
        clone = self.studio.retry(self.bid, failed_only=False)
        self.assertEqual(self.repo.tasks(clone["id"])[0].image_count, 3)
        batch = self.studio.submit(self.bid)
        request = self.studio.manifest(self.bid)["requests"][0]["request"]
        self.cloud.finish(batch["job_name"], {"shard.jsonl": [{"request": request, "status": "blocked"}]})
        self.studio.poll(self.bid)
        retry = self.studio.retry(self.bid)
        task = self.repo.tasks(retry["id"])[0]
        self.assertEqual((task.prompt, task.image_count), ("draw", 3))

    def test_api_persists_count_and_rejects_noninteger_or_out_of_range(self):
        with TestClient(create_app(self.studio, "test-token", background=False)) as client:
            client.headers["X-VBS-Token"] = "test-token"
            url = f"/batches/{self.bid}/tasks"
            saved = client.put(url, json={"tasks": [{"name": "图", "prompt": "original", "image_count": 4}]})
            self.assertEqual(saved.status_code, 200)
            task = saved.json()[0]
            self.assertEqual((task["prompt"], task["image_count"]), ("original", 4))
            for invalid in [0, 5, -1, True, 1.5, 1.0, "2", None]:
                with self.subTest(invalid=invalid):
                    rejected = client.put(url, json={"tasks": [{"name": "图", "prompt": "x", "image_count": invalid}]})
                    self.assertEqual(rejected.status_code, 422)
            self.assertEqual(client.get(url).json()[0], task)
            edited = client.put(url + "/" + task["id"], json={"name": "图", "prompt": "original", "image_count": 2})
            self.assertEqual(edited.json()["image_count"], 2)
            self.assertEqual(client.get(url).json()[0]["id"], task["id"])

    def test_imported_jsonl_keeps_existing_prompt_as_literal_text(self):
        text = "draw\n\n请生成4张独立图片，每张单独输出，不要将多张图片拼成一张。"
        source = self.repo.settings.root / "legacy.jsonl"
        source.write_text(json.dumps({"request": {"contents": [{"role": "user", "parts": [{"text": text}]}]}}, ensure_ascii=False) + "\n", encoding="utf-8")
        imported = import_jsonl(self.repo, self.bid, str(source))
        self.assertEqual(imported[0].image_count, 1)
        self.assertEqual(self.compiled(), text)
