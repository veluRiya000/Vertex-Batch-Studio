"""Import verified image files and snapshot them before creating cloud requests."""
from __future__ import annotations

from pathlib import Path
from contextlib import ExitStack
import shutil
import re
import uuid
from functools import lru_cache
from PIL import Image
from .files import beneath, filename, sha256_file, operation_lock, read_json, write_json
from .repository import Repository

MIME = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


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


@lru_cache(maxsize=4096)
def _listing_image_info(path: Path, size: int, modified_ns: int, changed_ns: int) -> dict:
    # Cache only library display metadata. Submission and deletion safety checks
    # continue to inspect and hash their files independently.
    return inspect_image(path)


def _inspect_for_listing(path: Path) -> dict:
    stat = path.stat()
    return _listing_image_info(path, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


class Assets:
    def __init__(self, repo: Repository):
        self.repo = repo

    def _stored_categories(self) -> list[dict]:
        path = self.repo.settings.data_dir / "references/.categories.json"
        if path.exists():
            values = read_json(path)
            if not isinstance(values, list) or any(not isinstance(v, dict) or
                    not re.fullmatch(r"[a-z0-9_-]{1,60}", v.get("id", "")) or
                    not isinstance(v.get("label"), str) for v in values):
                raise ValueError("参考图分类配置损坏")
            return values
        return [{"id": "styles", "label": "风格"}, {"id": "characters", "label": "人设"},
                {"id": "scenes", "label": "场景"}]

    def _assignments(self) -> dict:
        path = self.repo.settings.data_dir / 'references/.categories-by-path.json'
        if not path.exists():
            return {}
        values = read_json(path)
        if not isinstance(values, dict) or any(not isinstance(key, str) or not key.startswith('references/')
                or '\\' in key or '..' in key.split('/') or not isinstance(value, str)
                or not re.fullmatch(r'[a-z0-9_-]{1,60}', value) for key, value in values.items()):
            raise ValueError('参考图分类记录损坏')
        return values

    def _visible_categories(self, values):
        # Derive the automatic tab from actual remaining files, including old
        # category folders. Never recreate an empty 'uncategorized' on restart.
        regular = [value for value in values if value['id'] != 'uncategorized']
        ids = {value['id'] for value in regular}
        assignments = self._assignments()
        root = self.repo.settings.data_dir / 'references'
        for path in root.rglob('*'):
            if not path.is_file() or path.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
                continue
            try:
                safe = beneath(root, path.relative_to(root).as_posix())
            except ValueError:
                continue
            ref = safe.relative_to(self.repo.settings.data_dir.resolve()).as_posix()
            if assignments.get(ref, ref.split('/')[1]) not in ids:
                try:
                    _inspect_for_listing(safe)
                except ValueError:
                    continue
                return regular + [{'id':'uncategorized', 'label':'未分类'}]
        return regular

    def categories(self) -> list[dict]:
        return self._visible_categories(self._stored_categories())

    def _save_categories(self, values):
        visible = self._visible_categories(values)
        write_json(self.repo.settings.data_dir / 'references/.categories.json', visible)
        return visible

    def move(self, ref: str, category: str) -> dict:
        with self.repo.reference_lock():
            categories = self.categories()
            if category not in {value['id'] for value in categories}:
                raise ValueError('目标分类不存在')
            if not ref.startswith('references/'):
                raise ValueError('只能移动公共参考图库中的图片')
            target = beneath(self.repo.settings.data_dir / 'references', ref[11:])
            if target.relative_to(self.repo.settings.data_dir.resolve()).as_posix() != ref:
                raise ValueError('参考图路径不规范')
            inspect_image(target)
            current = self.list()
            if ref not in {item['path'] for item in current}:
                raise KeyError('找不到参考图')
            order = self._order()
            target_order = [item['path'] for item in current if item['category_id'] == category and item['path'] != ref]
            for key in order:
                order[key] = [path for path in order[key] if path != ref]
            order[category] = target_order + [ref]
            assignments = self._assignments()
            assignments[ref] = category
            # Keep filenames and frozen/live task references stable. Only the
            # library classification changes, so no prompt or GCS URI is broken.
            write_json(self.repo.settings.data_dir / 'references/.categories-by-path.json', assignments)
            write_json(self.repo.settings.data_dir / 'references/.order.json', order)
            categories = self._save_categories(categories)
            return {'references': self.list(), 'categories': categories}

    def add_category(self, label: str) -> list[dict]:
        label = label.strip()
        if not label or len(label) > 30:
            raise ValueError("分类名称应为1至30个字符")
        if label == '未分类':
            raise ValueError('“未分类”为自动分类，请使用其他名称')
        with self.repo.reference_lock():
            values = self.categories()
            if len(values) >= 40:
                raise ValueError("最多添加40个参考图分类")
            if any(v["label"] == label for v in values):
                raise ValueError("分类名称已存在")
            ident = "group_" + uuid.uuid4().hex[:16]
            (self.repo.settings.data_dir / "references" / ident).mkdir(parents=True)
            values.append({"id": ident, "label": label})
            return self._save_categories(values)

    def delete_category(self, ident: str, move_to: str | None = None) -> list[dict]:
        with self.repo.reference_lock():
            values = self.categories()
            if ident not in {v["id"] for v in values}:
                if ident == 'uncategorized':
                    return self._save_categories(values)
                raise KeyError("分类不存在")
            remaining = [v for v in values if v["id"] != ident]
            members = [item for item in self.list() if item['category_id'] == ident]
            if move_to and move_to not in {value['id'] for value in remaining}:
                raise ValueError('请选择其他有效分类接收图片')
            if ident == 'uncategorized' and members and not move_to:
                raise ValueError('请先选择接收分类，再删除未分类')
            if members:
                assignments = self._assignments()
                for item in members:
                    assignments[item['path']] = move_to or 'uncategorized'
                write_json(self.repo.settings.data_dir / 'references/.categories-by-path.json', assignments)
            return self._save_categories(remaining)

    def import_file(self, source: str, category: str | None = None,
                    batch_id: str | None = None) -> dict:
        path = Path(source).expanduser().resolve()
        if bool(category) == bool(batch_id):
            raise ValueError("请选择公共参考图分类，或临时参考图所属批次")
        lock = self.repo.lock(batch_id) if batch_id else operation_lock(
            self.repo.settings.data_dir / ".locks/assets.lock")
        with lock:
            if category and category not in {v["id"] for v in self.categories()}:
                raise ValueError("参考图分类不存在")
            if batch_id:
                self.repo.editable(batch_id)
                directory = self.repo.directory(batch_id) / "custom_refs"
            else:
                directory = self.repo.settings.data_dir / "references" / category
            directory.mkdir(parents=True, exist_ok=True)
            return self._copy_image(path, directory, category)

    def scan_folder(self, source: str) -> dict:
        """Read names only; choosing or cancelling a folder never writes data."""
        directory = Path(source).expanduser().resolve()
        if not directory.is_dir():
            raise ValueError("参考图文件夹不存在")
        files, skipped = [], 0
        for path in directory.iterdir():
            if path.is_file() and not path.is_symlink():
                if path.suffix.lower() in IMAGE_SUFFIXES:
                    files.append(path.name)
                else:
                    skipped += 1
        return {"source": str(directory), "label": directory.name,
                "files": sorted(files, key=str.casefold), "skipped": skipped}

    def import_folder_files(self, source: str, category: str, files: list[str]) -> dict:
        # Small chunks let the interface show progress without serializing image
        # bytes through the WebView, or reloading/hash-checking the entire library.
        if not 1 <= len(files) <= 8 or len(files) != len(set(files)):
            raise ValueError("每次应导入 1 至 8 张不同图片")
        directory = Path(source).expanduser().resolve()
        if not directory.is_dir():
            raise ValueError("参考图文件夹不存在")
        for name in files:
            if not name or "/" in name or "\\" in name or ":" in name or Path(name).suffix.lower() not in IMAGE_SUFFIXES:
                raise ValueError("参考图文件名无效")
        with self.repo.reference_lock():
            if category == "uncategorized" or category not in {v["id"] for v in self._stored_categories()}:
                raise ValueError("参考图分类不存在")
            destination = self.repo.settings.data_dir / "references" / category
            destination.mkdir(parents=True, exist_ok=True)
            imported, failed = [], []
            for name in files:
                try:
                    path = beneath(directory, name)
                    if path.parent != directory or (directory / name).is_symlink():
                        raise ValueError("只能导入所选文件夹内的图片")
                    imported.append({**self._copy_image(path, destination, category), "category_id": category})
                except (ValueError, OSError) as exc:
                    failed.append({"name": name, "error": str(exc)})
            return {"references": imported, "failed": failed}

    def _copy_image(self, path: Path, directory: Path, category: str | None) -> dict:
        info = inspect_image(path)
        stem = filename(path.stem)
        index = 1
        while True:
            suffix = "" if index == 1 else f"_{index:02d}"
            target = directory / (stem + suffix + EXT[info["mime_type"]])
            if target.exists():
                relative = target.relative_to(self.repo.settings.data_dir).as_posix()
                same_category = not category or self._assignments().get(relative, category) == category
                if same_category and sha256_file(target) == info["sha256"]:
                    break
                index += 1
                continue
            # Reserve the name atomically rather than overwriting an existing import.
            with target.open("xb") as dst:
                try:
                    with path.open("rb") as src:
                        shutil.copyfileobj(src, dst)
                except BaseException:
                    dst.close()
                    target.unlink(missing_ok=True)
                    raise
            if sha256_file(target) != info["sha256"]:
                target.unlink()
                raise ValueError("导入过程中原图发生变化，请重试")
            break
        return {"path": target.relative_to(self.repo.settings.data_dir).as_posix(), **info}

    def list(self, batch_id: str | None = None) -> list[dict]:
        category_ids = {v["id"] for v in self.categories()}
        assignments = self._assignments()
        roots = [self.repo.settings.data_dir / "references"]
        if batch_id:
            roots.append(self.repo.directory(batch_id) / "custom_refs")
        result = []
        for root in roots:
            for path in sorted(root.rglob("*")):
                if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                    try:
                        safe = beneath(root, path.relative_to(root).as_posix())
                        relative = path.relative_to(self.repo.settings.data_dir)
                        assigned = assignments.get(relative.as_posix(), relative.parts[1])
                        result.append({"path": relative.as_posix(),
                                       "category_id": assigned if assigned in category_ids else "uncategorized",
                                       **_inspect_for_listing(safe)})
                    except (ValueError, OSError):
                        continue
        order = self._order()
        def position(item):
            path = item['path']
            parent = path.rsplit('/', 1)[0]
            saved = order.get(item.get('category_id', parent.removeprefix('references/')), [])
            return (0 if path.startswith('references/') else 1, item.get('category_id', parent),
                    saved.index(path) if path in saved else len(saved), path)
        return sorted(result, key=position)

    def _order(self) -> dict:
        path = self.repo.settings.data_dir / 'references/.order.json'
        if not path.exists():
            return {}
        try:
            value = read_json(path)
            return {key: paths for key, paths in value.items()
                    if re.fullmatch(r'[a-z0-9_-]{1,60}', key) and isinstance(paths, list)
                    and all(isinstance(p, str) for p in paths)} if isinstance(value, dict) else {}
        except ValueError:
            return {}

    def reorder(self, category: str, paths: list[str]) -> list[dict]:
        if category not in {v['id'] for v in self.categories()}:
            raise ValueError('参考图分类无效')
        with operation_lock(self.repo.settings.data_dir / '.locks/assets.lock'):
            existing = {item['path'] for item in self.list()
                        if item.get('category_id') == category}
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
        if len(parts) != 3 or parts[0] != "references" or not re.fullmatch(r"[a-z0-9_-]{1,60}", parts[1]):
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
            assignments = self._assignments()
            assignments.pop(ref, None)
            write_json(root / '.categories-by-path.json', assignments)
            order = self._order()
            for category in order:
                order[category] = [path for path in order[category] if path != ref]
            write_json(root / ".order.json", order)
            self._save_categories(self.categories())
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
