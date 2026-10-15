"""Completion reminders owned by the backend, independent of visible WebViews."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import os
from pathlib import Path, PureWindowsPath
import queue
import re
import struct
import subprocess
import threading
import time
import wave

from .files import atomic_bytes, read_json, write_json
from .preferences import load_preferences


# All dynamic strings travel through JSON stdin, never PowerShell interpolation.
# Silent WinRT audio prevents a second Windows sound on top of the selected tone.
WINDOWS_HELPER = r'''
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
[Console]::InputEncoding=[Text.Encoding]::UTF8
[Console]::OutputEncoding=[Text.Encoding]::UTF8
$v=[Console]::In.ReadToEnd() | ConvertFrom-Json
try {
  if (-not $v.sound_only) {
    [Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime] > $null
    [Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom,ContentType=WindowsRuntime] > $null
    [Windows.UI.Notifications.NotificationSetting,Windows.UI.Notifications,ContentType=WindowsRuntime] > $null
    $notifier=[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('com.vertexbatchstudio.notifications')
    if ($notifier.Setting.ToString() -ne 'Enabled') { throw 'Windows notifications are disabled for Vertex Batch Studio' }
    $xml=New-Object Windows.Data.Xml.Dom.XmlDocument
    $xml.LoadXml('<toast><visual><binding template="ToastGeneric"><text/><text/></binding></visual><audio silent="true"/></toast>')
    $texts=$xml.GetElementsByTagName('text')
    $texts.Item(0).AppendChild($xml.CreateTextNode([string]$v.title)) > $null
    $texts.Item(1).AppendChild($xml.CreateTextNode([string]$v.body)) > $null
    $toast=[Windows.UI.Notifications.ToastNotification]::new($xml)
    $toast.Tag=[string]$v.tag
    $toast.Group='completion'
    $toast.ExpirationTime=[DateTimeOffset]::Now.AddHours(12)
    $notifier.Show($toast)
  }
  if ($v.sound) {
    Add-Type -AssemblyName PresentationCore
    Add-Type -AssemblyName WindowsBase
    $player=[System.Windows.Media.MediaPlayer]::new()
    $frame=[System.Windows.Threading.DispatcherFrame]::new()
    $script:audioError=$null
    $player.add_MediaEnded({$frame.Continue=$false}.GetNewClosure())
    $player.add_MediaFailed({param($s,$e) $script:audioError=$e.ErrorException.Message; $frame.Continue=$false}.GetNewClosure())
    $timer=[System.Windows.Threading.DispatcherTimer]::new()
    $timer.Interval=[TimeSpan]::FromSeconds(10)
    $timer.add_Tick({$frame.Continue=$false}.GetNewClosure())
    $timer.Start()
    try {
      $player.Open([Uri]::new([string]$v.sound))
      $player.Volume=0.65
      $player.Play()
      [System.Windows.Threading.Dispatcher]::PushFrame($frame)
      if ($script:audioError) {throw $script:audioError}
    } finally {$timer.Stop(); $player.Close()}
  }
  [Console]::Out.Write('ok')
} catch {[Console]::Error.Write($_.Exception.Message); exit 1}
'''


def windows_local_path(path):
    """Convert Rust's verbatim Windows paths to shell/media-compatible paths."""
    value = str(path)
    if value.startswith("\\\\?\\UNC\\"):
        return "\\\\" + value[8:]
    if value.startswith("\\\\?\\"):
        return value[4:]
    return value


def windows_media_uri(path):
    # Encode spaces, Unicode, # and % once; never treat a drive path as a host.
    return PureWindowsPath(windows_local_path(path)).as_uri()


