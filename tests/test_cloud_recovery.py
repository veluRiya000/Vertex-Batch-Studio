import asyncio
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import Mock, patch

import httpx
from backend.api import create_app
from backend.cloud import GoogleCloud
from backend.cloud_errors import is_transport_error, redact_cloud_error
from backend.config import Settings
from backend.connection import CloudConfiguration, configure_cloud
from backend.models import TaskInput
from backend.service import Studio
from .fakes import FakeCloud


class ProbeCloud(FakeCloud):
    def __init__(self, error=None):
        super().__init__()
        self.error = error
        self.closed = 0
        self.checks = 0

    def check_connection(self, bucket):
        self.checks += 1
        if self.error:
            raise self.error
        return {"storage_connection": "ok", "vertex_batch_list": "ok"}

    def close(self):
        self.closed += 1


class CloudRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = Settings(self.root, self.root / "data", project="demo", bucket="bucket")
        self.old, self.new = ProbeCloud(), ProbeCloud()
        self.factory = patch("backend.service.GoogleCloud", side_effect=[self.old, self.new]).start()
        self.studio = Studio(self.settings)

    def tearDown(self):
        self.studio.close()
        patch.stopall()
        self.temp.cleanup()

    def api_client(self, app):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1", headers={"X-VBS-Token": "test"})

    def test_probe_network_failure_rebuilds_next_check_and_redacts_diagnostics(self):
        self.old.error = httpx.ConnectError(
            "EOF proxy=http://user:proxy-secret@127.0.0.1:10808/check?access_token=query-secret "
            'Authorization: Bearer bearer-secret client_secret="field-secret"')
        app = create_app(self.studio, "test", background=False)
        async def run():
            async with self.api_client(app) as client:
                with self.assertLogs("vertex_backend", level="WARNING") as logs:
                    failed = await client.post("/cloud/check")
                self.assertEqual(failed.status_code, 400)
                self.assertIn("网络连接中断", failed.json()["detail"])
                output = " ".join(logs.output)
                self.assertIn("ConnectError", output)
                self.assertIn("EOF", output)
                for secret in ["proxy-secret", "query-secret", "bearer-secret", "field-secret"]:
                    self.assertNotIn(secret, output)
                self.assertEqual(self.old.closed, 1)
                recovered = await client.post("/cloud/check")
                self.assertEqual(recovered.status_code, 200)
                self.assertEqual(recovered.json()["details"]["storage_connection"], "ok")
                self.assertIs(self.studio._cloud, self.new)
        asyncio.run(run())
        self.assertEqual(self.factory.call_count, 2)
        self.assertEqual(self.old.creates + self.new.creates, 0)

    def test_retired_client_is_not_closed_during_concurrent_upload(self):
        entered, release = threading.Event(), threading.Event()
        failures = []
        def upload(*_):
            entered.set()
            if not release.wait(3):
                raise AssertionError("Test upload was not released")
            if self.old.closed:
                raise AssertionError("Transport closed during upload")
            return True
        self.old.upload = upload
        def worker():
            try:
                self.studio.cloud_call("upload", "bucket", "file", self.root / "file", "image/png")
            except Exception as exc:
                failures.append(exc)
        thread = threading.Thread(target=worker)
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            self.old.error = ConnectionError("proxy restarted")
            with self.assertLogs("vertex_backend", level="WARNING"), self.assertRaises(ConnectionError):
                self.studio.cloud_call("check_connection", "bucket")
            self.assertEqual(self.old.closed, 0)
            self.assertIsNone(self.studio._cloud)
            self.studio.cloud_call("check_connection", "bucket")
            self.assertIs(self.studio._cloud, self.new)
        finally:
            release.set()
            thread.join(3)
        self.assertFalse(failures)
        self.assertEqual(self.old.closed, 1)
        self.assertEqual(self.new.closed, 0)

    def test_configuration_change_and_late_probe_failure_cannot_reset_new_client(self):
        entered, release = threading.Event(), threading.Event()
        def probe(_):
            entered.set()
            release.wait(3)
            raise httpx.ReadError("old proxy EOF")
        self.old.check_connection = probe
        app = create_app(self.studio, "test", background=False)
        async def run():
            async with self.api_client(app) as client:
                with self.assertLogs("vertex_backend", level="WARNING"):
                    old_request = asyncio.create_task(client.post("/cloud/check"))
                    try:
                        self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                        await asyncio.to_thread(configure_cloud, self.studio,
                            CloudConfiguration(project="new-project", bucket="new-bucket"))
                        self.assertEqual(self.old.closed, 0)
                        self.assertEqual((await client.post("/cloud/check")).status_code, 200)
                        release.set()
                        self.assertEqual((await old_request).status_code, 400)
                    finally:
                        release.set()
                        await old_request
                self.assertIs(self.studio._cloud, self.new)
                self.assertEqual(self.old.closed, 1)
                self.assertEqual(self.new.closed, 0)
        asyncio.run(run())
        self.assertEqual(self.factory.call_args.args[0].project, "new-project")

    def test_timeout_retires_probe_but_keeps_its_transport_open_until_worker_exits(self):
        entered, release = threading.Event(), threading.Event()
        def probe(_):
            entered.set()
            release.wait(3)
            self.assertEqual(self.old.closed, 0)
            return {"storage_connection": "ok"}
        self.old.check_connection = probe
        app = create_app(self.studio, "test", background=False)
        app.state.cloud_check_timeout = .03
        async def run():
            async with self.api_client(app) as client:
                try:
                    with self.assertLogs("vertex_backend", level="WARNING"):
                        response = await client.post("/cloud/check")
                    self.assertTrue(entered.is_set())
                    self.assertEqual(response.status_code, 400)
                    self.assertIn("超时", response.json()["detail"])
                    self.assertEqual(self.old.closed, 0)
                    app.state.cloud_check_timeout = 1
                    self.assertEqual((await client.post("/cloud/check")).status_code, 200)
                finally:
                    release.set()
                    deadline = time.monotonic() + 2
                    while not self.old.closed and time.monotonic() < deadline:
                        await asyncio.sleep(.01)
                self.assertEqual(self.old.closed, 1)
                self.assertIs(self.studio._cloud, self.new)
        asyncio.run(run())

    def test_overlapping_checks_share_one_rebuilt_probe(self):
        self.old.error = ConnectionError("offline")
        app = create_app(self.studio, "test", background=False)
        original = self.new.check_connection
        def slow(bucket):
            time.sleep(.05)
            return original(bucket)
        self.new.check_connection = slow
        async def run():
            async with self.api_client(app) as client:
                with self.assertLogs("vertex_backend", level="WARNING"):
                    self.assertEqual((await client.post("/cloud/check")).status_code, 400)
                responses = await asyncio.gather(*[client.post("/cloud/check") for _ in range(8)])
                self.assertTrue(all(r.status_code == 200 for r in responses))
        asyncio.run(run())
        self.assertEqual(self.new.checks, 1)
        self.assertEqual(self.factory.call_count, 2)

    def test_auth_errors_are_logged_without_treating_them_as_broken_transports(self):
        self.old.error = PermissionError("403 permission denied")
        app = create_app(self.studio, "test", background=False)
        async def run():
            async with self.api_client(app) as client:
                with self.assertLogs("vertex_backend.api", level="WARNING"):
                    self.assertEqual((await client.post("/cloud/check")).status_code, 400)
                self.assertIs(self.studio._cloud, self.old)
                self.assertEqual(self.old.closed, 0)
                self.old.error = None
                self.assertEqual((await client.post("/cloud/check")).status_code, 200)
        asyncio.run(run())
        self.assertEqual(self.factory.call_count, 1)

    def test_failed_create_retires_client_without_replaying_billable_request(self):
        self.old.create_error = httpx.ReadError("EOF")
        batch = self.studio.repo.create("test")
        self.studio.append_task(batch["id"], TaskInput(name="test", prompt="lantern"))
        with self.assertLogs("vertex_backend", level="WARNING"), self.assertRaises(httpx.ReadError):
            self.studio.submit(batch["id"])
        self.assertEqual(self.old.creates, 1)
        self.assertEqual(self.new.creates, 0)
        self.assertEqual(self.factory.call_count, 1)
        self.assertEqual(self.studio.repo.get(batch["id"])["phase"], "submission_unknown")
        self.assertIsNone(self.studio._cloud)


