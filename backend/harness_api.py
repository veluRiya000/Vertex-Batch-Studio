"""Owner controls and separately authenticated model-provider routes."""
import asyncio
import json
from fastapi import Request
from fastapi.responses import StreamingResponse
from .harness_models import HarnessRun, HarnessRequest, HarnessStart, HarnessResume


def mount_harness(app, batch, runtime, scoped_token):
    @app.get("/harness/status")
    def status():
        return runtime.status()

    @app.post("/harness/start")
    async def start(value: HarnessStart, request: Request):
        # The local middleware already authenticates the owner; origin is still fixed, not supplied in JSON.
        url = await asyncio.to_thread(runtime.start, str(request.base_url).rstrip("/"), scoped_token, value.offline)
        return {"url": url, **runtime.status()}

    @app.post("/harness/stop")
    async def stop():
        await asyncio.to_thread(runtime.close)
        return runtime.status()

    @app.post("/harness/ui/cloud-settings")
    def cloud_settings():
        return runtime.request_cloud_settings()

    @app.post("/harness/ui/notification-settings")
    def notification_settings():
        return runtime.request_cloud_settings("notifications")

    @app.get("/harness/requests")
    def requests(run_id: str | None = None):
        return [batch.public(value) for value in batch.list(run_id)]

    @app.post("/harness/runs", status_code=201)
    def create_run(value: HarnessRun):
        return batch.create_run(value)

    @app.post("/harness/runs/{run_id}/pause")
    def pause(run_id: str):
        return batch.set_run_phase(run_id, "paused")

    @app.post("/harness/runs/{run_id}/finish")
    def finish(run_id: str):
        return batch.finish_run(run_id)

    @app.post("/harness/runs/{run_id}/resume")
    def resume_run(run_id: str, value: HarnessResume):
        return batch.set_run_phase(run_id, "active", **value.model_dump())

    @app.post("/harness/requests", status_code=202)
    def create_request(value: HarnessRequest):
        return batch.create(value)

    @app.get("/harness/requests/{request_id}")
    def receipt(request_id: str):
        return batch.public(batch.get(request_id))

    @app.post("/harness/requests/{request_id}/cancel")
    def cancel(request_id: str):
        return batch.cancel(request_id)

    @app.post("/harness/requests/{request_id}/resume")
    def resume(request_id: str):
        return batch.resume(request_id)

    @app.get("/harness/requests/{request_id}/events")
    async def events(request_id: str, request: Request):
        batch.get(request_id)
        async def stream():
            previous = None
            while not await request.is_disconnected():
                snapshot = await asyncio.to_thread(lambda: batch.public(batch.get(request_id)))
                encoded = json.dumps(snapshot, ensure_ascii=False)
                if encoded != previous:
                    yield f"event: snapshot\ndata: {encoded}\n\n"
                    previous = encoded
                else:
                    yield ": heartbeat\n\n"
                if snapshot["phase"] in {"completed", "failed", "cancelled", "budget_paused"}:
                    return
                await asyncio.sleep(1)
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})