class WindowsNotifier:
    def __init__(self, folder: Path):
        self.folder = folder
        self._lock = threading.Lock()
        self._child = None

    def register(self):
        if os.name != "nt":
            raise ValueError("完成提醒需要 Windows 桌面环境")
        import winreg
        # Unpackaged apps need an AUMID registered for the interactive user.
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Classes\AppUserModelId\com.vertexbatchstudio.notifications") as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "Vertex Batch Studio")
            icon = self.folder / "app-icon.png"
            if icon.is_file():
                winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, windows_local_path(icon))

    def send(self, title, body, sound, *, sound_only=False, tag="preview"):
        with self._lock:
            self.register()
            exe = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
            command = base64.b64encode(WINDOWS_HELPER.encode("utf-16le")).decode("ascii")
            self._child = subprocess.Popen(
                [str(exe), "-NoLogo", "-NoProfile", "-NonInteractive", "-STA", "-OutputFormat", "Text", "-EncodedCommand", command],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                data = json.dumps(dict(title=title, body=body, sound=windows_media_uri(sound) if sound else None,
                                      sound_only=sound_only, tag=tag[:16]), ensure_ascii=False).encode("utf-8")
                out, error = self._child.communicate(data, timeout=18)
                if self._child.returncode or out.decode("utf-8-sig").strip() != "ok":
                    detail = error.decode("utf-8-sig", errors="replace")
                    raise ValueError("Windows 提醒未能完成：" + detail[:600])
            except subprocess.TimeoutExpired:
                self._child.kill()
                self._child.communicate()
                raise ValueError("Windows 提醒响应超时") from None
            finally:
                self._child = None

    def close(self):
        child = self._child
        if child is not None:
            try:
                child.terminate()
            except OSError:
                pass


class SoundLibrary:
    MAX_BYTES = 5 * 1024 * 1024

    def __init__(self, folder):
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)

    def import_sound(self, name, encoded):
        ext = Path(name).suffix.lower()
        if ext not in {".wav", ".mp3"}:
            raise ValueError("请选择 WAV 或 MP3 音频")
        if len(encoded) > (self.MAX_BYTES + 2) // 3 * 4:
            raise ValueError("提醒音频不能超过 5 MB")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            raise ValueError("音频文件编码无效") from None
        if not data or len(data) > self.MAX_BYTES:
            raise ValueError("提醒音频不能为空或超过 5 MB")
        if ext == ".wav":
            try:
                with wave.open(io.BytesIO(data)) as audio:
                    if not audio.getnframes() or not audio.getframerate():
                        raise ValueError()
            except (wave.Error, EOFError, ValueError):
                raise ValueError("请选择有效的 PCM WAV 音频") from None
        elif not (data.startswith(b"ID3") or (len(data) > 2 and data[0] == 255 and data[1] & 224 == 224)):
            raise ValueError("请选择有效的 MP3 音频")
        ident = hashlib.sha256(data).hexdigest() + ext
        atomic_bytes(self.folder / ident, data)
        return {"custom_sound_id": ident, "custom_sound_name": Path(name.replace("\\", "/")).name[:160]}

    def resolve(self, preferences):
        if not preferences.sound_enabled:
            return None
        if preferences.sound == "custom":
            ident = preferences.custom_sound_id or ""
            if not re.fullmatch(r"[a-f0-9]{64}\.(?:wav|mp3)", ident):
                raise ValueError("请先导入自定义提醒音频")
            path = self.folder / ident
            if not path.is_file():
                raise ValueError("自定义提醒音频已丢失，请重新导入")
            return path
        path = self.folder / (preferences.sound + ".wav")
        if not path.is_file():
            notes = {"soft": [660, 880], "chime": [784, 988, 1175], "double": [880, 0, 880]}[preferences.sound]
            samples = bytearray()
            rate = 22050
            for frequency in notes:
                length = int(rate * 0.22)
                for i in range(length):
                    envelope = min(i / (rate * .015), 1) * math.exp(-4 * i / length)
                    value = math.sin(2 * math.pi * frequency * i / rate) if frequency else 0
                    samples.extend(struct.pack("<h", int(9000 * envelope * value)))
            output = io.BytesIO()
            with wave.open(output, "wb") as audio:
                audio.setparams((1, 2, rate, 0, "NONE", "not compressed"))
                audio.writeframes(samples)
            atomic_bytes(path, output.getvalue())
        return path


