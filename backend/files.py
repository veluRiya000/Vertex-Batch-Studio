"""Atomic persistence, path boundaries, and cross-process operation locks."""

from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import os
import re
import uuid


class BusyError(RuntimeError):
    pass


def atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def write_json(path: Path, value: object) -> None:
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256_file(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def beneath(root: Path, relative: str) -> Path:
    if Path(relative).is_absolute() or "\\" in relative or ":" in relative:
        raise ValueError("受管理路径应为使用 / 分隔的相对路径")
    result = (root / relative).resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError("路径超出受管理目录")
    return result


def project_name(value: str) -> str:
    if not value.strip() or value != value.strip() or value.endswith("."):
        raise ValueError("项目名称不能为空，也不能以空格或句点结尾")
    if re.search(r'[<>:"/\\|?*\x00-\x1f]', value):
        raise ValueError('项目名称不能包含 < > : " / \\ | ? * 或控制字符')
    if len(value) > 80:
        raise ValueError("项目名称最多 80 个字符")
    return value


def filename(value: str, limit: int = 60) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")[:limit]
    if not cleaned or cleaned.upper().split(".")[0] in {
        "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        cleaned = "image_" + cleaned
    return cleaned


@contextmanager
def operation_lock(path: Path):
    """One writer across both CLI and HTTP processes; never delete a lock file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as f:
        f.seek(0, os.SEEK_END)
        if f.tell() == 0:
            f.write(b"0")
            f.flush()
        f.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            raise BusyError("该批次正在被另一个操作处理，请稍后重试") from exc
        try:
            yield
        finally:
            f.seek(0)
            if os.name == "nt":
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
