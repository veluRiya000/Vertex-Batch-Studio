"""Import verified image files and snapshot them before creating cloud requests."""
from __future__ import annotations

from pathlib import Path
from contextlib import ExitStack
import shutil
from PIL import Image
from .files import beneath, filename, sha256_file, operation_lock, read_json, write_json
from .repository import Repository

MIME = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


def inspect_image(path: Path) -> dict:
    if not path.is_file():
        raise ValueError(f"图片不存在：{path.name}")
    size = path.stat().st_size
    if size > 30 * 1024 * 1024:
        raise ValueError(f"参考图超过 30 MB：{path.name}")
    try:
        with Image.open(path) as image:
            mime = MIME.get(image.format)
            dimensions = list(image.size)
            image.verify()
    except (OSError, SyntaxError) as exc:
        raise ValueError(f"文件不是有效图片：{path.name}") from exc
    if not mime:
        raise ValueError("第一版支持 PNG、JPEG、WebP")
    return {"mime_type": mime, "size": size, "sha256": sha256_file(path),
            "dimensions": dimensions}


class Assets:
    def __init__(self, repo: Repository):
        self.repo = repo

    def import_file(self, source: str, category: str | None = None,
                    batch_id: str | None = None) -> dict:
        path = Path(source).expanduser().resolve()
        if bool(category) == bool(batch_id):
            raise ValueError("请选择公共参考图分类，或临时参考图所属批次")
        if category and category not in {"characters", "scenes", "styles"}:
            raise ValueError("分类应为 characters、scenes 或 styles")
        lock = self.repo.lock(batch_id) if batch_id else operation_lock(
            self.repo.settings.data_dir / ".locks/assets.lock")
        with lock:
            if batch_id:
                self.repo.editable(batch_id)
                directory = self.repo.directory(batch_id) / "custom_refs"
            else:
                directory = self.repo.settings.data_dir / "references" / category
            info = inspect_image(path)
            stem = filename(path.stem)
            index = 1
            while True:
                suffix = "" if index == 1 else f"_{index:02d}"
                target = directory / (stem + suffix + EXT[info["mime_type"]])
                if target.exists():
                    if sha256_file(target) == info["sha256"]:
                        break
                    index += 1
                    continue
                # Reserve the name atomically rather than overwriting an existing import.
                with path.open("rb") as src, target.open("xb") as dst:
                    shutil.copyfileobj(src, dst)
                if sha256_file(target) != info["sha256"]:
                    target.unlink()
                    raise ValueError("导入过程中原图发生变化，请重试")
                break
            return {"path": target.relative_to(self.repo.settings.data_dir).as_posix(), **info}

    def list(self, batch_id: str | None = None) -> list[dict]:
        roots = [self.repo.settings.data_dir / "references"]
        if batch_id:
            roots.append(self.repo.directory(batch_id) / "custom_refs")
        result = []
        for root in roots:
            for path in sorted(root.rglob("*")):
                if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                    try:
                        safe = beneath(root, path.relative_to(root).as_posix())
                        result.append({"path": path.relative_to(self.repo.settings.data_dir).as_posix(),
                                       **inspect_image(safe)})
                    except ValueError:
                        continue
        order = self._order()
        def position(item):
            path = item['path']
            parent = path.rsplit('/', 1)[0]
            saved = order.get(parent.removeprefix('references/'), [])
            return (0 if path.startswith('references/') else 1, parent,
                    saved.index(path) if path in saved else len(saved), path)
        return sorted(result, key=position)

    def _order(self) -> dict:
        path = self.repo.settings.data_dir / 'references/.order.json'
        if not path.exists():
            return {}
        try:
            value = read_json(path)
            return {key: paths for key, paths in value.items()
                    if key in {'characters', 'scenes', 'styles'} and isinstance(paths, list)
                    and all(isinstance(p, str) for p in paths)} if isinstance(value, dict) else {}
        except ValueError:
            return {}

    def reorder(self, category: str, paths: list[str]) -> list[dict]:
        if category not in {'characters', 'scenes', 'styles'}:
            raise ValueError('参考图分类无效')
        with operation_lock(self.repo.settings.data_dir / '.locks/assets.lock'):
            existing = {item['path'] for item in self.list()
                        if item['path'].startswith('references/' + category + '/')}
            if len(paths) != len(set(paths)) or set(paths) != existing:
                raise ValueError('参考图库已变化，请刷新后再排序')
            order = self._order()
            order[category] = paths
            write_json(self.repo.settings.data_dir / 'references/.order.json', order)
            return self.list()

    def local(self, ref: str, batch_id: str) -> Path:
        path = beneath(self.repo.settings.data_dir, ref)
        allowed = [self.repo.settings.data_dir / "references",
                   self.repo.directory(batch_id) / "custom_refs"]
        if not any(path.is_relative_to(root.resolve()) for root in allowed):
            raise ValueError("参考图应位于公共库或当前批次的 custom_refs 中")
        return path

    def delete(self, ref: str) -> list[dict]:
        parts = ref.split("/")
        if len(parts) < 3 or parts[0] != "references" or parts[1] not in {"styles", "characters", "scenes"}:
            raise ValueError("只能删除公共参考图库中的图片")
        root = self.repo.settings.data_dir / "references"
        target = beneath(root, "/".join(parts[1:]))
        if target.relative_to(self.repo.settings.data_dir.resolve()).as_posix() != ref:
            raise ValueError("参考图路径不规范，不能删除")
        if target.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"} or not target.is_file():
            raise KeyError("找不到参考图")
        with ExitStack() as locks:
            locks.enter_context(operation_lock(self.repo.settings.data_dir / ".locks/assets.lock"))
            for batch in sorted(self.repo.list(), key=lambda batch: batch["id"]):
                locks.enter_context(self.repo.lock(batch["id"]))
                if not any(ref in task.refs for task in self.repo.tasks(batch["id"])):
                    continue
                directory = self.repo.directory(batch["id"])
                manifest_path = directory / "inputs/manifest.json"
                snapshot = None
                if batch["phase"] not in {"draft", "prepared"} and manifest_path.exists():
                    snapshot = next((asset for asset in read_json(manifest_path).get("assets", [])
                                     if asset["source_path"] == ref), None)
                if not snapshot or not beneath(directory, snapshot["local_path"]).is_file():
                    raise ValueError(f"参考图正在被项目「{batch['project_name']}」使用，请先移除任务中的引用")
                if sha256_file(beneath(directory, snapshot["local_path"])) != snapshot["sha256"]:
                    raise ValueError("任务中的参考图快照损坏，不能删除原图")
            target.unlink()
            order = self._order()
            for category in order:
                order[category] = [path for path in order[category] if path != ref]
            write_json(root / ".order.json", order)
            return self.list()

    def snapshot(self, ref: str, batch_id: str) -> dict:
        source = self.local(ref, batch_id)
        info = inspect_image(source)
        directory = self.repo.directory(batch_id)
        target = directory / "inputs/assets" / (info["sha256"] + EXT[info["mime_type"]])
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copyfile(source, target)
        if sha256_file(target) != info["sha256"]:
            raise ValueError("参考图在准备过程中变化，请重新准备批次")
        source_relative = source.relative_to(self.repo.settings.data_dir)
        object_name = (source_relative.parent /
                       (filename(source.stem) + "_" + info["sha256"] + EXT[info["mime_type"]])).as_posix()
        return {"local_path": target.relative_to(directory).as_posix(),
                "source_path": ref, "object_name": object_name, **info}
