"""Durable one-row Gemini Batch requests. No synchronous generation fallback."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager
import hashlib
import json
import sqlite3
import threading
import time
from .cloud import TERMINAL, GoogleCloud
from dataclasses import replace
from .files import write_json
from .jsonl import split_gcs
from .harness_models import HarnessRun, HarnessRequest
from .harness_profiles import PROFILES, profile, price_snapshot, estimate_cost, usage_cost
from .harness_results import request_matches, response_from_row
from .harness_continuation import next_request, merge_responses, sum_usage, generated_tokens

FINAL = {"completed", "failed", "cancelled", "budget_paused"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class HarnessBatch:
    """Own request identities, budget reservations, cloud receipts and recovery."""
    def __init__(self, studio):
        self.studio = studio
        self._agent_cloud = None
        self._agent_context = None
        self.root = studio.settings.data_dir / "harness"
        self.root.mkdir(parents=True, exist_ok=True)
        # Agent model/region are separate from the image model selection.
        self.agent_location = "global"
        write_json(self.root / "model.json", {"model": "gemini-4-argon", "models": list(PROFILES), "location": self.agent_location})
        self.db = self.root / "queue.sqlite3"
        self._lock = threading.RLock()
        self._local = threading.local()
        self._stop = threading.Event()
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="harness-batch")
        self._inflight = set()
        self._thread = None
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY, run_id TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT, data TEXT NOT NULL);
            """)
            # A crash during a network submission must be reconciled, never resubmitted.
            for row in db.execute("SELECT id,data FROM requests").fetchall():
                value = json.loads(row["data"])
                if value["phase"] == "submitting":
                    value["phase"] = "submission_unknown"
                    db.execute("UPDATE requests SET data=? WHERE id=?", (canonical(value), row["id"]))
                if value["phase"] not in FINAL:
                    # Monitor accepted jobs after restart, but never start a new
                    # paid continuation without the user's explicit resume.
                    value["continuation_suspended"] = True
                    db.execute("UPDATE requests SET data=? WHERE id=?", (canonical(value), row["id"]))
            # No local Agent loop survives a backend restart. Retain every
            # pending cloud request, but release orphaned local-only turns.
            self._reconcile_runs(restarting=True)
            # Re-read already downloaded final answers affected by an older
            # echo matcher. This path never submits jobs or dispatches tools.
            for row in db.execute("SELECT id FROM requests").fetchall():
                self.recover_local_answer(row["id"])

    @contextmanager
    def connection(self):
        with self._lock:
            current = getattr(self._local, "db", None)
            if current is not None:
                yield current
                return
            db = sqlite3.connect(self.db, timeout=10)
            db.row_factory = sqlite3.Row
            self._local.db = db
            try:
                with db:
                    yield db
            finally:
                self._local.db = None
                db.close()

    def run(self, run_id):
        with self.connection() as db:
            row = db.execute("SELECT data FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise KeyError("找不到 Harness 任务")
            return json.loads(row[0])

    def _reconcile_runs(self, *, restarting=False):
        """Release failed/orphaned turns only when no cloud request is pending."""
        with self.connection() as db:
            for row in db.execute("SELECT data FROM runs").fetchall():
                run = json.loads(row[0])
                if run["phase"] != "active":
                    continue
                requests = self.list(run["run_id"])
                if any(r["phase"] not in FINAL for r in requests):
                    continue
                failed = any((r["phase"] in {"failed", "cancelled", "budget_paused"} or r.get("truncated")) for r in requests)
                if restarting or failed:
                    self.set_run_phase(run["run_id"], "paused")

    def create_run(self, value: HarnessRun):
        try:
            workspace = Path(value.workspace).expanduser().resolve(strict=True)
        except OSError:
            raise ValueError("选定工作区不存在或不可访问") from None
        if not workspace.is_dir():
            raise ValueError("工作区必须是目录")
        data = value.model_dump() | {"workspace": str(workspace), "phase": "active"}
        with self.connection() as db:
            self._reconcile_runs()
            row = db.execute("SELECT data FROM runs WHERE id=?", (value.run_id,)).fetchone()
            if row:
                old = json.loads(row[0])
                if (old["session_id"], old["workspace"]) != (value.session_id, str(workspace)):
                    raise ValueError("任务身份或工作区不能更改")
                # The user's run-limit switch applies to the next request,
                # without resetting accumulated usage or changing frozen input.
                if old.get("limits_enabled", True) != value.limits_enabled:
                    return self.set_run_phase(value.run_id, old["phase"], limits_enabled=value.limits_enabled)
                return old
            active = [json.loads(r[0]) for r in db.execute("SELECT data FROM runs")]
            # Pausing local execution does not terminate a pending cloud job.
            pending_runs = {r["run_id"] for r in self.list() if r["phase"] not in FINAL}
            active = [r for r in active if r["phase"] == "active" or r["run_id"] in pending_runs]
            if any(r["workspace"] == str(workspace) for r in active):
                raise ValueError("当前工作区已有活动任务，请完成或暂停后再开始")
            if len(active) >= 2:
                raise ValueError("最多同时运行两个工作区")
            db.execute("INSERT INTO runs VALUES (?,?)", (value.run_id, canonical(data)))
        return data

    def set_run_phase(self, run_id, phase, **limits):
        with self.connection() as db:
            run = self.run(run_id)
            run.update(phase=phase, **{k: v for k, v in limits.items() if v is not None})
            db.execute("UPDATE runs SET data=? WHERE id=?", (canonical(run), run_id))
        return run

    def finish_run(self, run_id):
        with self.connection():
            run=self.run(run_id)
            if run["phase"] != "active":
                return run
            requests=self.list(run_id)
            if any(r["phase"] not in FINAL for r in requests):
                return run
            return self.set_run_phase(run_id,"completed" if requests and all(r["phase"] == "completed" for r in requests) else "paused")

    def get(self, request_id):
        with self.connection() as db:
            row = db.execute("SELECT data FROM requests WHERE id=?", (request_id,)).fetchone()
            if not row:
                raise KeyError("找不到 Batch 请求")
            return json.loads(row[0])

    def list(self, run_id=None):
        with self.connection() as db:
            sql = "SELECT data FROM requests" + (" WHERE run_id=?" if run_id else "")
            return [json.loads(r[0]) for r in db.execute(sql, (run_id,) if run_id else ())]

    def save(self, value):
        value["updated_at"] = datetime.now(timezone.utc).isoformat()
        with self.connection() as db:
            db.execute("UPDATE requests SET data=? WHERE id=?", (canonical(value), value["request_id"]))
            public = self.public(value)
            db.execute("INSERT INTO events(request_id,data) VALUES (?,?)", (value["request_id"], canonical(public)))
            if value["phase"] in {"failed", "cancelled", "budget_paused"} or value.get("truncated"):
                self._reconcile_runs()

    def public(self, value):
        run = self.run(value["run_id"])
        value = dict(value)
        if value.get("continuation"):
            value["continuation"] = dict(value["continuation"], submitted_jobs=self.submitted_jobs(value))
        return {k: v for k, v in value.items() if k not in {"request", "active_request", "segments", "continuation_suspended", "cloud_context", "downloads"}} | {"budget_usd": run["budget_usd"], "max_rounds": run["max_rounds"], "limits_enabled": run.get("limits_enabled", True)}

    def create(self, value: HarnessRequest):
        self.studio.settings.require_cloud()
        body = value.model_dump()
        digest = fingerprint(body)
        with self.connection() as db:
            row = db.execute("SELECT data FROM requests WHERE id=?", (value.request_id,)).fetchone()
            if row:
                old = json.loads(row[0])
                if old["fingerprint"] != digest:
                    raise ValueError("相同请求编号不能绑定不同输入")
                return self.public(old)
            run = self.run(value.run_id)
            if run["phase"] != "active" or run["session_id"] != value.session_id:
                raise ValueError("任务已暂停或会话身份不一致")
            if any(r["phase"] not in FINAL for r in self.list(value.run_id)):
                raise ValueError("当前任务的上一轮尚未完成")
            settings = self.studio.settings
            body.update(phase="preparing", fingerprint=digest, job_name=None, error=None,
                        reserved_usd=0, actual_usd=0, response=None, downloads={},
                        created_at=datetime.now(timezone.utc).isoformat(),
                        cloud_context=[settings.project, self.agent_location, settings.bucket])
            db.execute("INSERT INTO requests VALUES (?,?,?)", (value.request_id, value.run_id, canonical(body)))
            self.save(body)
        return self.public(body)

    def _context(self, value):
        settings = self.studio.settings
        if value["cloud_context"] != [settings.project, self.agent_location, settings.bucket]:
            raise ValueError("云端配置与提交快照不同，请恢复原配置再继续")

    @property
    def cloud(self):
        primary=self.studio.cloud
        if not isinstance(primary,GoogleCloud):
            return primary  # Injected offline provider.
        settings=replace(self.studio.settings,location=self.agent_location,model="gemini-4-argon")
        key=(settings.project, settings.bucket, settings.credentials_file)
        with self._lock:
            if self._agent_context != key:
                if self._agent_cloud is not None:
                    self._agent_cloud.close()
                self._agent_cloud=GoogleCloud(settings, api_version="v1beta1")
                self._agent_context=key
            return self._agent_cloud

    @staticmethod
    def wire_request(value):
        return value.get("active_request", value["request"])

    @staticmethod
    def submitted_jobs(value):
        return sum(bool(s.get("submission_intent")) for s in value.get("segments", [])) + bool(value.get("submission_intent"))

    def aggregate_cost(self, value):
        segments = value.get("segments", [])
        value["actual_usd"] = sum(s.get("actual_usd", 0) for s in segments) + value.get("segment_actual_usd", 0)
        value["reserved_usd"] = sum(s.get("reserved_usd", 0) for s in segments) + value.get("segment_reserved_usd", 0)
        usage = [s.get("usage") for s in segments] + [value.get("segment_usage")]
        if any(isinstance(u, dict) for u in usage):
            value["usage"] = sum_usage(usage)
        costs = [s.get("cost_estimate") for s in segments] + [value.get("segment_cost_estimate")]
        if any(costs):
            value["cost_estimate"] = {"estimated_usd": value["actual_usd"],
                "promotional_estimated_usd": sum(c.get("promotional_estimated_usd", 0) for c in costs if c),
                "basis": "sum of per-segment returned usage; before account credits"}

    def settle_usage(self, value, row):
        # Idempotent: replace this segment's counters, then sum archived segments.
        raw = row.get("response")
        usage = raw.get("usageMetadata") if isinstance(raw, dict) else None
        cost = usage_cost(usage, value.get("price_snapshot") or price_snapshot(value["model"]), value["model"], value["created_at"])
        if cost is not None:
            value.update(segment_usage=usage, segment_cost_estimate=cost,
                         segment_actual_usd=cost["estimated_usd"], segment_reserved_usd=0)
        else:
            status = row.get("status")
            if isinstance(status, str) and status:
                try: status = json.loads(status)
                except ValueError: status = None
            if isinstance(status, dict) and status.get("canonicalCode", status.get("code")) in {3,5,7,16} and not (isinstance(raw, dict) and raw.get("candidates")):
                value.update(segment_actual_usd=0, segment_reserved_usd=0, cost_basis="cloud_rejected_without_generation")
            elif "segment_reserved_usd" not in value:
                value["segment_reserved_usd"] = value["reserved_usd"]
        self.aggregate_cost(value)
        self.save(value)

    def accept_response(self, value, response):
        """Checkpoint a whole cloud segment; expose no partial tool or prose."""
        segments = value.setdefault("segments", [])
        current = len(segments)
        previous = [json.loads((self.root / s["response_file"]).read_text(encoding="utf-8")) for s in segments]
        reason = response["candidates"][0].get("finishReason")
        path = Path("requests") / value["request_id"] / "segments" / f"{current:04d}" / "response.json"
        write_json(self.root / path, response)
        if value["phase"] == "cancel_requested":
            value.update(phase="cancelled", response=None, error=None)
            return
        if reason == "STOP":
            if response["candidates"][0].get("continuationToken"):
                raise ValueError("云端 STOP 仍带有续传令牌，结束状态不一致")
            value.update(response=merge_responses(previous + [response]) if previous else response,
                         phase="completed", truncated=False, error=None)
            if previous:
                value["continuation"] = {"state": "complete", "buffered_segments": current + 1,
                    "segment_index": current, "generated_tokens": generated_tokens(previous + [response]),
                    "submitted_jobs": self.submitted_jobs(value)}
            return
        run = self.run(value["run_id"])
        wire, blocked = next_request(value["request"], self.wire_request(value), previous + [response],
                                     value["model"], value.get("input_tokens", 0), run.get("limits_enabled", True))
        if wire is None:
            # No terminal tool is ever exposed if the cloud cannot continue.
            value.update(response=None, phase="failed", truncated=True, error=blocked)
            value["continuation"] = {"state": "blocked", "buffered_segments": current + 1,
                                     "generated_tokens": generated_tokens(previous + [response])}
            return
        segments.append({"response_file": path.as_posix(), "job_name": value["job_name"],
            "input_uri": value["input_uri"], "output_uri": value["output_uri"],
            "submission_intent": True, "actual_usd": value.get("segment_actual_usd", 0),
            "reserved_usd": value.get("segment_reserved_usd", 0),
            "usage": value.get("segment_usage"), "cost_estimate": value.get("segment_cost_estimate")})
        for key in ("cloud_state", "input_uri", "output_uri", "submission_rejected", "budget_check",
                    "segment_usage", "segment_cost_estimate"):
            value.pop(key, None)
        value.update(active_request=wire, phase="preparing", job_name=None, submission_intent=False,
                     segment_actual_usd=0, segment_reserved_usd=0, response=None, error=None, truncated=False)
        value["continuation"] = {"state": "buffering", "buffered_segments": current + 1,
            "segment_index": current + 1, "generated_tokens": generated_tokens(previous + [response]),
            "submitted_jobs": self.submitted_jobs(value)}
        self.aggregate_cost(value)

    def advance(self, request_id):
        value = self.get(request_id)
        if value["phase"] in FINAL:
            return self.public(value)
        try:
            self._context(value)
            cloud = self.cloud
            if value["phase"] == "preparing":
                tokens = cloud.count_request_tokens(value["request"], model=value["model"])
                cap = self.wire_request(value).get("generationConfig", {}).get("maxOutputTokens")
                spec = profile(value["model"])
                if type(tokens) is not int or tokens < 0 or tokens > spec["input_limit"] or (cap is not None and spec["shared_context"] and tokens + cap > spec["input_limit"]):
                    raise ValueError(f"请求超过 {spec['label']} 的 {spec['input_limit']} Token 上下文，请减少材料或调整输出额度")
                rates = price_snapshot(value["model"])
                # No explicit cap: estimate the cloud default for display only.
                decoded = value.get("continuation", {}).get("generated_tokens", 0)
                # Native continuation re-prefills earlier decoded tokens. The
                # output cap is cumulative, so reserve only remaining output.
                reservation = estimate_cost(tokens + decoded, max(0, cap - decoded) if cap is not None else 65536, rates)
                with self.connection():
                    value = self.get(request_id)
                    if value["phase"] != "preparing":
                        return self.public(value)
                    run = self.run(value["run_id"])
                    previous = [r for r in self.list(value["run_id"]) if r["request_id"] != request_id]
                    total = sum(r["reserved_usd"] + r["actual_usd"] for r in previous) + value["actual_usd"] + value["reserved_usd"]
                    attempts = sum(self.submitted_jobs(r) for r in previous) + self.submitted_jobs(value)
                    if value.get("continuation_suspended") or run["phase"] != "active" or (run.get("limits_enabled", True) and (attempts >= run["max_rounds"] or total + reservation > run["budget_usd"])):
                        reason = "程序重启后续传已暂停，请点击恢复" if value.get("continuation_suspended") else "任务已暂停" if run["phase"] != "active" else f"已达到 {run['max_rounds']} 次模型请求上限" if attempts >= run["max_rounds"] else f"已估算 ${total:.3f}，下一次按输出上限预留 ${reservation:.3f}，合计超过 ${run['budget_usd']:.2f} 预算；预留不是已扣费"
                        value.update(phase="budget_paused", error=reason, budget_check={"estimated_and_unresolved_usd":total,"next_reservation_usd":reservation,"budget_usd":run["budget_usd"],"submitted_requests":attempts})
                        self.set_run_phase(value["run_id"], "paused")
                    else:
                        value.update(phase="uploading", segment_reserved_usd=reservation, input_tokens=tokens, price_snapshot=rates)
                        self.aggregate_cost(value)
                    self.save(value)
                if value["phase"] == "budget_paused":
                    return self.public(value)
            if value["phase"] == "uploading":
                segment = len(value.get("segments", []))
                suffix = f"/segments/{segment:04d}" if segment else ""
                directory = self.root / "requests" / (request_id + suffix)
                directory.mkdir(parents=True, exist_ok=True)
                source = directory / "input.jsonl"
                source.write_text(canonical({"request": self.wire_request(value)}) + "\n", encoding="utf-8")
                bucket = value["cloud_context"][2]
                key = f"harness/requests/{request_id}{suffix}/input.jsonl"
                cloud.upload(bucket, key, source, "application/jsonl")
                with self.connection():
                    value = self.get(request_id)
                    if value["phase"] != "uploading":
                        return self.public(value)
                    value.update(phase="submitting", submission_intent=True,
                                 input_uri=f"gs://{bucket}/{key}", output_uri=f"gs://{bucket}/harness/requests/{request_id}{suffix}/outputs/")
                    self.save(value)
                try:
                    job = cloud.create_job(value["model"], value["input_uri"], value["output_uri"], "vbs-harness-" + request_id + (f"-s{segment:04d}" if segment else ""))
                except Exception as error:
                    with self.connection():
                        value = self.get(request_id)
                        code=getattr(error,"code",getattr(error,"status_code",None))
                        if code in {400,401,403,404,422}:
                            value.update(phase="failed",segment_reserved_usd=0,submission_rejected=True,
                                         error=f"云端拒绝提交（{code}），请检查模型访问权限、项目和凭证")
                        elif value["phase"] != "cancel_requested":
                            value.update(phase="submission_unknown", error="提交结果未确认，正在核对原作业，不会重复提交")
                        self.aggregate_cost(value)
                        self.save(value)
                    return self.public(value)
                with self.connection():
                    value = self.get(request_id)
                    value["job_name"] = job.name
                    if value["phase"] != "cancel_requested":
                        value.update(phase="queued", error=None)
                    self.save(value)
            if value["phase"] in {"submitting", "submission_unknown", "cancel_requested"} and not value["job_name"]:
                found = cloud.find_jobs("vbs-harness-" + request_id + (f"-s{len(value.get('segments', [])):04d}" if value.get("segments") else ""), value.get("input_uri", ""))
                if len(found) != 1:
                    value.update(error="正在核对云端提交记录" if not found else "找到多个作业，需要人工核对")
                    self.save(value)
                    return self.public(value)
                value["job_name"] = found[0].name
                if value["phase"] != "cancel_requested":
                    value["phase"] = "queued"
                self.save(value)
            if value["phase"] == "cancel_requested":
                cloud.cancel_job(value["job_name"])
            job = cloud.get_job(value["job_name"])
            value = self.get(request_id)
            value["cloud_state"] = job.state
            if job.output_uri:
                value["output_uri"] = job.output_uri
            segment = len(value.get("segments", []))
            directory = self.root / "requests" / request_id
            if segment:
                directory = directory / "segments" / f"{segment:04d}"
            directory = directory / "raw"
            directory.mkdir(parents=True, exist_ok=True)
            bucket, _ = split_gcs(value["output_uri"])
            matched = []
            for obj in cloud.list_outputs(value["output_uri"]):
                key = obj.name + "#" + obj.generation
                target = directory / (hashlib.sha256(key.encode()).hexdigest() + ".jsonl")
                if not target.exists():
                    cloud.download(bucket, obj, target)
                for line in target.read_text(encoding="utf-8-sig").splitlines():
                    row = json.loads(line)
                    if not request_matches(self.wire_request(value), row.get("request")):
                        raise ValueError("Batch 输出无法关联到冻结的请求")
                    matched.append(row)
            if len(matched) > 1:
                raise ValueError("单行请求收到多条输出，需要人工核对")
            if matched:
                row = matched[0]
                # Commit paid usage before any validation that may fail.
                with self.connection():
                    if self.get(request_id)["phase"] == "cancel_requested":
                        value["phase"] = "cancel_requested"
                    self.settle_usage(value, row)
                response = response_from_row(row, self.wire_request(value), allow_continuation=True)
                with self.connection():
                    # Cancellation may arrive while a cloud download is running.
                    cancelled = self.get(request_id)["phase"] == "cancel_requested"
                    if cancelled:
                        value["phase"] = "cancel_requested"
                    if response["candidates"][0].get("finishReason") == "MAX_TOKENS" and not response["candidates"][0].get("continuationToken") and not value.get("segments"):
                        value.update(response=response, truncated=True,
                                     phase="cancelled" if cancelled else "completed", error=None)
                    else:
                        self.accept_response(value, response)
                    self.save(value)
                return self.public(value)
            elif job.state in TERMINAL:
                value.update(phase="cancelled" if job.state == "JOB_STATE_CANCELLED" else "failed", error="云端作业已结束，没有可用结果")
            elif value["phase"] != "cancel_requested":
                value["phase"] = "running" if job.state == "JOB_STATE_RUNNING" else "queued"
            self.save(value)
        except Exception as error:
            value = self.get(request_id)
            transient = not isinstance(error, ValueError) and value["phase"] in {"queued", "running", "cancel_requested", "submission_unknown", "uploading"}
            value["error"] = "连接暂时中断，将继续核对" if transient else str(error) if isinstance(error, ValueError) else "请求准备失败，请检查配置与权限"
            if not transient:
                value["phase"] = "failed"
                if not value.get("submission_intent"):
                    value["segment_reserved_usd"] = 0
                    self.aggregate_cost(value)
            self.save(value)
        return self.public(value)

    def recover_local_answer(self, request_id):
        """Recover a text-only final answer from local raw output, never rerun tools.

        Preserve the original failure in recovery metadata. The DSH transcript
        remains an honest historical log; its activity panel presents this answer.
        """
        with self.connection():
            value = self.get(request_id)
            if value["phase"] != "failed" or value.get("error") != "Batch 输出无法关联到冻结的请求":
                return False
            if not value.get("job_name"):
                return False
            directory = self.root / "requests" / request_id
            try:
                frozen = json.loads((directory / "input.jsonl").read_text(encoding="utf-8-sig"))
                if frozen != {"request": value["request"]}:
                    return False
                rows = [json.loads(line) for file in (directory / "raw").glob("*.jsonl")
                        for line in file.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
                if len(rows) != 1:
                    return False
                row = rows[0]
                response = response_from_row(row, value["request"])
                if len(response["candidates"]) != 1 or response["candidates"][0].get("finishReason") != "STOP":
                    return False
                parts = response["candidates"][0].get("content", {}).get("parts", [])
                # No tool calls, executable code or ambiguous partial responses.
                if not parts or any(not isinstance(p, dict) or set(p) - {"text", "thought", "thoughtSignature"} for p in parts):
                    return False
                text = "\n\n".join(p["text"] for p in parts if not p.get("thought") and isinstance(p.get("text"), str))
                if not text.strip():
                    return False
            except (OSError, ValueError, KeyError, TypeError):
                return False
            recovered_at = datetime.now(timezone.utc).isoformat()
            self.settle_usage(value, row)
            value.update(phase="completed", error=None, response=response, truncated=False,
                         local_recovery={"previous_error": value["error"], "at": recovered_at, "text": text})
            self.save(value)
            # Keep the failed Agent turn paused; never restart its execution.
            return True

    def cancel(self, request_id):
        with self.connection():
            value = self.get(request_id)
            if value["phase"] not in FINAL:
                value["phase"] = "cancel_requested" if value.get("submission_intent") else "cancelled"
                if not value.get("submission_intent"):
                    value["segment_reserved_usd"] = 0
                    self.aggregate_cost(value)
                self.save(value)
            self.set_run_phase(value["run_id"], "paused")
        return self.public(value)

    def resume(self, request_id):
        with self.connection():
            value = self.get(request_id)
            if value["phase"] == "budget_paused":
                value.update(phase="preparing", error=None, continuation_suspended=False)
                self.save(value)
            elif value["phase"] in {"cancelled", "failed"}:
                raise ValueError("此请求已结束，请开始新任务")
        return self.public(value)

    def start(self):
        if self._thread:
            return
        def loop():
            while not self._stop.is_set():
                with self._lock:
                    for value in self.list():
                        key = value["request_id"]
                        if value["phase"] not in FINAL and key not in self._inflight:
                            self._inflight.add(key)
                            future = self._pool.submit(self.advance, key)
                            def done(_future, key=key):
                                with self._lock:
                                    self._inflight.discard(key)
                            future.add_done_callback(done)
                self._stop.wait(self.studio.settings.poll_seconds)
        self._thread = threading.Thread(target=loop, daemon=True, name="harness-monitor")
        self._thread.start()

    def close(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._pool.shutdown(wait=True, cancel_futures=True)
        if self._agent_cloud is not None:
            self._agent_cloud.close()
            self._agent_cloud=None
