"""Local authenticated HTTP API, with asynchronous job operations and SSE snapshots."""

import asyncio
from contextlib import asynccontextmanager
import json
import logging
import secrets

logger = logging.getLogger("vertex_backend.api")
import time
import tempfile
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from . import __version__
from .files import BusyError
from .files import filename, read_json, beneath, sha256_file
from .assets import inspect_image
from .jsonl import import_jsonl
from .models import (BatchCreate, ReferenceImport, TasksReplace, TaskInput,
                     JsonlImport, OutputDirectory, InputModel, WorkspaceRename)
from .service import Studio
from .preferences import Preferences, load_preferences, save_preferences
from .connection import CloudConfiguration, configure_cloud
from .model_catalog import select_model
from .model_parameters import unsupported_generation_parameters


class AttachJob(InputModel):
    job_name: str


class ModelSelection(InputModel):
    model: str


class ReferenceOrder(InputModel):
    category: str
    paths: list[str]


class ReferenceCategory(InputModel):
    label: str


class ReferenceMove(InputModel):
    path: str
    category: str


def create_app(studio: Studio, token: str, on_shutdown=None,
               background: bool = True, instance_id: str | None = None,
               mode: str = "standalone") -> FastAPI:
    if not token:
        raise ValueError("本地 API 必须设置访问令牌")

    from .harness_batch import HarnessBatch
    from .harness_runtime import HarnessRuntime
    from .harness_api import mount_harness
    from .lifecycle import log_lifecycle_event
    harness = HarnessBatch(studio)
    harness_runtime = HarnessRuntime(studio.settings, instance_id=instance_id)
    harness_token = secrets.token_urlsafe(32)
    from .notifications import NotificationCenter
    notifications = NotificationCenter(studio, harness)

    @asynccontextmanager
    async def lifespan(app):
        if background:
            notifications.start()
            studio.start()
            harness.start()
        try:
            yield
        finally:
            shutdown_started = time.monotonic()
            app.state.shutting_down = True
            studio.request_stop()
            harness.request_stop()
            harness_runtime.request_stop()
            log_lifecycle_event(
                studio.settings.root,
                "lifespan_shutdown_start",
                instance_id=instance_id,
                mode=mode,
            )
            # Independent shutdowns share one grace period; never wait for a
            # remote inference or network retry before asking Node to flush logs.
            results = await asyncio.gather(
                asyncio.to_thread(notifications.close),
                asyncio.to_thread(harness_runtime.close),
                asyncio.to_thread(harness.close, wait=False),
                asyncio.to_thread(studio.close, wait=False), return_exceptions=True)
            errors = {}
            for name, res in zip(["notifications", "harness_runtime", "harness", "studio"], results):
                if isinstance(res, BaseException):
                    errors[name] = f"{type(res).__name__}: {res}"
                    logger.error("Error shutting down %s: %s", name, res, exc_info=res)
            log_lifecycle_event(
                studio.settings.root,
                "lifespan_shutdown_complete",
                instance_id=instance_id,
                mode=mode,
                elapsed_ms=round((time.monotonic() - shutdown_started) * 1000, 1),
                harness_close=results[1] if isinstance(results[1], dict) else None,
                errors=errors,
            )

    app = FastAPI(title="VertexBatchStudio", version=__version__, lifespan=lifespan)
    app.state.shutting_down = False

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        if request.client and request.client.host not in {"127.0.0.1", "::1", "testclient"}:
            return JSONResponse({"detail": "只接受本机连接"}, status_code=403)
        given = request.headers.get("X-VBS-Token", "")
        import re
        scoped = request.headers.get("X-VBS-Harness-Token", "")
        provider_route = re.fullmatch(r"/harness/(?:requests(?:/[a-f0-9]{64}(?:/(?:cancel|resume|events))?)?|runs(?:/[a-f0-9]{64}/(?:pause|resume|finish))?)", request.url.path)
        ui_route = request.method == "POST" and request.url.path in {"/harness/ui/cloud-settings", "/harness/ui/notification-settings"}
        scoped_valid = bool(provider_route or ui_route) and secrets.compare_digest(scoped, harness_token)
        if not secrets.compare_digest(given, token) and not scoped_valid:
            return JSONResponse({"detail": "本地访问令牌无效"}, status_code=401)
        if app.state.shutting_down and request.url.path != "/shutdown":
            return JSONResponse({"detail": "工作室正在退出"}, status_code=503)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(BusyError)
    async def busy(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(KeyError)
    async def not_found(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.get("/health")
    def health():
        return {"status": "ok", "version": __version__,
                "project_configured": bool(studio.settings.project),
                "bucket_configured": bool(studio.settings.bucket)}

    @app.get("/references")
    def references(batch_id: str | None = None):
        return studio.assets.list(batch_id)

    @app.get("/references/categories")
    def reference_categories():
        return studio.assets.categories()

    @app.post("/references/categories", status_code=201)
    def add_reference_category(value: ReferenceCategory):
        return studio.assets.add_category(value.label)

    @app.delete("/references/categories/{category}")
    def delete_reference_category(category: str, move_to: str | None = None):
        return studio.assets.delete_category(category, move_to)

    @app.post('/references/move')
    def move_reference(value: ReferenceMove):
        return studio.assets.move(value.path, value.category)

    @app.post("/batches/{batch_id}/open-folder")
    def open_batch_folder(batch_id: str):
        # Only resolve managed batch paths; never accept arbitrary shell commands.
        directory = studio.repo.directory(batch_id)
        import os
        if os.name != "nt":
            raise ValueError("此操作需要 Windows 桌面")
        os.startfile(str(directory))
        return {"opened": True}

    @app.put('/references/order')
    def reorder_references(value: ReferenceOrder):
        return studio.assets.reorder(value.category, value.paths)

    @app.delete("/references")
    def delete_reference(path: str):
        return studio.assets.delete(path)

    @app.get("/config")
    def public_config():
        settings = studio.settings
        return {"project": settings.project, "bucket": settings.bucket, "model": settings.model,
                "location": settings.location, "data_dir": str(settings.data_dir),
                "root": str(settings.root), "poll_seconds": settings.poll_seconds,
                "credentials_configured": bool(settings.credentials_file),
                "authentication_mode": "service_account" if settings.credentials_file else "adc",
                "credential_name": settings.credentials_file.name if settings.credentials_file else None,
                "model_catalog": studio.model_catalog.snapshot(),
                "unsupported_generation_parameters": sorted(unsupported_generation_parameters(settings.model, studio.model_capabilities()))}

    @app.post("/models/refresh")
    def refresh_models():
        studio.model_catalog.refresh()
        return public_config()

    @app.post("/models/selection")
    def update_model(value: ModelSelection):
        select_model(studio, value.model)
        return public_config()

    @app.get("/preferences")
    def preferences():
        return load_preferences(studio.settings.root)

    @app.put("/preferences")
    def update_preferences(value: Preferences):
        return save_preferences(studio.settings.root, value)

    @app.get("/notifications/status")
    def notification_status():
        return notifications.status()

    class SoundImport(InputModel):
        name: str
        content_base64: str

    class ReminderTest(InputModel):
        sound_only: bool = False

    @app.post("/notifications/sound")
    async def import_notification_sound(request: Request):
        payload = bytearray()
        async for chunk in request.stream():
            payload.extend(chunk)
            if len(payload) > 7 * 1024 * 1024:
                raise HTTPException(413, "音频文件过大")
        try:
            value = SoundImport.model_validate(json.loads(payload))
        except Exception:
            raise ValueError("音频导入参数无效") from None
        return await asyncio.to_thread(notifications.sounds.import_sound, value.name, value.content_base64)

    @app.post("/notifications/test")
    async def test_notification(value: ReminderTest):
        prefs = load_preferences(studio.settings.root).notifications
        return await asyncio.to_thread(notifications.send, "Vertex Studio · 测试提醒",
                                       "批次完成时，会在这里提醒你。", prefs, sound_only=value.sound_only)

    @app.put("/cloud/configuration")
    async def cloud_configuration(request: Request):
        if any(row["phase"] not in {"completed", "cancelled", "failed", "budget_paused"} for row in harness.list()):
            raise ValueError("Harness 云端请求仍在进行，请完成或确认取消后再修改云端配置")
        payload = bytearray()
        async for chunk in request.stream():
            payload.extend(chunk)
            if len(payload) > 2 * 1024 * 1024:
                raise HTTPException(413, "密钥 JSON 文件过大")
        try:
            value = CloudConfiguration.model_validate(json.loads(payload))
        except Exception:
            # Don't return Pydantic's input field: it could contain a private key.
            raise ValueError("连接参数有误，请检查项目 ID、桶名和 JSON 文件") from None
        await asyncio.to_thread(configure_cloud, studio, value)
        if background:
            studio.model_catalog.refresh()
        return public_config()

    @app.post("/cloud/check")
    async def check_cloud():
        try:
            # Share a single probe. Shield prevents HTTP timeout/cancellation
            # from making the next caller spawn another still-running thread.
            scope = (studio.settings.project, studio.settings.bucket, studio.settings.credentials_file)
            probe = getattr(app.state, "cloud_probe", None)
            if probe is None or probe[0] != scope or probe[1].done():
                task = asyncio.create_task(asyncio.to_thread(lambda: studio.cloud.check_connection(studio.settings.bucket)))
                task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
                app.state.cloud_probe = probe = (scope, task)
            details = await asyncio.wait_for(asyncio.shield(probe[1]), timeout=30)
        except asyncio.TimeoutError:
            raise ValueError("连接检查超时，请检查网络后重试") from None
        except Exception:
            raise ValueError("连接检查失败，请检查项目、桶、凭证及其访问权限") from None
        return {"ok": True, "details": details}

    @app.post("/references/upload", status_code=201)
    async def upload_reference(request: Request, name: str, category: str | None = None,
                               batch_id: str | None = None):
        staging = studio.settings.root / ".runtime/imports"
        staging.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=staging) as temp:
            target = Path(temp) / filename(Path(name).name)
            size = 0
            with target.open("wb") as output:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > 30 * 1024 * 1024:
                        raise HTTPException(413, "参考图超过 30 MB")
                    output.write(chunk)
            return await asyncio.to_thread(studio.assets.import_file, str(target), category, batch_id)

    @app.post("/references/import", status_code=201)
    def import_reference(value: ReferenceImport):
        return studio.assets.import_file(value.source, value.category, value.batch_id)

    @app.get("/references/file")
    def reference_file(path: str, batch_id: str | None = None):
        # Only verified managed images, never an arbitrary file from the disk.
        if batch_id:
            directory = studio.repo.directory(batch_id)
            manifest = directory / "inputs/manifest.json"
            if manifest.is_file() and any(path in task.refs for task in studio.repo.tasks(batch_id)):
                for asset in read_json(manifest).get("assets", []):
                    if asset["source_path"] == path and asset["local_path"].startswith("inputs/assets/"):
                        snapshot = beneath(directory / "inputs/assets", asset["local_path"][14:])
                        if sha256_file(snapshot) != asset["sha256"]:
                            raise ValueError("参考图快照损坏")
                        return FileResponse(snapshot, media_type=inspect_image(snapshot)["mime_type"])
        for item in studio.assets.list(batch_id):
            if item["path"] == path:
                return FileResponse(studio.settings.data_dir / path, media_type=item["mime_type"])
        raise KeyError("找不到参考图")

    @app.get("/batches")
    def batches():
        return studio.repo.list()

    @app.post("/batches", status_code=201)
    def create_batch(value: BatchCreate):
        return studio.repo.create(value.project_name, value.image_output_dir, value.source_batch_id)

    @app.get("/batches/{batch_id}")
    def batch(batch_id: str):
        return studio.repo.get(batch_id)

    @app.get("/batches/{batch_id}/tasks")
    def tasks(batch_id: str):
        return [t.model_dump() for t in studio.repo.tasks(batch_id)]

    @app.put("/batches/{batch_id}/tasks")
    def replace_tasks(batch_id: str, value: TasksReplace):
        return [t.model_dump() for t in studio.repo.replace_tasks(batch_id, value.tasks)]

    @app.post("/batches/{batch_id}/tasks", status_code=201)
    def append_task(batch_id: str, value: TaskInput):
        return studio.append_task(batch_id, value)

    @app.delete("/batches/{batch_id}/tasks/{task_id}", status_code=204)
    def delete_task(batch_id: str, task_id: str):
        studio.delete_task(batch_id, task_id)

    @app.put("/batches/{batch_id}/tasks/{task_id}")
    def update_task(batch_id: str, task_id: str, value: TaskInput):
        return studio.update_task(batch_id, task_id, value)

    @app.post("/batches/{batch_id}/import-jsonl")
    def import_tasks(batch_id: str, value: JsonlImport):
        return [t.model_dump() for t in import_jsonl(studio.repo, batch_id, value.source)]

    @app.put("/batches/{batch_id}/output-directory")
    def output_directory(batch_id: str, value: OutputDirectory):
        return studio.repo.set_output(batch_id, value.path)

    @app.post("/batches/{batch_id}/prepare")
    def prepare(batch_id: str):
        manifest = studio.prepare(batch_id)
        return {"batch": studio.repo.get(batch_id), "task_count": len(manifest["requests"])}

    @app.post("/batches/{batch_id}/submit", status_code=202)
    def submit(batch_id: str):
        studio.repo.get(batch_id)
        return {"queued": studio.enqueue(batch_id, "submit"), "batch_id": batch_id}

    @app.post("/batches/{batch_id}/poll", status_code=202)
    def poll(batch_id: str):
        studio.repo.get(batch_id)
        return {"queued": studio.enqueue(batch_id, "poll"), "batch_id": batch_id}

    @app.post("/batches/{batch_id}/extract", status_code=202)
    def extract(batch_id: str):
        studio.repo.get(batch_id)
        return {"queued": studio.enqueue(batch_id, "extract_local"), "batch_id": batch_id}

    @app.post("/batches/{batch_id}/cancel")
    def cancel(batch_id: str):
        return studio.cancel(batch_id)

    @app.post("/batches/{batch_id}/attach")
    def attach(batch_id: str, value: AttachJob):
        return studio.attach(batch_id, value.job_name)

    @app.post("/batches/{batch_id}/retry", status_code=201)
    def retry(batch_id: str):
        return studio.retry(batch_id, failed_only=True)

    @app.post("/batches/{batch_id}/clone", status_code=201)
    def clone(batch_id: str):
        return studio.retry(batch_id, failed_only=False)

    @app.post("/batches/{batch_id}/archive")
    def archive(batch_id: str):
        return studio.repo.archive(batch_id)

    @app.put("/workspaces/{workspace_id}")
    def rename_workspace(workspace_id: str, value: WorkspaceRename):
        return studio.repo.rename_workspace(workspace_id, value.project_name)

    @app.post("/workspaces/{workspace_id}/archive")
    def archive_workspace(workspace_id: str):
        return studio.repo.archive_workspace(workspace_id)

    @app.delete("/workspaces/{workspace_id}")
    def delete_workspace(workspace_id: str):
        return studio.repo.delete_workspace(workspace_id)

    @app.get("/batches/{batch_id}/results")
    def results(batch_id: str):
        return studio.results(batch_id)

    @app.get("/batches/{batch_id}/images/{task_id}/{image_index}")
    def image(batch_id: str, task_id: str, image_index: int):
        for task in studio.results(batch_id)["tasks"]:
            if task["task_id"] == task_id and 0 <= image_index < len(task["images"]):
                value = task["images"][image_index]
                return FileResponse(value["path"], media_type=value["mime_type"])
        raise KeyError("找不到输出图片")

    @app.get("/batches/{batch_id}/events")
    async def events(batch_id: str, request: Request):
        await asyncio.to_thread(studio.repo.get, batch_id)
        async def snapshots():
            previous = None
            heartbeat = time.monotonic()
            while not app.state.shutting_down and not await request.is_disconnected():
                value = await asyncio.to_thread(studio.repo.get, batch_id)
                report = await asyncio.to_thread(studio.results, batch_id)
                snapshot = {"batch": value, "results": report}
                encoded = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
                if encoded != previous:
                    yield f"id: {value['updated_at']}\nevent: snapshot\ndata: {encoded}\n\n"
                    previous = encoded
                    heartbeat = time.monotonic()
                    if value["phase"] in {"completed", "completed_with_errors", "failed", "cancelled", "submission_unconfirmed"}:
                        break
                elif time.monotonic() - heartbeat >= 15:
                    yield ": keepalive\n\n"
                    heartbeat = time.monotonic()
                await asyncio.sleep(0.5)
        # Always sends a full snapshot on reconnect, even with Last-Event-ID.
        return StreamingResponse(snapshots(), media_type="text/event-stream",
                                 headers={"X-Accel-Buffering": "no"})

    @app.post("/shutdown")
    async def shutdown():
        app.state.shutting_down = True
        studio.request_stop()
        harness.request_stop()
        harness_runtime.request_stop()
        log_lifecycle_event(
            studio.settings.root,
            "shutdown_requested",
            instance_id=instance_id,
            mode=mode,
            harness_running=bool(harness_runtime.child and harness_runtime.child.poll() is None),
            harness_pid=harness_runtime.child.pid if harness_runtime.child else None,
        )
        if on_shutdown:
            on_shutdown()
        return {"status": "stopping"}

    mount_harness(app, harness, harness_runtime, harness_token)
    return app
