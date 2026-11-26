"""Disposable previews of managed images. Originals never change."""

from hashlib import sha256
from io import BytesIO
from pathlib import Path
from threading import Lock

from PIL import Image, ImageOps

from .files import atomic_bytes


SIZES = (160, 320, 960)


class Thumbnails:
    """Generate on first access, serialize cache changes and evict oldest previews."""

    def __init__(self, root: Path, byte_limit: int = 128 * 1024 * 1024):
        self.root = root
        self.byte_limit = byte_limit
        self._lock = Lock()
        self._known = None

    def get(self, original: Path, size: int, source_key: str | None = None) -> bytes:
        if size not in SIZES:
            raise ValueError("不支持的缩略图大小")
        # A stored fingerprint can be shared by *verified* reference snapshots.
        # Output files may be overwritten/redecoded; use the current file identity.
        stat = original.stat()
        identity = source_key or f"{original}:{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ctime_ns}"
        key = sha256(f"v1:{size}:{identity}".encode()).hexdigest()
        target = self.root / f"{key}.webp"
        # Limit decoding to one original at a time, including after a project switch.
        with self._lock:
            try:
                return target.read_bytes()
            except OSError:
                pass
            try:
                with Image.open(original) as image:
                    # Let JPEG reduce the decoded image before EXIF orientation.
                    image.draft("RGB", (size, size))
                    image.thumbnail((size, size), Image.Resampling.LANCZOS)
                    oriented = ImageOps.exif_transpose(image)
                    if oriented.mode not in ("RGB", "RGBA"):
                        oriented = oriented.convert("RGBA" if "A" in oriented.getbands() or
                                                    "transparency" in oriented.info else "RGB")
                    output = BytesIO()
                    oriented.save(output, "WEBP", quality=78, method=3)
                    encoded = output.getvalue()
            except (OSError, Image.DecompressionBombError) as exc:
                raise ValueError("无法生成缩略图") from exc
            try:
                if self._known is None:
                    self._known = {
                        path: (stat.st_mtime_ns, stat.st_size)
                        for path in self.root.glob("*.webp")
                        if path.is_file() and (stat := path.stat())
                    }
                atomic_bytes(target, encoded)
                self._known[target] = (target.stat().st_mtime_ns, len(encoded))
                size_on_disk = sum(entry[1] for entry in self._known.values())
                if size_on_disk > self.byte_limit:
                    for path, (_, length) in sorted(self._known.items(), key=lambda item: item[1]):
                        path.unlink(missing_ok=True)
                        del self._known[path]
                        size_on_disk -= length
                        if size_on_disk <= self.byte_limit:
                            break
            except OSError:
                # A read-only/cache-full disk should not hide an otherwise valid image.
                pass
            return encoded
