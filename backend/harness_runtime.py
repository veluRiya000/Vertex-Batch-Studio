"""Own the optional DSH process; credentials stay in the Python model broker."""
from pathlib import Path
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from urllib.parse import urlsplit
from .harness_profiles import PROFILES
from .lifecycle import (
    CREATE_SUSPENDED,
    WindowsJobObject,
    log_lifecycle_event,
    process_creation_filetime,
    resume_process_handle,
)

logger = logging.getLogger("vertex_backend.harness_runtime")

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
    def __init__(self, settings, instance_id: str | None = None):
        self.settings = settings
        self.instance_id = instance_id
        self.child = None
        self.child_created_filetime = None
        self._job: WindowsJobObject | None = None
        self._reader_thread: threading.Thread | None = None
        self._shutdown_ack = threading.Event()
        self.shutting_down = False
        self.last_close_result = None
        self.url = None
        self.error = None
        self.offline = None
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self.ui_request_seq = 0
        self.ui_request_tab = "cloud"

    def request_stop(self):
        """Mark the runtime as shutting down so no in-flight request can spawn Node."""
        self.shutting_down = True
        self._ready.set()

    @property
    def source(self):
        import sys
        if getattr(sys, "frozen", False):
            # The combined installer owns this versioned runtime. User sessions
            # stay outside the installation folder, under settings.data_dir.
            bundled = node_path(Path(sys.executable).resolve().parent.parent / "harness")
            if (bundled / "component-manifest.json").is_file():
                return bundled
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
        limits = {"budgetUsd": 5, "maxRounds": 20, "maxOutputTokens": 65536, "limitsEnabled": False}
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
        if self.shutting_down:
            raise ValueError("工作室正在退出")
        with self._lock:
            if self.shutting_down:
                raise ValueError("工作室正在退出")
            if self.child is not None and self.child.poll() is None:
                if offline != self.offline:
                    raise ValueError("请停止当前 Harness 后台，再切换离线或云端验收")
            else:
                if self._job is not None:
                    self._job.close()
                    self._job = None
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
                import inspect
                generate = profile_builder["generate"]
                if "output" in inspect.signature(generate).parameters:
                    profile = generate(self.source, output=node_path(self.settings.root / ".runtime/harness-profile.yml"))
                else:
                    # Compatibility with an older, separately installed component.
                    profile = generate(self.source)
                home = self.settings.data_dir / "harness/home"
                home.mkdir(parents=True, exist_ok=True)
                workspace_parent = self.settings.data_dir / "harness/workspaces"
                workspace_parent.mkdir(parents=True, exist_ok=True)
                if offline:
                    fixture = workspace_parent / "deepseek-harness/default-workspace/README.md"
                    fixture.parent.mkdir(parents=True, exist_ok=True)
                    if not fixture.exists():
                        fixture.write_text("# Vertex Harness offline fixture\n\nRead this file to verify the local tool loop. No cloud calls.\n", encoding="utf-8")
                env = {k: v for k, v in os.environ.items() if not any(word in k.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD", "GOOGLE_", "DEEPSEEK_"))}
                env.update(
                    DSH_HOME=str(node_path(home)),
                    DSH_TELEMETRY_DISABLED="1",
                    DSH_OTEL_SESSION_LOG_DISABLED="1",
                    VBS_HARNESS_BROKER_URL=broker_url,
                    VBS_HARNESS_BROKER_TOKEN=broker_token,
                    VBS_HARNESS_WORKSPACE_PARENT=str(node_path(workspace_parent)),
                    VBS_HARNESS_OFFLINE="1" if offline else "0",
                    VBS_HARNESS_MANAGED="1",
                    VBS_HARNESS_PARENT_PID=str(os.getpid()),
                )
                if self.instance_id:
                    env["VBS_INSTANCE_ID"] = self.instance_id
                self.url = None
                self.error = None
                self.offline = offline
                self._ready.clear()
                self._shutdown_ack.clear()
                command = [str(node), str(self.source / "upstream/apps/cli/lib/bin.js"),
                           "--patch", str(profile), "--profile", "web",
                           "--no-open", "--host", "127.0.0.1", "--port", "0"]
                if self.shutting_down:
                    raise ValueError("工作室正在退出")
                flags = (subprocess.CREATE_NO_WINDOW | CREATE_SUSPENDED) if os.name == "nt" else 0
                child = subprocess.Popen(
                    command,
                    cwd=self.source / "upstream",
                    env=env,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=flags,
                )
                raw_handle = getattr(child, "_handle", None)
                if os.name == "nt" and isinstance(raw_handle, int):
                    job = None
                    try:
                        job = WindowsJobObject.create()
                        job.assign_process_handle(int(raw_handle))
                        resume_process_handle(int(raw_handle))
                        self._job = job
                    except Exception as exc:
                        log_lifecycle_event(
                            self.settings.root,
                            "harness_job_assign_failed",
                            instance_id=self.instance_id,
                            harness_pid=child.pid,
                            error=str(exc),
                        )
                        try:
                            child.kill()
                            child.wait(timeout=2)
                        except Exception:
                            pass
                        if job is not None:
                            job.close()
                        raise ValueError(f"Harness 受管作业初始化失败: {exc}") from exc
                self.child = child
                self.child_created_filetime = process_creation_filetime(child.pid)
                log_lifecycle_event(
                    self.settings.root,
                    "harness_started",
                    instance_id=self.instance_id,
                    harness_pid=child.pid,
                    harness_created_filetime=self.child_created_filetime,
                    node_executable=str(node),
                    offline=bool(offline),
                    job_managed=self._job is not None,
                )

                def read_output(proc):
                    log_dir = self.settings.root / ".runtime"
                    log_dir.mkdir(parents=True, exist_ok=True)
                    try:
                        with (log_dir / "harness.log").open("a", encoding="utf-8") as log:
                            for line in proc.stdout:
                                if "vbs-shutdown-ack" in line:
                                    self._shutdown_ack.set()
                                found = re.search(r"http://127\.0\.0\.1:\d+/\?token=[A-Za-z0-9_.~%-]+", line)
                                if found:
                                    self.url = found[0]
                                    self._ready.set()
                                    log.write("Harness host ready\n")
                                else:
                                    # Never persist authentication URLs or the private bridge credential.
                                    log.write(line.replace(broker_token, "[redacted]") if "token=" not in line else "[authentication URL omitted]\n")
                                log.flush()
                    except (OSError, ValueError):
                        pass
                    if not self.url and not self.shutting_down:
                        self.error = "Harness 启动失败，请查看本地运行日志"
                    self._ready.set()

                self._reader_thread = threading.Thread(target=read_output, args=(self.child,), daemon=True)
                self._reader_thread.start()
        if not self._ready.wait(60):
            raise ValueError("Harness 正在启动，请稍后重试；不会重复启动进程")
        if self.shutting_down:
            raise ValueError("工作室正在退出")
        if not self.url or self.child is None or self.child.poll() is not None:
            raise ValueError(self.error or "Harness 后台已退出")
        return self.url

    def close(self, timeout: float = 8.5):
        started = time.monotonic()
        deadline = started + max(1.0, float(timeout))
        self._ready.set()
        acquired = self._lock.acquire(timeout=max(0.1, min(1.5, deadline - time.monotonic())))
        try:
            child = self.child
            job = self._job
            reader = self._reader_thread
            created_ft = self.child_created_filetime
            if not child:
                if job is not None:
                    job.close()
                    self._job = None
                self.url = None
                self.offline = None
                result = {"status": "idle", "elapsed_ms": round((time.monotonic() - started) * 1000, 1)}
                self.last_close_result = result
                return result

            pid = getattr(child, "pid", None)
            stdin_sent = False
            forced = False
            taskkill_rc = None
            taskkill_err = None
            job_terminate_err = None
            exit_code = child.poll()

            log_lifecycle_event(
                self.settings.root,
                "harness_close_start",
                instance_id=self.instance_id,
                harness_pid=pid,
                harness_created_filetime=created_ft,
                already_exited=exit_code is not None,
                initial_exit_code=exit_code,
            )

            try:
                if exit_code is None:
                    # Ask our plugin to enter the upstream CLI's bounded graceful shutdown.
                    # Application exit keeps cloud jobs alive for receipt reconciliation.
                    try:
                        if child.stdin:
                            child.stdin.write("vbs-shutdown\n")
                            child.stdin.flush()
                            stdin_sent = True
                        grace = max(0.2, min(4.5, deadline - time.monotonic() - 2.5))
                        child.wait(timeout=grace)
                    except (OSError, ValueError, subprocess.TimeoutExpired):
                        pass
                    exit_code = child.poll()

                job_active = 0
                if job is not None:
                    try:
                        job_active = job.active_processes()
                    except OSError:
                        job_active = 0
                    if exit_code is not None and job_active > 0:
                        wait_until = min(deadline - 1.5, time.monotonic() + 1.0)
                        while time.monotonic() < wait_until and job_active > 0:
                            time.sleep(0.05)
                            try:
                                job_active = job.active_processes()
                            except OSError:
                                job_active = 0
                                break

                if exit_code is None or job_active > 0:
                    forced = True
                    try:
                        if child.stdin:
                            child.stdin.close()
                    except (OSError, ValueError):
                        pass
                    if job is not None:
                        job_terminate_err = job.terminate(1)
                    if exit_code is None and os.name == "nt":
                        try:
                            tk_timeout = max(1.0, min(3.0, deadline - time.monotonic()))
                            res = subprocess.run(
                                ["taskkill", "/PID", str(pid), "/T", "/F"],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE,
                                creationflags=subprocess.CREATE_NO_WINDOW,
                                timeout=tk_timeout,
                                text=True,
                                errors="replace",
                            )
                            taskkill_rc = res.returncode
                            taskkill_err = (res.stderr or "").strip() or None
                            if res.returncode != 0 and child.poll() is None:
                                logger.warning("Harness taskkill exited with code %s: %s", res.returncode, taskkill_err)
                        except Exception as exc:
                            taskkill_err = str(exc)
                            logger.warning("Harness taskkill failed: %s", exc)
                    elif exit_code is None:
                        child.terminate()
                        try:
                            child.wait(timeout=max(0.5, min(2.0, deadline - time.monotonic())))
                        except subprocess.TimeoutExpired:
                            child.kill()
                    try:
                        child.wait(timeout=max(0.2, min(2.0, deadline - time.monotonic())))
                    except (subprocess.TimeoutExpired, OSError):
                        try:
                            child.kill()
                        except OSError:
                            pass
                    exit_code = child.poll()
            finally:
                try:
                    if child.stdin:
                        child.stdin.close()
                except (OSError, ValueError):
                    pass
                if reader is not None and reader is not threading.current_thread():
                    reader.join(timeout=0.3)
                try:
                    if child.stdout:
                        child.stdout.close()
                except (OSError, ValueError):
                    pass

                final_job_active = 0
                if job is not None:
                    try:
                        final_job_active = job.active_processes()
                    except OSError:
                        final_job_active = 0
                    job.close()
                    self._job = None

                elapsed_ms = round((time.monotonic() - started) * 1000, 1)
                result = {
                    "status": "stopped" if (exit_code is not None and final_job_active == 0) else "residual_warning",
                    "pid": pid,
                    "exit_code": exit_code,
                    "stdin_sent": stdin_sent,
                    "ack_received": self._shutdown_ack.is_set(),
                    "forced": forced,
                    "taskkill_returncode": taskkill_rc,
                    "taskkill_error": taskkill_err,
                    "job_terminate_error": job_terminate_err,
                    "job_active_before_close": final_job_active,
                    "elapsed_ms": elapsed_ms,
                }
                self.last_close_result = result
                log_lifecycle_event(
                    self.settings.root,
                    "harness_close_complete",
                    instance_id=self.instance_id,
                    **result,
                )
                if exit_code is not None and final_job_active == 0:
                    self.child = None
                    self.child_created_filetime = None
                self.url = None
                self.offline = None
            return self.last_close_result
        finally:
            if acquired:
                self._lock.release()
