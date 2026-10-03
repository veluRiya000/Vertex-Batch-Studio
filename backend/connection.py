"""Configure the existing service-account flow without exposing credential contents."""
from dataclasses import replace
import json
from pathlib import Path
import re
import uuid
from pydantic import Field
from .files import atomic_bytes, filename, operation_lock, BusyError
from .models import InputModel


class CloudConfiguration(InputModel):
    project: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")
    bucket: str = Field(min_length=3, max_length=222, pattern=r"^[a-z0-9][a-z0-9._-]+[a-z0-9]$")
    key_json: str | None = Field(default=None, max_length=1024 * 1024)
    credential_filename: str = Field(default="credentials.json", max_length=200)


def configure_cloud(studio, value: CloudConfiguration):
    # The enqueue lock closes the gap between an HTTP submission and its worker starting.
    with studio._inflight_lock, operation_lock(studio.settings.root / ".runtime/cloud-config.lock"):
        if studio._inflight or any(not b["archived"] and b["phase"] in {
            "monitoring", "uploading", "downloading", "submitting", "submission_unknown", "paused"
        } for b in studio.repo.list()):
            raise BusyError("当前还有运行中的批次，请完成或取消后再更换连接配置")
        key = None
        if value.key_json is not None:
            try:
                info = json.loads(value.key_json)
                if not isinstance(info, dict) or info.get("type") != "service_account":
                    raise ValueError()
                from google.oauth2 import service_account
                service_account.Credentials.from_service_account_info(info)
            except Exception:
                raise ValueError("这不是有效的 Google Cloud 服务账号 JSON 密钥") from None
            key = json.dumps(info, ensure_ascii=False, indent=2).encode("utf-8")
        settings = studio.settings
        new_key = settings.credentials_file
        changes = {"GOOGLE_CLOUD_PROJECT": value.project, "GCS_BUCKET": value.bucket}
        if key is not None:
            new_key = settings.root / "secrets" / (uuid.uuid4().hex + "_" + filename(Path(value.credential_filename).name, 100))
            changes["GOOGLE_APPLICATION_CREDENTIALS"] = new_key.relative_to(settings.root).as_posix()
        env_path = settings.root / ".env"
        lines = env_path.read_text(encoding="utf-8-sig").splitlines() if env_path.exists() else []
        remaining = dict(changes)
        output = []
        for line in lines:
            match = re.match(r"^\s*([A-Z_]+)\s*=", line)
            name = match.group(1) if match else None
            if name in changes:
                if name in remaining:
                    output.append(name + "=" + remaining.pop(name))
            else:
                output.append(line)
        output.extend(name + "=" + text for name, text in remaining.items())
        if key is not None:
            atomic_bytes(new_key, key)
        atomic_bytes(env_path, ("\n".join(output) + "\n").encode("utf-8"))
        # Keep the data directory and unrelated settings exactly as the current process uses them.
        new_settings = replace(settings, project=value.project, bucket=value.bucket, credentials_file=new_key)
        with studio._cloud_lock:
            if studio._cloud and hasattr(studio._cloud, "close"):
                try:
                    studio._cloud.close()
                except Exception:
                    pass  # A stale client's shutdown must not undo the saved configuration.
            studio._cloud = None
            studio.settings = studio.repo.settings = new_settings
        return new_settings
