"""Lesson 2: readable, versioned JSON state with collision-free batch directories."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import uuid
import re
import warnings
from .config import Settings
from .files import read_json, write_json, project_name, operation_lock
from .models import Task, TaskInput

BEIJING = timezone(timedelta(hours=8))


def now() -> str:
    return datetime.now(BEIJING).isoformat()


class Repository:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.initialize()

    @staticmethod
    def normalize(batch: dict, directory: Path) -> dict:
        """Read the earlier five-field lesson format without changing user files."""
        if batch.get("schema_version", 1) != 1:
            raise ValueError("不支持的批次数据版本")
        if not re.fullmatch(r"[a-f0-9]{32}", str(batch.get("id", ""))):
            raise ValueError("批次 ID 无效")
        defaults = {
            "workspace_id": batch["id"],
            "schema_version": 1, "folder": directory.name,
            "updated_at": batch.get("created_at", ""), "source_batch_id": None,
            "phase": "draft", "cloud_state": None, "job_name": None,
            "input_uri": None, "output_prefix": None, "actual_output_uri": None,
            "image_output_dir": None, "last_error": None, "cancel_requested": False,
            "downloaded_objects": {}, "row_assignments": {},
        }
        for key, value in defaults.items():
            batch.setdefault(key, value)
        batch["archived"] = directory.parent.name == "archive"
        batch["folder"] = directory.name
        return batch

    def create(self, name: str, image_output_dir: str | None = None,
               source_batch_id: str | None = None) -> dict:
        name = project_name(name)
        source = self.get(source_batch_id) if source_batch_id else None
        base = datetime.now(BEIJING).strftime("%Y%m%d") + "_" + name
        index = 1
        while True:
            folder = base if index == 1 else f"{base}_{index:02d}"
            directory = self.settings.data_dir / "batches" / folder
            # Archived folders also reserve their original cloud prefix.
            if (self.settings.data_dir / "archive" / folder).exists():
                index += 1
                continue
            try:
                directory.mkdir()
                break
            except FileExistsError:
                index += 1
        for sub in ("inputs", "custom_refs", "outputs/raw", "outputs/images", "logs"):
            (directory / sub).mkdir(parents=True)
        batch = {
            "schema_version": 1, "id": uuid.uuid4().hex, "project_name": name,
            "folder": folder, "created_at": now(), "updated_at": now(),
            "source_batch_id": source_batch_id, "phase": "draft", "cloud_state": None,
            "job_name": None, "input_uri": None, "output_prefix": None,
            "actual_output_uri": None, "image_output_dir":
                str(Path(image_output_dir).expanduser().resolve()) if image_output_dir else None,
            "archived": False, "last_error": None, "cancel_requested": False,
            "downloaded_objects": {}, "row_assignments": {},
        }
        batch["workspace_id"] = source["workspace_id"] if source else batch["id"]
        write_json(directory / "batch.json", batch)
        write_json(directory / "inputs/tasks.json", [])
        return batch

    def directory(self, batch_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", batch_id):
            raise KeyError("不存在的批次 ID")
        for section in ("batches", "archive"):
            for path in (self.settings.data_dir / section).iterdir():
                metadata = path / "batch.json"
                if path.is_dir() and metadata.is_file():
                    try:
                        if read_json(metadata).get("id") == batch_id:
                            return path
                    except (ValueError, OSError, AttributeError):
                        continue
        raise KeyError("找不到批次")

    def get(self, batch_id: str) -> dict:
        directory = self.directory(batch_id)
        return self.normalize(read_json(directory / "batch.json"), directory)

    def save(self, batch: dict) -> None:
        batch["updated_at"] = now()
        write_json(self.directory(batch["id"]) / "batch.json", batch)

    def lock(self, batch_id: str):
        # Outside batch folder, so archive can move it while the lock is held.
        self.directory(batch_id)
        return operation_lock(self.settings.data_dir / ".locks" / (batch_id + ".lock"))

    def list(self) -> list[dict]:
        batches = []
        for section in ("batches", "archive"):
            for path in (self.settings.data_dir / section).glob("*/batch.json"):
                try:
                    batches.append(self.normalize(read_json(path), path.parent))
                except (ValueError, OSError, AttributeError) as exc:
                    warnings.warn(f"批次信息无法读取：{path.parent.name} ({exc})", stacklevel=2)
        return sorted(batches, key=lambda b: b["created_at"], reverse=True)

    def tasks(self, batch_id: str) -> list[Task]:
        path = self.directory(batch_id) / "inputs/tasks.json"
        return [Task.model_validate(t) for t in read_json(path)] if path.exists() else []

    def editable(self, batch_id: str) -> dict:
        batch = self.get(batch_id)
        if batch["archived"] or batch["phase"] not in {"draft", "prepared"}:
            raise ValueError("该批次输入已冻结；请建立新批次")
        return batch

    def replace_tasks(self, batch_id: str, tasks: list[TaskInput]) -> list[Task]:
        with self.lock(batch_id):
            batch = self.editable(batch_id)
            existing_ids = {t.id for t in self.tasks(batch_id)}
            items = []
            for task in tasks:
                if isinstance(task, Task):
                    if task.id not in existing_ids:
                        raise ValueError("任务 ID 不属于当前批次；新增任务请不填写 ID")
                    items.append(task)
                else:
                    items.append(Task(**task.model_dump(), id=uuid.uuid4().hex, created_at=now()))
            if len({t.id for t in items}) != len(items):
                raise ValueError("任务列表包含重复 ID")
            write_json(self.directory(batch_id) / "inputs/tasks.json", [t.model_dump() for t in items])
            batch.update(phase="draft", last_error=None)
            self.save(batch)
            return items

    def set_output(self, batch_id: str, path: str | None) -> dict:
        with self.lock(batch_id):
            batch = self.get(batch_id)
            if batch["archived"]:
                raise ValueError("归档批次不能修改")
            batch["image_output_dir"] = str(Path(path).expanduser().resolve()) if path else None
            self.save(batch)
            return batch

    def archive(self, batch_id: str) -> dict:
        with self.lock(batch_id):
            batch = self.get(batch_id)
            if batch["archived"]:
                return batch
            if batch["phase"] not in {"draft", "prepared", "completed", "completed_with_errors", "failed", "cancelled"}:
                raise ValueError("运行中或尚待处理的批次不能归档")
            source = self.directory(batch_id)
            target = self.settings.data_dir / "archive" / source.name
            if target.exists():
                raise ValueError("归档目录已存在")
            source.rename(target)
            report_path = target / "outputs/results.json"
            if report_path.exists():
                report = read_json(report_path)
                for task in report.get("tasks", []):
                    for image in task.get("images", []):
                        old_path = Path(image["path"])
                        if old_path.is_relative_to(source):
                            image["path"] = str(target / old_path.relative_to(source))
                write_json(report_path, report)
            batch["archived"] = True
            self.save(batch)
            return batch
