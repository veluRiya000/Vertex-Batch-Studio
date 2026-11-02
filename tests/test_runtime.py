"""Actual localhost server startup/shutdown, not just in-process route tests."""

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import threading
import unittest
import httpx


class RuntimeTests(unittest.TestCase):
    def test_local_server_lifecycle(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            process = subprocess.Popen(
                [sys.executable, "-X", "utf8", "-m", "backend", "--root", str(root), "serve"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
            try:
                connection = root / ".runtime/connection.json"
                deadline = time.monotonic() + 15
                while not connection.exists():
                    if process.poll() is not None:
                        out, err = process.communicate()
                        self.fail("Server exited: " + err.decode("utf-8", errors="replace"))
                    if time.monotonic() > deadline:
                        self.fail("Server startup timed out")
                    time.sleep(0.05)
                info = json.loads(connection.read_text(encoding="utf-8"))
                from backend.lifecycle import is_process_alive_with_identity
                self.assertEqual(info["pid"], process.pid)
                self.assertEqual(info["mode"], "standalone")
                self.assertTrue(info.get("instance_id"))
                self.assertTrue(is_process_alive_with_identity(
                    info["pid"], info.get("process_created_filetime"), info.get("executable")
                ))
                with httpx.Client(base_url=info["url"], trust_env=False, timeout=5) as client:
                    for _ in range(100):
                        try:
                            unauthorized = client.get("/health")
                            break
                        except httpx.ConnectError:
                            time.sleep(0.05)
                    self.assertEqual(unauthorized.status_code, 401)
                    client.headers["X-VBS-Token"] = info["token"]
                    self.assertEqual(client.get("/health").status_code, 200)
                    created = client.post("/batches", json={"project_name": "运行测试"})
                    self.assertEqual(created.status_code, 201)
                    # Leave a real progress stream open as the desktop does.
                    # Shutdown must end it rather than wait indefinitely for it.
                    entered = threading.Event()
                    finished = threading.Event()
                    def progress():
                        try:
                            with httpx.Client(trust_env=False, timeout=10) as stream_client:
                                with stream_client.stream('GET', info['url'] + '/batches/' + created.json()['id'] + '/events',
                                        headers={'X-VBS-Token': info['token']}) as response:
                                    for line in response.iter_lines():
                                        if line.startswith('data:'):
                                            entered.set()
                        finally:
                            finished.set()
                    reader = threading.Thread(target=progress, daemon=True)
                    reader.start()
                    self.assertTrue(entered.wait(5))
                    stopping_at = time.monotonic()
                    stopped = subprocess.run(
                        [sys.executable, "-X", "utf8", "-m", "backend", "--root", str(root), "stop"],
                        capture_output=True, timeout=15)
                    self.assertEqual(stopped.returncode, 0, stopped.stderr.decode("utf-8", errors="replace"))
                    self.assertEqual(json.loads(stopped.stdout)["status"], "stopping")
                process.communicate(timeout=8)
                self.assertEqual(process.returncode, 0)
                self.assertLess(time.monotonic() - stopping_at, 6)
                self.assertTrue(finished.wait(1))
                self.assertFalse(connection.exists())
                self.assertFalse(is_process_alive_with_identity(
                    info["pid"], info.get("process_created_filetime"), info.get("executable")
                ))
                lifecycle_events = [
                    json.loads(line)["event"]
                    for line in (root / ".runtime/lifecycle.log").read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
                self.assertIn("backend_start", lifecycle_events)
                self.assertIn("shutdown_requested", lifecycle_events)
                self.assertIn("lifespan_shutdown_complete", lifecycle_events)
                self.assertIn("backend_exit", lifecycle_events)
                self.assertTrue(list((root / 'data/batches').glob('*/batch.json')))
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.communicate(timeout=10)