class CloudDiagnosticTests(unittest.TestCase):
    def test_redacts_keys_tokens_headers_and_signed_urls(self):
        text = ('private_key="-----BEGIN PRIVATE KEY-----\nPRIVATE-DATA\n-----END PRIVATE KEY-----" '
                'https://user:proxy-pass@proxy/check?token=query-token '
                'socks5://user:socks-pass@proxy:10808 '
                'access_token=access-secret refresh_token="refresh-secret" '
                'Authorization: Bearer bearer-secret '
                'eyJhbGciOiJSUzI1NiJ9.payload.signature')
        cleaned = redact_cloud_error(text)
        for secret in ["PRIVATE-DATA","proxy-pass","socks-pass","query-token","access-secret",
                       "refresh-secret","bearer-secret","eyJhbGci"]:
            self.assertNotIn(secret, cleaned)
        self.assertIn("proxy/check", cleaned)

    def test_nested_retry_transport_error_is_recognized_but_permissions_are_not(self):
        error = RuntimeError("retry exhausted")
        error.__cause__ = httpx.ProxyError("proxy disconnected")
        self.assertTrue(is_transport_error(error))
        self.assertTrue(is_transport_error(RuntimeError("Cannot send a request, as the client has been closed.")))
        self.assertFalse(is_transport_error(PermissionError("403 forbidden")))

    def test_sdk_close_waits_for_lookup_worker_and_closes_both_transports_once(self):
        cloud = GoogleCloud.__new__(GoogleCloud)
        cloud._lookup_lock = threading.Lock()
        cloud._lookups = {}
        cloud._closing = cloud._closed = False
        cloud.lookup_timeout = .01
        cloud.genai, cloud.storage = Mock(), Mock()
        entered, release = threading.Event(), threading.Event()
        def lookup(*_):
            entered.set()
            release.wait(3)
            return []
        cloud._find_jobs = lookup
        try:
            with self.assertRaises(TimeoutError):
                cloud.find_jobs("name", "uri")
            self.assertTrue(entered.is_set())
            cloud.close()
            cloud.genai.close.assert_not_called()
            cloud.storage.close.assert_not_called()
        finally:
            release.set()
            deadline = time.monotonic() + 2
            while not cloud._closed and time.monotonic() < deadline:
                time.sleep(.01)
        cloud.close()
        cloud.genai.close.assert_called_once()
        cloud.storage.close.assert_called_once()

    def test_storage_transport_closes_even_when_genai_close_fails(self):
        cloud = GoogleCloud.__new__(GoogleCloud)
        cloud._lookup_lock = threading.Lock()
        cloud._lookups = {}
        cloud._closing = cloud._closed = False
        cloud.genai, cloud.storage = Mock(), Mock()
        cloud.genai.close.side_effect = RuntimeError("close failed")
        with self.assertRaises(RuntimeError):
            cloud.close()
        cloud.storage.close.assert_called_once()
