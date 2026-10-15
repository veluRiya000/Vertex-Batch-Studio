"""Own the optional DSH process; credentials stay in the Python model broker."""
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import threading
import time
from urllib.parse import urlsplit
from .harness_profiles import PROFILES

UPSTREAM_COMMIT = "d743267388641bc76f17c45ce8b4c231aed1d32c"

def node_path(path):
    """Node ESM URLs need ordinary Windows paths, not Rust's verbatim prefix."""
    value = str(path)
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return Path(value)


class HarnessRuntime:
    def __init__(self, settings):
        self.settings = settings
        self.child = None
        self.url = None
        self.error = None
        self.offline = None
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self.ui_request_seq = 0
        self.ui_request_tab = "cloud"

    @property
    def source(self):
        import sys
        if getattr(sys, "frozen", False):
            return node_path(self.settings.root / "components/harness")
        source = node_path(Path(__file__).resolve().parents[1] / "harness")
        component = source / "component"
        if (component / "component-manifest.json").is_file():
            return component
        return source

    def status(self):
        source = self.source
        frontend = source / "upstream/apps/web/dist/index.html"
        if not frontend.is_file():
            frontend = source / "upstream/node_modules/@deepseek-ai/dsh-web-frontend/dist/index.html"
        available = (source / "upstream/apps/cli/lib/bin.js").is_file() and frontend.is_file()
        running = self.child is not None and self.child.poll() is None
        limits = {"budgetUsd": 5, "maxRounds": 20, "maxOutputTokens": 65536, "limitsEnabled": True}
        settings_file = self.settings.data_dir / "harness/home/vbs-run-settings.json"
        if settings_file.is_file():
            try:
                limits.update(json.loads(settings_file.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass
        return {"available": available, "running": running, "ready": running and bool(self.url),
                "error": self.error, "upstream_commit": UPSTREAM_COMMIT,
                "model": "gemini-4-argon", "models": list(PROFILES), "location": "global", "budget_usd": limits["budgetUsd"], "max_rounds": limits["maxRounds"], "max_output_tokens": limits["maxOutputTokens"], "read_only_tools": False, "limits_enabled": limits["limitsEnabled"], "offline": self.offline,
                "validation_required": False, "component_path": str(source), "ui_request_seq": self.ui_request_seq, "ui_request_tab": self.ui_request_tab}

    def request_cloud_settings(self, tab="cloud"):
        # A UI intent only: the scoped DSH process cannot read or change credentials.
        with self._lock:
            self.ui_request_tab = tab
            self.ui_request_seq += 1
            return {"ui_request_seq": self.ui_request_seq}

    def start(self, broker_url, broker_token, offline=False):
        with self._lock:
            if self.child is not None and self.child.poll() is None:
                if offline != self.offline:
                    raise ValueError("请停止当前 Harness 后台，再切换离线或云端验收")
            else:
                if not self.status()["available"]:
                    raise ValueError("Harness 组件尚未构建或安装")
                node = self.source / "node/node.exe"
                if not node.is_file():
                    found = shutil.which("node")
                    if not found:
                        raise ValueError("找不到 Node 运行环境")
                    node = Path(found)
                # Rebuild absolute plugin paths after component install or relocation.
                import runpy
                profile_builder = runpy.run_path(str(self.source / "setup_profile.py"))
                profile_builder["generate"](self.source)
                home = self.settings.data_dir / "harness/home"
                home.mkdir(parents=True, exist_ok=True)
                workspace_parent = self.settings.data_dir / "harness/workspaces"
                workspace_parent.mkdir(parents=True, exist_ok=True)
                if offline:
                    fixture=workspace_parent / "deepseek-harness/default-workspace/README.md"
                    fixture.parent.mkdir(parents=True, exist_ok=True)
                    if not fixture.exists():
                        fixture.write_text("# Vertex Harness offline fixture\n\nRead this file to verify the local tool loop. No cloud calls.\n", encoding="utf-8")
                env = {k: v for k, v in os.environ.items() if not any(word in k.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD", "GOOGLE_", "DEEPSEEK_"))}
                env.update(DSH_HOME=str(node_path(home)), DSH_TELEMETRY_DISABLED="1", DSH_OTEL_SESSION_LOG_DISABLED="1",
                           VBS_HARNESS_BROKER_URL=broker_url, VBS_HARNESS_BROKER_TOKEN=broker_token,
                           VBS_HARNESS_WORKSPACE_PARENT=str(node_path(workspace_parent)),
                           VBS_HARNESS_OFFLINE="1" if offline else "0")
                self.url = None
                self.error = None
                self.offline = offline
                self._ready.clear()
                command = [str(node), str(self.source / "upstream/apps/cli/lib/bin.js"),
                           "--patch", str(self.source / "studio.patch.yml"), "--profile", "web",
                           "--no-open", "--host", "127.0.0.1", "--port", "0"]
                self.child = subprocess.Popen(command, cwd=self.source / "upstream", env=env,
                                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                              text=True, encoding="utf-8", errors="replace",
                                              creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                def read_output(child):
                    log_dir = self.settings.root / ".runtime"
                    log_dir.mkdir(parents=True, exist_ok=True)
                    with (log_dir / "harness.log").open("a", encoding="utf-8") as log:
                        for line in child.stdout:
                            found = re.search(r"http://127\.0\.0\.1:\d+/\?token=[A-Za-z0-9_.~%-]+", line)
                            if found:
                                self.url = found[0]
                                self._ready.set()
                                log.write("Harness host ready\n")
                            else:
                                # Never persist authentication URLs or the private bridge credential.
                                log.write(line.replace(broker_token, "[redacted]") if "token=" not in line else "[authentication URL omitted]\n")
                            log.flush()
                    if not self.url:
                        self.error = "Harness 启动失败，请查看本地运行日志"
                    self._ready.set()
                threading.Thread(target=read_output, args=(self.child,), daemon=True).start()
        if not self._ready.wait(60):
            raise ValueError("Harness 正在启动，请稍后重试；不会重复启动进程")
        if not self.url or self.child.poll() is not None:
            raise ValueError(self.error or "Harness 后台已退出")
        return self.url

    def close(self):
        with self._lock:
            child = self.child
            if child and child.poll() is None:
                # Ask our plugin to enter the upstream CLI's bounded graceful shutdown.
                # Application exit keeps cloud jobs alive for receipt reconciliation.
                try:
                    child.stdin.write("vbs-shutdown\n")
                    child.stdin.flush()
                    child.wait(timeout=8)
                except (OSError, subprocess.TimeoutExpired):
                    pass
                if child.poll() is None and os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
                elif child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill()
                child.wait(timeout=10)
            self.child = None
            self.url = None
            self.offline = None