def completion_snapshot(studio, harness):
    """Whole image jobs / Agent runs only; an individual model step is never a task."""
    items = {}
    for batch in studio.repo.list():
        phase = batch["phase"]
        status = ("success" if phase in {"completed", "completed_with_errors"} else
                  "failed" if phase in {"failed", "upload_failed", "submission_failed"} else
                  "cancelled" if phase == "cancelled" else
                  "idle" if phase in {"draft", "prepared"} else "active")
        items["image:" + batch["id"]] = dict(status=status, kind="image", name=batch["project_name"],
                                             warning=phase == "completed_with_errors")
    with harness.connection() as db:
        runs = [json.loads(row[0]) for row in db.execute("SELECT data FROM runs")]
    for run in runs:
        status = "success" if run["phase"] == "completed" else "active"
        if run["phase"] == "paused":
            with harness.connection() as db:
                receipts = [json.loads(row[0]) for row in db.execute(
                    "SELECT data FROM requests WHERE run_id=? ORDER BY rowid", (run["run_id"],))]
            # Pausing the Agent does not cancel an accepted cloud job. Only real
            # in-flight receipts keep this queue active, never a historical pause.
            if any(receipt["phase"] not in {"completed", "failed", "cancelled", "budget_paused"}
                   for receipt in receipts):
                status = "active"
            elif receipts and (receipts[-1]["phase"] == "failed" or receipts[-1].get("truncated")):
                status = "failed"
            elif receipts and receipts[-1]["phase"] == "cancelled":
                status = "cancelled"
            else:
                status = "paused"
        items["harness:" + run["run_id"]] = dict(status=status, kind="harness", name=Path(run["workspace"]).name)
    return items


class CompletionTracker:
    """Persist observations before dispatch: refresh/restart cannot replay the same reminder.

    Each mode has its own cohort, growing while submitted work remains. Drafts
    and locally paused runs do not block it; unresolved cloud jobs do.
    Disabling reminders consumes events.
    """
    TERMINAL = {"success", "failed", "cancelled"}

    def __init__(self, path):
        self.path = path
        try:
            self.state = read_json(path) if path.exists() else {"seen": {}, "pending": {}, "config": None}
            if not isinstance(self.state.get("seen"), dict) or not isinstance(self.state.get("pending"), dict):
                raise ValueError("Invalid reminder state")
        except (OSError, ValueError, AttributeError):
            # This auxiliary ledger must never prevent opening sessions or image jobs.
            if path.exists():
                atomic_bytes(path.with_name("observed-recovery.json"), path.read_bytes())
            self.state = {"seen": {}, "pending": {}, "config": None}
        self.started = False

    def poll(self, items, prefs):
        state = self.state
        previous = state["seen"]
        config = [prefs.enabled, prefs.mode, prefs.image_batches, prefs.harness_tasks, prefs.include_failures]
        if state["config"] != config:
            state["pending"] = {}
        pending = state["pending"]
        events = []
        for key, item in items.items():
            old = previous.get(key)
            selected = prefs.image_batches if item["kind"] == "image" else prefs.harness_tasks
            if not prefs.enabled or not selected:
                continue
            if item["status"] in {"idle", "paused"}:
                pending.pop(key, None)
            if item["status"] == "active":
                pending[key] = item
            if item["status"] in self.TERMINAL:
                # Ignore historical terminal rows on first launch, including archives.
                changed = old is not None and old["status"] not in self.TERMINAL and (old["status"] != "idle" or self.started)
                if changed and key not in pending:
                    pending[key] = item
                if key in pending:
                    pending[key] = item
                if changed and prefs.mode == "each" and (item["status"] == "success" or
                                                         item["status"] == "failed" and prefs.include_failures):
                    events.append([item])
        # A vanished item was deleted; it must not leave a cohort stuck forever.
        for key in list(pending):
            if key not in items:
                del pending[key]
        # Independent queues: even an active Agent must not suppress image
        # reminders. Grouping also migrates persisted mixed cohorts in place.
        for kind in ("image", "harness"):
            cohort = {key: item for key, item in pending.items() if item["kind"] == kind}
            if cohort and all(item["status"] in self.TERMINAL for item in cohort.values()):
                ready = [item for item in cohort.values() if item["status"] == "success" or
                         item["status"] == "failed" and prefs.include_failures]
                if prefs.mode == "all" and ready:
                    events.append(ready)
                for key in cohort:
                    del pending[key]
        state["seen"] = items
        state["config"] = config
        if state != getattr(self, "_saved", None):
            write_json(self.path, state)
            self._saved = json.loads(json.dumps(state))
        self.started = True
        return events


