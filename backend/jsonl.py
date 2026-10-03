"""Lesson 3: official JSONL, legacy import, and request-based result matching."""

import copy
import hashlib
import json
import re
from pathlib import Path
from .assets import Assets
from .files import atomic_bytes, write_json
from .models import TaskInput
from .repository import Repository

ALIASES = {
    "file_data": "fileData", "file_uri": "fileUri", "mime_type": "mimeType",
    "generation_config": "generationConfig", "image_config": "imageConfig",
    "aspect_ratio": "aspectRatio", "image_size": "imageSize",
    "response_modalities": "responseModalities", "inline_data": "inlineData",
    "system_instruction": "systemInstruction", "top_p": "topP", "top_k": "topK",
    "max_output_tokens": "maxOutputTokens", "candidate_count": "candidateCount",
    "safety_settings": "safetySettings", "thinking_config": "thinkingConfig",
}


def canonical(value):
    if isinstance(value, dict):
        return {ALIASES.get(k, k): canonical(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [canonical(v) for v in value]
    # JSON numbers 1 and 1.0 describe the same generation setting.
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def fingerprint(request: dict) -> str:
    encoded = json.dumps(canonical(request), sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def echoed_matches(expected, actual) -> bool:
    """Ignore response-added defaults, but require all explicitly submitted fields."""
    expected, actual = canonical(expected), canonical(actual)
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and echoed_matches(value, actual[key]) for key, value in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(expected) == len(actual) and all(
            echoed_matches(x, y) for x, y in zip(expected, actual))
    return expected == actual


def split_gcs(uri: str) -> tuple[str, str]:
    match = re.fullmatch(r"gs://([^/]+)/(.+)", uri)
    if not match or any(part in {".", ".."} for part in match.group(2).split("/")):
        raise ValueError("无效的 gs:// 图片或输出地址")
    return match.group(1), match.group(2)


def prepare(repo: Repository, batch_id: str) -> dict:
    batch = repo.editable(batch_id)
    repo.settings.require_cloud(check_credentials=False)
    tasks = repo.tasks(batch_id)
    if not tasks:
        raise ValueError("批次至少需要一条任务")
    assets = Assets(repo)
    directory = repo.directory(batch_id)
    snapshots: dict[str, dict] = {}
    remote_refs: dict[str, dict] = {}
    requests = []
    for task in tasks:
        # 从原始提示词生成提交文本，不改写 tasks.json，也不累积追加。
        prompt = task.prompt
        if task.image_count > 1:
            prompt += f"\n\n请生成{task.image_count}张独立图片，每张单独输出，不要将多张图片拼成一张。"
        parts = [{"text": prompt}]
        for ref in task.refs:
            if ref.startswith("gs://"):
                bucket, name = split_gcs(ref)
                if bucket != repo.settings.bucket:
                    raise ValueError("第一版只支持当前存储桶内的远程参考图")
                suffix = Path(name).suffix.lower()
                mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                        ".webp": "image/webp"}.get(suffix)
                if not mime:
                    raise ValueError("远程参考图只支持 PNG、JPEG、WebP")
                uri = ref
                remote_refs[ref] = {"object_name": name, "mime_type": mime}
            else:
                if ref not in snapshots:
                    snapshots[ref] = assets.snapshot(ref, batch_id)
                snapshot = snapshots[ref]
                uri = f"gs://{repo.settings.bucket}/{snapshot['object_name']}"
                mime = snapshot["mime_type"]
            parts.append({"fileData": {"fileUri": uri, "mimeType": mime}})
        config = copy.deepcopy(canonical(task.generation_config))
        if task.temperature is not None:
            config["temperature"] = task.temperature
        config["responseModalities"] = ["TEXT", "IMAGE"]
        if not isinstance(config.get("imageConfig", {}), dict):
            raise ValueError("generation_config.imageConfig 必须是对象")
        config.setdefault("imageConfig", {}).update(
            aspectRatio=task.aspect_ratio, imageSize=task.image_size)
        request = {"contents": [{"role": "user", "parts": parts}], "generationConfig": config}
        requests.append({"task_id": task.id, "name": task.name,
                         "request": request, "fingerprint": fingerprint(request)})
    prefix = "batches/" + batch["folder"]
    manifest = {
        "schema_version": 1, "project": repo.settings.project, "bucket": repo.settings.bucket,
        "model": repo.settings.model, "location": repo.settings.location,
        "assets": list(snapshots.values()), "remote_refs": list(remote_refs.values()),
        "requests": requests, "input_uri": f"gs://{repo.settings.bucket}/{prefix}/inputs/prompts.jsonl",
        "output_prefix": f"gs://{repo.settings.bucket}/{prefix}/outputs/",
    }
    content = "".join(json.dumps({"request": r["request"]}, ensure_ascii=False, allow_nan=False,
                                 separators=(",", ":")) + "\n" for r in requests)
    atomic_bytes(directory / "inputs/prompts.jsonl", content.encode("utf-8"))
    write_json(directory / "inputs/manifest.json", manifest)
    batch.update(phase="prepared", input_uri=manifest["input_uri"],
                 output_prefix=manifest["output_prefix"], last_error=None)
    repo.save(batch)
    return manifest


def import_jsonl(repo: Repository, batch_id: str, source: str) -> list:
    """Import plain data, never import or execute an old Python task script."""
    tasks = []
    with Path(source).open(encoding="utf-8-sig") as f:
        for number, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                request = canonical(row["request"])
                if set(request) - {"contents", "generationConfig"}:
                    raise ValueError("此导入器只支持 contents 和 generationConfig")
                contents = request["contents"]
                if len(contents) != 1 or contents[0].get("role", "user") != "user":
                    raise ValueError("此导入器仅支持单轮 user 请求")
                parts = contents[0]["parts"]
                if any(set(p) - {"text", "fileData"} for p in parts):
                    raise ValueError("不支持的请求部分")
                text_parts = [p["text"] for p in parts if p.get("text") is not None]
                if len(text_parts) != 1 or "text" not in parts[0]:
                    raise ValueError("此导入器要求提示词在前，随后为参考图")
                config = request.get("generationConfig", {})
                image = config.get("imageConfig", {})
                tasks.append(TaskInput(
                    name=f"Imported_{number:04d}", prompt=text_parts[0],
                    refs=[p["fileData"]["fileUri"] for p in parts if p.get("fileData")],
                    temperature=config.get("temperature"),
                    aspect_ratio=image.get("aspectRatio", "16:9"),
                    image_size=image.get("imageSize", "1K"), generation_config=config))
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"JSONL 第 {number} 行：{exc}") from exc
    return repo.replace_tasks(batch_id, tasks)
