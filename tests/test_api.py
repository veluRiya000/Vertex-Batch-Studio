from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from dataclasses import replace
from fastapi.testclient import TestClient
from backend.api import create_app
from backend.config import Settings
from backend.models import TaskInput
from backend.service import Studio
from .fakes import FakeCloud, response, image_bytes


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        root = Path(self.temp.name)
        self.cloud = FakeCloud()
        self.studio = Studio(Settings(root, root / "data", project="demo", bucket="bucket"), self.cloud)
        self.client = TestClient(create_app(self.studio, "test-token", background=False))
        self.client.__enter__()
        self.client.headers["X-VBS-Token"] = "test-token"

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def test_requires_auth_and_rejects_invalid_names(self):
        self.assertEqual(self.client.get("/health", headers={"X-VBS-Token": "wrong"}).status_code, 401)
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(self.client.post("/batches", json={"project_name": "bad/name"}).status_code, 422)

    def test_submit_without_configuration_is_rejected_and_local_cancel_succeeds(self):
        batch = self.studio.repo.create("未配置的项目")
        bid = batch["id"]
        self.studio.append_task(bid, TaskInput(name="图", prompt="draw"))
        self.studio.settings = replace(self.studio.settings, project="", bucket="")
        response = self.client.post(f"/batches/{bid}/submit")
        self.assertEqual(response.status_code, 400)
        self.assertIn("项目 ID", response.json()["detail"])
        self.assertEqual(self.studio.repo.get(bid)["phase"], "draft")
        cancelled = self.client.post(f"/batches/{bid}/cancel")
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.json()["phase"], "cancelled")
        self.assertEqual(self.cloud.creates, 0)

    def test_editing_tasks_and_prepare(self):
        batch = self.client.post("/batches", json={"project_name": "中文项目"}).json()
        bid = batch["id"]
        tasks = self.client.put(f"/batches/{bid}/tasks", json={"tasks": [{"name": "图", "prompt": "draw"}]}).json()
        edited = self.client.put(f"/batches/{bid}/tasks/{tasks[0]['id']}", json={"name": "改", "prompt": "changed"})
        self.assertEqual(edited.json()["id"], tasks[0]["id"])
        self.assertEqual(self.client.post(f"/batches/{bid}/prepare").status_code, 200)
        self.studio.submit(bid)
        denied = self.client.put(f"/batches/{bid}/tasks", json={"tasks": [{"name": "图", "prompt": "x"}]})
        self.assertEqual(denied.status_code, 400)

    def test_finished_sse_snapshot_and_output_image(self):
        bid = self.studio.repo.create("SSE")["id"]
        self.studio.repo.replace_tasks(bid, [TaskInput(name="图", prompt="draw")])
        batch = self.studio.submit(bid)
        request = self.studio.manifest(bid)["requests"][0]["request"]
        self.cloud.finish(batch["job_name"], {"part.jsonl": [response(request)]})
        self.studio.poll(bid)
        events = self.client.get(f"/batches/{bid}/events", headers={"Last-Event-ID": "old"})
        self.assertEqual(events.status_code, 200)
        self.assertIn("event: snapshot", events.text)
        self.assertIn('"phase":"completed"', events.text)
        task_id = self.studio.repo.tasks(bid)[0].id
        image = self.client.get(f"/batches/{bid}/images/{task_id}/0")
        self.assertEqual(image.headers["content-type"], "image/png")
        self.assertTrue(image.content.startswith(b"\x89PNG"))

    def test_unknown_batch_is_404(self):
        self.assertEqual(self.client.get("/batches/" + "a" * 32).status_code, 404)

    def test_bulk_reordering_preserves_ids(self):
        batch = self.client.post("/batches", json={"project_name": "排序"}).json()
        url = f"/batches/{batch['id']}/tasks"
        tasks = self.client.put(url, json={"tasks": [
            {"name": "一", "prompt": "one"}, {"name": "二", "prompt": "two"}]}).json()
        reordered = self.client.put(url, json={"tasks": list(reversed(tasks))})
        self.assertEqual(reordered.status_code, 200)
        self.assertEqual([t["id"] for t in reordered.json()], [t["id"] for t in reversed(tasks)])
        bad = dict(tasks[0], id="f" * 32)
        self.assertEqual(self.client.put(url, json={"tasks": [bad]}).status_code, 400)

    def test_append_edit_delete_and_frozen_inputs(self):
        batch = self.studio.repo.create("逐条任务")
        url = f"/batches/{batch['id']}/tasks"
        a = self.client.post(url, json={"name": "一", "prompt": "one", "image_count": 3}).json()
        b = self.client.post(url, json={"name": "二", "prompt": "two"}).json()
        self.assertNotEqual(a["id"], b["id"])
        self.assertTrue(a["created_at"])
        edited = self.client.put(url + "/" + a["id"], json={"name": "改", "prompt": "edit", "image_count": 2}).json()
        self.assertEqual(edited["created_at"], a["created_at"])
        self.assertEqual(self.client.delete(url + "/" + b["id"]).status_code, 204)
        self.assertEqual(self.client.get(url).json(), [edited])
        self.studio.submit(batch["id"])
        self.assertEqual(self.client.post(url, json={"name": "三", "prompt": "three"}).status_code, 400)
        self.assertEqual(self.client.delete(url + "/" + a["id"]).status_code, 400)

    def test_rounds_keep_workspace_and_do_not_overwrite(self):
        a = self.client.post("/batches", json={"project_name": "中文 项目"}).json()
        b = self.client.post("/batches", json={"project_name": a["project_name"], "source_batch_id": a["id"]}).json()
        c = self.client.post("/batches", json={"project_name": a["project_name"], "source_batch_id": b["id"]}).json()
        self.assertEqual(a["workspace_id"], a["id"])
        self.assertEqual(b["workspace_id"], a["id"])
        self.assertEqual(c["workspace_id"], a["id"])
        self.assertTrue(b["folder"].endswith("_02"))
        self.assertTrue(c["folder"].endswith("_03"))
        self.assertEqual(self.client.post("/batches", json={"project_name": "missing", "source_batch_id": "a" * 32}).status_code, 404)

    def test_raw_reference_upload_validates_content_and_filename(self):
        ref = self.client.post("/references/upload", params={"name": "../参考.webp", "category": "styles"}, content=image_bytes()).json()
        self.assertEqual(ref["mime_type"], "image/png")
        self.assertTrue(ref["path"].startswith("references/styles/"))
        self.assertNotIn("..", ref["path"])
        image = self.client.get("/references/file", params={"path": ref["path"]})
        self.assertEqual(image.content, image_bytes())
        bad = self.client.post("/references/upload", params={"name": "invalid.png", "category": "styles"}, content=b"not an image")
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(len(self.client.get("/references").json()), 1)
        self.assertEqual(list((self.studio.settings.root / ".runtime/imports").iterdir()), [])

    def test_public_config_does_not_expose_secrets(self):
        config = self.client.get("/config").json()
        self.assertEqual(config["project"], "demo")
        self.assertNotIn("credentials_file", config)
        self.assertNotIn("token", config)
        self.assertNotIn("private_key", config)

    def test_reference_order_persists_per_category_and_new_imports_append(self):
        def upload(name,category):
            return self.client.post('/references/upload', params={'name':name,'category':category}, content=image_bytes()).json()['path']
        a=upload('a.png','characters')
        b=upload('b.png','characters')
        other=upload('style.png','styles')
        result=self.client.put('/references/order',json={'category':'characters','paths':[b,a]})
        self.assertEqual(result.status_code,200)
        self.assertEqual([ref['path'] for ref in result.json()],[b,a,other])
        from backend.assets import Assets
        self.assertEqual([ref['path'] for ref in Assets(self.studio.repo).list()],[b,a,other])
        new=upload('0-new.png','characters')
        self.assertEqual([ref['path'] for ref in self.client.get('/references').json()],[b,a,new,other])
        self.assertTrue((self.studio.settings.data_dir/a).exists())
        self.assertTrue((self.studio.settings.data_dir/b).exists())

    def test_reference_sort_rejects_duplicates_cross_category_and_stale_lists(self):
        a=self.client.post('/references/upload',params={'name':'a.png','category':'characters'},content=image_bytes()).json()['path']
        b=self.client.post('/references/upload',params={'name':'b.png','category':'styles'},content=image_bytes()).json()['path']
        for paths in [[a,a],[b],[],['../secrets/key.json']]:
            result=self.client.put('/references/order',json={'category':'characters','paths':paths})
            self.assertEqual(result.status_code,400)
        self.assertEqual(self.client.put('/references/order',json={'category':'invalid','paths':[a]}).status_code,400)
        self.assertEqual([ref['path'] for ref in self.client.get('/references').json()],[a,b])

    def test_preferences_persist_and_reject_invalid_values(self):
        value = self.client.get('/preferences').json()
        value.update(theme='dark', language='en', sidebar_width=123)
        self.assertEqual(self.client.put('/preferences', json=value).json(), value)
        self.assertEqual(self.client.get('/preferences').json(), value)
        self.assertEqual(self.client.put('/preferences', json=dict(value, sidebar_width=-1)).status_code, 422)
        self.assertEqual(self.client.put('/preferences', json=dict(value, language='bad')).status_code, 422)
        self.assertEqual(self.client.get('/preferences').json(), value)

    def test_connection_configuration_preserves_unrelated_settings(self):
        env = self.studio.settings.root / '.env'
        env.write_text('# local configuration\nVBS_POLL_SECONDS=45\nGOOGLE_CLOUD_PROJECT=old\nGCS_BUCKET=old-bucket\n', encoding='utf-8')
        data_dir = self.studio.settings.data_dir
        result = self.client.put('/cloud/configuration', json={'project':'new-project','bucket':'new-bucket'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['project'], 'new-project')
        self.assertEqual(self.studio.settings.data_dir, data_dir)
        text = env.read_text(encoding='utf-8')
        self.assertIn('# local configuration', text)
        self.assertIn('VBS_POLL_SECONDS=45', text)
        self.assertIn('GOOGLE_CLOUD_PROJECT=new-project', text)

    def test_imports_arbitrary_named_valid_json_without_overwriting_old_key(self):
        # Generate a disposable test key; no real credentials or network calls.
        import json
        from dataclasses import replace
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
        info = {'type':'service_account','project_id':'demo-project','private_key':private,
                'client_email':'fixture@demo-project.iam.gserviceaccount.com',
                'token_uri':'https://oauth2.googleapis.com/token'}
        old = self.studio.settings.root / 'secrets/old.json'
        old.parent.mkdir(parents=True)
        old.write_text('old content', encoding='utf-8')
        self.studio.settings = self.studio.repo.settings = replace(self.studio.settings, credentials_file=old)
        result = self.client.put('/cloud/configuration', json={'project':'demo-project','bucket':'demo-bucket',
            'credential_filename':'downloaded-project-123.json','key_json':json.dumps(info)})
        self.assertEqual(result.status_code, 200)
        new = self.studio.settings.credentials_file
        self.assertTrue(new.name.endswith('downloaded-project-123.json'))
        self.assertEqual(json.loads(new.read_text(encoding='utf-8')), info)
        self.assertEqual(old.read_text(encoding='utf-8'), 'old content')
        self.assertNotIn(private, result.text)
        self.assertNotIn('private_key', result.text)

    def test_invalid_secret_never_echoed_and_configuration_unchanged(self):
        marker = 'private-secret-must-never-appear'
        for body in [{'project':'bad/id','bucket':'bucket','key_json':marker},
                     {'project':'demo','bucket':'bucket','key_json':marker}]:
            result = self.client.put('/cloud/configuration', json=body)
            self.assertEqual(result.status_code, 400)
            self.assertNotIn(marker, result.text)
        self.assertEqual(self.studio.settings.project, 'demo')
        self.assertFalse((self.studio.settings.root / '.env').exists())

    def test_cannot_change_connection_while_job_active_or_queued(self):
        bid = self.studio.repo.create('active')['id']
        self.studio.repo.replace_tasks(bid, [TaskInput(name='one',prompt='test')])
        self.studio.submit(bid)
        result = self.client.put('/cloud/configuration', json={'project':'next','bucket':'next-bucket'})
        self.assertEqual(result.status_code, 409)
        batch = self.studio.repo.get(bid)
        batch['phase'] = 'cancelled'
        self.studio.repo.save(batch)
        self.studio._inflight.add(bid)
        result = self.client.put('/cloud/configuration', json={'project':'next','bucket':'next-bucket'})
        self.assertEqual(result.status_code, 409)
        self.studio._inflight.clear()

    def test_connection_check_is_read_only_and_sanitizes_failures(self):
        self.cloud.check_connection = lambda bucket: {'storage':True}
        self.assertTrue(self.client.post('/cloud/check').json()['ok'])
        self.assertEqual(self.cloud.jobs, {})
        def fail(bucket):
            raise RuntimeError('private-secret-value')
        self.cloud.check_connection = fail
        result = self.client.post('/cloud/check')
        self.assertEqual(result.status_code, 400)
        self.assertNotIn('private-secret-value', result.text)
