"""Actual localhost server startup/shutdown, not just in-process route tests."""

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
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
                    stopped = subprocess.run(
                        [sys.executable, "-X", "utf8", "-m", "backend", "--root", str(root), "stop"],
                        capture_output=True, timeout=15)
                    self.assertEqual(stopped.returncode, 0, stopped.stderr.decode("utf-8", errors="replace"))
                    self.assertEqual(json.loads(stopped.stdout)["status"], "stopping")
                process.communicate(timeout=15)
                self.assertEqual(process.returncode, 0)
                self.assertFalse(connection.exists())
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.communicate(timeout=10)