class NotificationCenter:
    def __init__(self, studio, harness, sender=None):
        self.studio, self.harness = studio, harness
        self.folder = studio.settings.data_dir / "notifications"
        self.sounds = SoundLibrary(self.folder)
        icon = self.folder / "app-icon.png"
        logo_bytes = base64.b64decode("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")
        if not icon.is_file() or icon.read_bytes() != logo_bytes:
            atomic_bytes(icon, logo_bytes)
        self.sender = sender or WindowsNotifier(self.folder)
        self.tracker = CompletionTracker(self.folder / "observed.json")
        self.stop = threading.Event()
        self.work = queue.Queue(maxsize=64)
        self.threads = []
        self.last_error = None
        self.last_sent_at = None

    def start(self):
        # Synchronous baseline, before cloud workers can complete a short job.
        try:
            self.tick()
        except Exception as exc:
            self.last_error = "完成状态读取失败：" + str(exc)[:250]
        for target in (self._monitor, self._dispatch):
            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            self.threads.append(thread)

    def status(self):
        return dict(available=os.name == "nt", last_error=self.last_error, last_sent_at=self.last_sent_at)

    def tick(self):
        prefs = load_preferences(self.studio.settings.root).notifications
        for event in self.tracker.poll(completion_snapshot(self.studio, self.harness), prefs):
            failed = sum(i["status"] == "failed" or i.get("warning", False) for i in event)
            if prefs.mode == "all":
                if event[0]["kind"] == "image":
                    title = "生图批次已全部处理完成" if failed else "生图批次已全部完成"
                else:
                    title = "Harness 本轮运行已结束"
                body = f"已完成 {len(event) - failed} 项" + (f"，{failed} 项失败或部分失败。请打开工作室查看。" if failed else "，可以回来查看结果了。")
            else:
                item = event[0]
                title = ("Harness 任务" if item["kind"] == "harness" else "生图批次") + ("处理失败" if failed else "已完成")
                body = item["name"] + (" · 请查看错误详情" if failed else " · 结果已就绪")
            try:
                self.work.put_nowait((title, body, prefs))
            except queue.Full:
                self.last_error = "待发送提醒过多，部分提醒已跳过"

    def _monitor(self):
        while not self.stop.wait(1):
            try:
                self.tick()
            except Exception as exc:
                self.last_error = "完成状态读取失败：" + str(exc)[:250]

    def _dispatch(self):
        while not self.stop.is_set():
            try:
                title, body, prefs = self.work.get(timeout=.5)
            except queue.Empty:
                continue
            try:
                # Switching notifications off also cancels already queued reminders.
                if load_preferences(self.studio.settings.root).notifications.enabled:
                    self.send(title, body, prefs)
            except Exception:
                pass  # send() records diagnostics; never fail cloud processing.

    def send(self, title, body, prefs, *, sound_only=False):
        try:
            sound = self.sounds.resolve(prefs)
            if sound_only and sound is None:
                raise ValueError("请先开启提醒声音")
            self.sender.send(title, body, sound, sound_only=sound_only,
                             tag=hashlib.sha256(f"{time.time_ns()}".encode()).hexdigest()[:16])
            self.last_error = None
            self.last_sent_at = time.time()
            return {"sent": True, **self.status()}
        except Exception as exc:
            self.last_error = str(exc)
            raise ValueError(self.last_error) from None

    def close(self):
        self.stop.set()
        self.sender.close()
        for thread in self.threads:
            thread.join(timeout=2)
