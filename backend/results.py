"""Streaming extraction across all shards, with durable request-to-task assignments."""

from collections import defaultdict
from io import BytesIO
from pathlib import Path
import base64
import hashlib
import json
from PIL import Image
from .assets import MIME, EXT
from .files import atomic_bytes, beneath, filename, write_json
from .jsonl import canonical, echoed_matches, fingerprint
from .repository import Repository, now


def rows(directory: Path, objects: dict):
    for name, metadata in sorted(objects.items()):
        path = beneath(directory, metadata["local_path"])
        try:
            with path.open(encoding="utf-8-sig") as f:
                for number, line in enumerate(f, 1):
                    if not line.strip():
                        continue
                    key = name + ":" + str(number) + ":" + hashlib.sha256(line.encode()).hexdigest()
                    try:
                        row = json.loads(line)
                        if not isinstance(row, dict):
                            raise ValueError("结果行必须是对象")
                        yield key, name, number, row, None
                    except (ValueError, TypeError) as exc:
                        yield key, name, number, None, f"损坏 JSONL：{exc}"
        except (OSError, UnicodeError) as exc:
            yield name, name, 0, None, f"无法读取结果文件：{exc}"


def extract(repo: Repository, batch: dict, manifest: dict, final: bool = False) -> dict:
    directory = repo.directory(batch["id"])
    output = Path(batch["image_output_dir"]) if batch["image_output_dir"] else directory / "outputs/images"
    output.mkdir(parents=True, exist_ok=True)
    objects = batch["downloaded_objects"]
    groups = defaultdict(list)
    by_contents = defaultdict(set)
    request_by_group = {}
    for item in manifest["requests"]:
        group = item["fingerprint"]
        groups[group].append(item["task_id"])
        request_by_group[group] = item["request"]
        by_contents[fingerprint({"contents": item["request"]["contents"]})].add(group)
    for task_ids in groups.values():
        task_ids.sort()

    descriptors = []
    row_errors = []
    for key, name, number, row, error in rows(directory, objects):
        if error:
            row_errors.append({"object": name, "line": number, "error": error})
            continue
        returned = canonical(row.get("request") or {})
        if not isinstance(returned, dict):
            row_errors.append({"object": name, "line": number, "error": "回传 request 不是对象"})
            continue
        candidates = by_contents.get(fingerprint({"contents": returned.get("contents")}), set())
        matches = [g for g in candidates if echoed_matches(request_by_group[g], returned)]
        if not matches:
            row_errors.append({"object": name, "line": number,
                               "error": "无法对应提交请求；原始数据已保留"})
            continue
        # Exact echoes take priority. If the provider adds default fields, prefer
        # the most constrained matching request; equivalent variants can use the
        # remaining matching group. Never match a conflicting explicit setting.
        matches.sort(key=lambda group: (
            canonical(request_by_group[group]) == returned,
            len(json.dumps(request_by_group[group]["generationConfig"], sort_keys=True))), reverse=True)
        descriptors.append((key, matches, name, number))

    current = {key for key, _, _, _ in descriptors}
    assignments = {key: value for key, value in batch.get("row_assignments", {}).items() if key in current}
    used = set(assignments.values())
    for key, matching_groups, name, number in descriptors:
        if key not in assignments:
            available = [tid for group in matching_groups for tid in groups[group] if tid not in used]
            if not available:
                row_errors.append({"object": name, "line": number,
                                   "error": "结果数量超过相同请求的任务数量"})
                continue
            assignments[key] = available[0]
            used.add(available[0])
    batch["row_assignments"] = assignments
    results = {item["task_id"]: {
        "task_id": item["task_id"], "name": item["name"], "state": "pending",
        "images": [], "error": None,
    } for item in manifest["requests"]}

    for key, name, number, row, read_error in rows(directory, objects):
        if read_error or key not in assignments:
            continue
        result = results[assignments[key]]
        result.update(source_object=name, source_line=number)
        status = row.get("status")
        if status or row.get("error"):
            result.update(state="error", error=str(row.get("error") or status))
            continue
        response = canonical(row.get("response") or {})
        errors = []
        candidates = response.get("candidates", []) if isinstance(response, dict) else None
        if not isinstance(candidates, list):
            result.update(state="error", error="损坏的 response/candidates 结构")
            continue
        for candidate_index, candidate in enumerate(candidates, 1):
            content = candidate.get("content") if isinstance(candidate, dict) else None
            parts = (content or {}).get("parts", []) if isinstance(content, (dict, type(None))) else None
            if not isinstance(parts, list):
                errors.append("损坏的 candidate.content.parts 结构")
                continue
            for part_index, part in enumerate(parts, 1):
                if not isinstance(part, dict):
                    errors.append("损坏的图片 part 结构")
                    continue
                if part.get("thought") or "inlineData" not in part:
                    continue
                inline = part["inlineData"]
                if not isinstance(inline, dict):
                    errors.append("损坏的 inlineData 结构")
                    continue
                mime = inline.get("mimeType")
                if mime not in EXT:
                    errors.append("输出图片 MIME 类型不受支持")
                    continue
                try:
                    data = base64.b64decode(inline.get("data", ""), validate=True)
                    with Image.open(BytesIO(data)) as image:
                        if MIME.get(image.format) != mime:
                            raise ValueError("图片内容与 MIME 类型不符")
                        image.verify()
                    name_part = filename(result["name"], limit=30)
                    image_name = f"{name_part}_{result['task_id']}_c{candidate_index:02d}_i{part_index:02d}{EXT[mime]}"
                    target = output / image_name
                    digest = hashlib.sha256(data).hexdigest()
                    if target.exists():
                        from .files import sha256_file
                        unchanged = sha256_file(target) == digest
                    else:
                        unchanged = False
                    if not unchanged:
                        atomic_bytes(target, data)
                    result["images"].append({"path": str(target.resolve()), "mime_type": mime,
                                              "sha256": digest, "size": len(data)})
                except (ValueError, OSError, SyntaxError, TypeError) as exc:
                    errors.append(f"图片解码或保存失败：{exc}")
        if errors:
            result.update(state="error", error="；".join(errors))
        elif result["images"]:
            result["state"] = "succeeded"
        else:
            reasons = [c.get("finishReason") for c in candidates if isinstance(c, dict)]
            result.update(state="error", error="未返回图片：" + str(
                response.get("promptFeedback") or reasons))
    if final:
        for result in results.values():
            if result["state"] == "pending":
                result.update(state="missing", error="云端任务已结束，但未找到该任务结果")
    values = list(results.values())
    counts = {state: sum(r["state"] == state for r in values)
              for state in ("succeeded", "error", "missing", "pending")}
    counts["images"] = sum(len(r["images"]) for r in values)
    report = {"updated_at": now(), "final": final, "counts": counts,
              "tasks": values, "row_errors": row_errors}
    write_json(directory / "outputs/results.json", report)
    batch["counts"] = counts
    return report
