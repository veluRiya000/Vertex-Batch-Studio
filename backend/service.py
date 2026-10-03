"""Workflow coordinator. Cloud calls are injectable for meaningful offline tests."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib
import json
import threading
from .assets import Assets
from .cloud import Cloud, GoogleCloud, TERMINAL
from .config import Settings
from .files import BusyError, beneath, read_json, sha256_file, write_json
from .jsonl import prepare, split_gcs
from .models import TaskInput
from .repository import Repository, now
from .results import extract


class Studio:
    def __init__(self, settings: Settings, cloud: Cloud | None = None):
        self.settings = settings
        self.repo = Repository(settings)
        self.assets = Assets(self.repo)
        self._cloud = cloud
        self._cloud_lock = threading.Lock()
        self._stop = threading.Event()
        self._worker = None
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="vbs")
        self._inflight = set()
        self._inflight_lock = threading.Lock()

    @property
    def cloud(self) -> Cloud:
        with self._cloud_lock:
            if self._cloud is None:
                self._cloud = GoogleCloud(self.settings)
            return self._cloud

    def log(self, batch_id: str, event: str, **details) -> None:
        path = self.repo.directory(batch_id) / "logs/events.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"time": now(), "event": event, **details}, ensure_ascii=False) + "\n")

    def prepare(self, batch_id: str) -> dict:
        with self.repo.lock(batch_id):
            manifest = prepare(self.repo, batch_id)
            manifest["tasks_sha256"] = sha256_file(self.repo.directory(batch_id) / "inputs/tasks.json")
            manifest["jsonl_sha256"] = sha256_file(self.repo.directory(batch_id) / "inputs/prompts.jsonl")
            write_json(self.repo.directory(batch_id) / "inputs/manifest.json", manifest)
            self.log(batch_id, "prepared", tasks=len(manifest["requests"]))
            return manifest

    def manifest(self, batch_id: str) -> dict:
        return read_json(self.repo.directory(batch_id) / "inputs/manifest.json")

    def update_task(self, batch_id: str, task_id: str, value: TaskInput) -> dict:
        with self.repo.lock(batch_id):
            batch = self.repo.editable(batch_id)
            tasks = self.repo.tasks(batch_id)
            from .models import Task
            changed = False
            for index, task in enumerate(tasks):
                if task.id == task_id:
                    tasks[index] = Task(id=task_id, created_at=task.created_at, **value.model_dump())
                    changed = True
            if not changed:
                raise KeyError("任务不存在")
            write_json(self.repo.directory(batch_id) / "inputs/tasks.json", [t.model_dump() for t in tasks])
            batch.update(phase="draft", last_error=None)
            self.repo.save(batch)
            return next(t.model_dump() for t in tasks if t.id == task_id)

    def append_task(self, batch_id: str, value: TaskInput) -> dict:
        from .models import Task
        import uuid
        with self.repo.lock(batch_id):
            batch = self.repo.editable(batch_id)
            tasks = self.repo.tasks(batch_id)
            task = Task(id=uuid.uuid4().hex, created_at=now(), **value.model_dump())
            tasks.append(task)
            write_json(self.repo.directory(batch_id) / "inputs/tasks.json", [t.model_dump() for t in tasks])
            batch.update(phase="draft", last_error=None)
            self.repo.save(batch)
            return task.model_dump()

    def delete_task(self, batch_id: str, task_id: str) -> None:
        with self.repo.lock(batch_id):
            batch = self.repo.editable(batch_id)
            tasks = self.repo.tasks(batch_id)
            remaining = [task for task in tasks if task.id != task_id]
            if len(tasks) == len(remaining):
                raise KeyError("任务不存在")
            write_json(self.repo.directory(batch_id) / "inputs/tasks.json", [t.model_dump() for t in remaining])
            batch.update(phase="draft", last_error=None)
            self.repo.save(batch)

    def _check_context(self, manifest: dict) -> None:
        if (manifest["project"], manifest["location"], manifest["bucket"]) != (
                self.settings.project, self.settings.location, self.settings.bucket):
            raise ValueError("当前项目、区域或桶名与批次快照不同；请恢复该批次的配置")

    def _attach(self, batch: dict, job) -> None:
        batch.update(job_name=job.name, cloud_state=job.state, phase="monitoring", last_error=None)
        if job.output_uri:
            batch["actual_output_uri"] = job.output_uri
        self.repo.save(batch)
        self.log(batch["id"], "job_attached", job_name=job.name)

    def _reconcile(self, batch: dict, manifest: dict) -> dict:
        jobs = self.cloud.find_jobs("vbs-" + batch["id"], manifest["input_uri"])
        if len(jobs) == 1:
            self._attach(batch, jobs[0])
        else:
            batch.update(phase="submission_unknown", last_error=(
                "尚未找到已提交任务；将继续核对，不会自动重复提交" if not jobs else
                "找到多个对应的云端任务，请通过 attach 指定正确的任务编号"))
            self.repo.save(batch)
        return batch

    def submit(self, batch_id: str) -> dict:
        with self.repo.lock(batch_id):
            batch = self.repo.get(batch_id)
            if batch["archived"]:
                raise ValueError("归档批次不能提交")
            if batch["job_name"]:
                return batch
            if batch["phase"] == "draft":
                manifest = prepare(self.repo, batch_id)
                manifest["tasks_sha256"] = sha256_file(self.repo.directory(batch_id) / "inputs/tasks.json")
                manifest["jsonl_sha256"] = sha256_file(self.repo.directory(batch_id) / "inputs/prompts.jsonl")
                write_json(self.repo.directory(batch_id) / "inputs/manifest.json", manifest)
                batch = self.repo.get(batch_id)
            else:
                manifest = self.manifest(batch_id)
            self._check_context(manifest)
            if batch["phase"] in {"submitting", "submission_unknown"}:
                return self._reconcile(batch, manifest)
            if batch["phase"] not in {"prepared", "upload_failed", "uploading", "submission_failed"}:
                raise ValueError("该批次不能提交；重复生成请创建新批次")
            directory = self.repo.directory(batch_id)
            for file, key in (("inputs/tasks.json", "tasks_sha256"),
                              ("inputs/prompts.jsonl", "jsonl_sha256")):
                if sha256_file(directory / file) != manifest[key]:
                    raise ValueError("准备后的输入文件被修改，请重新准备；已开始提交时请建立新批次")
            # Initialization failures cannot create a job. Resolve credentials before marking submitting.
            cloud = self.cloud
            batch.update(phase="uploading", last_error=None)
            self.repo.save(batch)
            try:
                for remote in manifest["remote_refs"]:
                    cloud.validate_reference(manifest["bucket"], remote["object_name"], remote["mime_type"])
                for asset in manifest["assets"]:
                    local = beneath(directory, asset["local_path"])
                    if sha256_file(local) != asset["sha256"]:
                        raise ValueError("准备的参考图快照被修改，禁止上传")
                    changed = cloud.upload(manifest["bucket"], asset["object_name"], local, asset["mime_type"])
                    self.log(batch_id, "asset_uploaded" if changed else "asset_skipped", object=asset["object_name"])
                bucket, object_name = split_gcs(manifest["input_uri"])
                cloud.upload(bucket, object_name, directory / "inputs/prompts.jsonl", "application/jsonl")
            except Exception as exc:
                batch.update(phase="upload_failed", last_error=str(exc))
                self.repo.save(batch)
                self.log(batch_id, "upload_failed", error=str(exc))
                raise
            batch.update(phase="submitting", submission_started_at=now())
            self.repo.save(batch)
            try:
                job = cloud.create_job(manifest["model"], manifest["input_uri"],
                                       manifest["output_prefix"], "vbs-" + batch["id"])
                self._attach(batch, job)
            except Exception as exc:
                # Also covers a successful API call followed by a failed local save.
                code = getattr(exc, "code", None)
                if callable(code):
                    code = code()
                rejected = code in {400, 401, 403, 404, 422}
                batch.update(phase="submission_failed" if rejected else "submission_unknown",
                             last_error=str(exc))
                self.repo.save(batch)
                self.log(batch_id, "submission_unknown", error=str(exc))
                raise
            return batch

    def attach(self, batch_id: str, job_name: str) -> dict:
        with self.repo.lock(batch_id):
            batch = self.repo.get(batch_id)
            manifest = self.manifest(batch_id)
            self._check_context(manifest)
            matching = self.cloud.find_jobs("vbs-" + batch_id, manifest["input_uri"])
            if job_name not in {j.name for j in matching}:
                raise ValueError("该云端任务的提交名称或输入地址与本批次不同")
            self._attach(batch, next(j for j in matching if j.name == job_name))
            return batch

    def _download(self, batch: dict, uri: str) -> None:
        bucket, _ = split_gcs(uri)
        manifest = self.manifest(batch["id"])
        if bucket != manifest["bucket"]:
            raise ValueError("任务返回的输出桶与批次配置不同")
        directory = self.repo.directory(batch["id"])
        existing = batch["downloaded_objects"]
        current = {}
        for obj in self.cloud.list_outputs(uri):
            previous = existing.get(obj.name)
            relative = "outputs/raw/" + hashlib.sha256(obj.name.encode()).hexdigest() + ".jsonl"
            target = beneath(directory, relative)
            cached = (previous and previous["generation"] == obj.generation and target.is_file()
                      and previous.get("sha256") == sha256_file(target))
            if not cached:
                temp = target.with_suffix(".download")
                try:
                    self.cloud.download(bucket, obj, temp)
                    if temp.stat().st_size != obj.size:
                        raise ValueError("下载大小与云端对象大小不同")
                    temp.replace(target)
                finally:
                    temp.unlink(missing_ok=True)
                self.log(batch["id"], "result_downloaded", object=obj.name, generation=obj.generation)
            current[obj.name] = {"generation": obj.generation, "local_path": relative,
                                 "size": obj.size, "sha256": sha256_file(target)}
            # Persist each completed shard so a later download failure does not lose the checkpoint.
            batch["downloaded_objects"][obj.name] = current[obj.name]
            self.repo.save(batch)
        batch["downloaded_objects"] = current

    def poll(self, batch_id: str) -> dict:
        with self.repo.lock(batch_id):
            batch = self.repo.get(batch_id)
            if batch["archived"]:
                return batch
            manifest = self.manifest(batch_id)
            self._check_context(manifest)
            try:
                if not batch["job_name"]:
                    if batch["phase"] in {"submitting", "submission_unknown"}:
                        return self._reconcile(batch, manifest)
                    raise ValueError("该批次尚未提交")
                job = self.cloud.get_job(batch["job_name"])
                terminal = job.state in TERMINAL
                batch.update(cloud_state=job.state, cloud_error=job.error,
                             phase="downloading" if terminal else "monitoring", last_error=None)
                if job.output_uri:
                    batch["actual_output_uri"] = job.output_uri
                self.repo.save(batch)
                output_uri = batch["actual_output_uri"] or manifest["output_prefix"]
                self._download(batch, output_uri)
                # Give an empty terminal output a bounded settling window before declaring rows missing.
                if terminal and not batch["downloaded_objects"]:
                    batch["empty_output_checks"] = batch.get("empty_output_checks", 0) + 1
                    settled = batch["empty_output_checks"] >= 3
                else:
                    settled = True
                    batch["empty_output_checks"] = 0
                report = extract(self.repo, batch, manifest, final=terminal and settled)
                if terminal and settled:
                    if job.state == "JOB_STATE_CANCELLED":
                        batch["phase"] = "cancelled"
                    elif job.state in {"JOB_STATE_FAILED", "JOB_STATE_EXPIRED"}:
                        batch["phase"] = "failed"
                    elif report["counts"]["error"] or report["counts"]["missing"] or report["row_errors"]:
                        batch["phase"] = "completed_with_errors"
                    else:
                        batch["phase"] = "completed"
                elif job.state == "JOB_STATE_PAUSED":
                    batch["phase"] = "paused"
                batch["last_polled_at"] = now()
                self.repo.save(batch)
                return batch
            except Exception as exc:
                batch["last_error"] = str(exc)
                self.repo.save(batch)
                self.log(batch_id, "poll_failed", error=str(exc))
                raise

    def extract_local(self, batch_id: str) -> dict:
        with self.repo.lock(batch_id):
            batch = self.repo.get(batch_id)
            if batch["archived"]:
                raise ValueError("归档批次不能修改；可以直接打开已有图片")
            report = extract(self.repo, batch, self.manifest(batch_id),
                             final=batch["cloud_state"] in TERMINAL)
            # A local repair can finish an earlier successful cloud job without generating again.
            if report["final"] and batch["cloud_state"] in {"JOB_STATE_SUCCEEDED", "JOB_STATE_PARTIALLY_SUCCEEDED"}:
                batch["phase"] = "completed_with_errors" if (
                    report["counts"]["error"] or report["counts"]["missing"] or report["row_errors"]) else "completed"
            self.repo.save(batch)
            return report

    def results(self, batch_id: str) -> dict:
        directory = self.repo.directory(batch_id)
        path = directory / "outputs/results.json"
        report = read_json(path) if path.exists() else {"tasks": [], "counts": {}, "row_errors": [], "final": False}
        # Also recovers an archive interrupted between the move and path rewrite.
        if directory.parent.name == "archive":
            old_root = self.settings.data_dir / "batches" / directory.name
            for task in report["tasks"]:
                for image in task["images"]:
                    old_path = Path(image["path"])
                    if old_path.is_relative_to(old_root):
                        image["path"] = str(directory / old_path.relative_to(old_root))
        return report

    def cancel(self, batch_id: str) -> dict:
        with self.repo.lock(batch_id):
            batch = self.repo.get(batch_id)
            if batch["archived"] or not batch["job_name"]:
                raise ValueError("只能取消已提交且未归档的任务")
            self._check_context(self.manifest(batch_id))
            if batch["cloud_state"] not in TERMINAL:
                self.cloud.cancel_job(batch["job_name"])
                batch["cancel_requested"] = True
                self.repo.save(batch)
            return batch

    def retry(self, batch_id: str, failed_only: bool = True) -> dict:
        with self.repo.lock(batch_id):
            source = self.repo.get(batch_id)
            selected = {r["task_id"] for r in self.results(batch_id)["tasks"]
                        if r["state"] in {"error", "missing"}}
            if failed_only and source["phase"] not in {"completed_with_errors", "failed", "cancelled"}:
                raise ValueError("批次结束后才能重试失败任务")
            tasks = [t for t in self.repo.tasks(batch_id) if not failed_only or t.id in selected]
            if not tasks:
                raise ValueError("没有可重试的任务")
            target = self.repo.create(source["project_name"], source_batch_id=batch_id)
            # Preserve frozen reference bytes even if the common library has since been edited.
            manifest_path = self.repo.directory(batch_id) / "inputs/manifest.json"
            manifest = read_json(manifest_path) if manifest_path.exists() else None
            snapshots = {a["source_path"]: a for a in manifest["assets"]} if manifest else {}
            inputs = []
            for task in tasks:
                values = task.model_dump(exclude={"id", "created_at"})
                refs = []
                for ref in task.refs:
                    if ref in snapshots:
                        path = beneath(self.repo.directory(batch_id), snapshots[ref]["local_path"])
                        refs.append(self.assets.import_file(str(path), batch_id=target["id"])["path"])
                    elif ref.startswith("gs://"):
                        refs.append(ref)
                    else:
                        prefix = f"batches/{source['folder']}/custom_refs/"
                        if source["archived"] and ref.startswith(prefix):
                            local = beneath(self.repo.directory(batch_id) / "custom_refs", ref[len(prefix):])
                        else:
                            local = self.assets.local(ref, batch_id)
                        refs.append(self.assets.import_file(str(local),
                                                           batch_id=target["id"])["path"])
                values["refs"] = refs
                inputs.append(TaskInput.model_validate(values))
            self.repo.replace_tasks(target["id"], inputs)
            return self.repo.get(target["id"])

    def enqueue(self, batch_id: str, action: str = "poll") -> bool:
        if action not in {"submit", "poll", "cancel", "extract_local"}:
            raise ValueError("不支持的后台动作")
        with self._inflight_lock:
            if batch_id in self._inflight:
                return False
            self._inflight.add(batch_id)
        def run():
            try:
                getattr(self, action)(batch_id)
            except BusyError:
                pass
            except Exception as exc:
                # Store failures before the operation entered its own recovery block too.
                try:
                    with self.repo.lock(batch_id):
                        batch = self.repo.get(batch_id)
                        batch["last_error"] = str(exc)
                        self.repo.save(batch)
                except (BusyError, KeyError):
                    pass
            finally:
                with self._inflight_lock:
                    self._inflight.discard(batch_id)
        self._executor.submit(run)
        return True

    def start(self) -> None:
        if self._worker:
            return
        def monitor():
            while not self._stop.is_set():
                for batch in self.repo.list():
                    if batch["archived"]:
                        continue
                    if batch["phase"] in {"monitoring", "downloading", "submitting", "submission_unknown"}:
                        self.enqueue(batch["id"], "poll")
                    elif batch["phase"] == "uploading":
                        self.enqueue(batch["id"], "submit")
                self._stop.wait(self.settings.poll_seconds)
        self._worker = threading.Thread(target=monitor, name="vbs-monitor", daemon=True)
        self._worker.start()

    def close(self) -> None:
        self._stop.set()
        if self._worker:
            self._worker.join(timeout=5)
        self._executor.shutdown(wait=True)
        if self._cloud and hasattr(self._cloud, "close"):
            self._cloud.close()
