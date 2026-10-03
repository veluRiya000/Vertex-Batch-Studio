"""Google SDK adapter. No credentials or SDK clients are loaded by offline operations."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from .config import Settings
from .files import sha256_file
from .jsonl import split_gcs

TERMINAL = {"JOB_STATE_SUCCEEDED", "JOB_STATE_FAILED", "JOB_STATE_CANCELLED",
            "JOB_STATE_EXPIRED", "JOB_STATE_PARTIALLY_SUCCEEDED"}


@dataclass
class Job:
    name: str
    state: str
    output_uri: str | None = None
    error: str | None = None


@dataclass
class CloudObject:
    name: str
    generation: str
    size: int


class Cloud(Protocol):
    def upload(self, bucket: str, name: str, local: Path, mime: str) -> bool: ...
    def validate_reference(self, bucket: str, name: str, mime: str) -> None: ...
    def create_job(self, model: str, input_uri: str, output_prefix: str, display_name: str) -> Job: ...
    def find_jobs(self, display_name: str, input_uri: str) -> list[Job]: ...
    def get_job(self, name: str) -> Job: ...
    def cancel_job(self, name: str) -> None: ...
    def list_outputs(self, uri: str) -> list[CloudObject]: ...
    def download(self, bucket: str, obj: CloudObject, target: Path) -> None: ...


class GoogleCloud:
    def __init__(self, settings: Settings):
        settings.require_cloud()
        from google import genai
        from google.genai import types
        from google.cloud import storage
        import google.auth
        from google.oauth2 import service_account

        if settings.credentials_file:
            credentials = service_account.Credentials.from_service_account_file(
                str(settings.credentials_file), scopes=["https://www.googleapis.com/auth/cloud-platform"])
        else:
            credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        self.genai = genai.Client(vertexai=True, project=settings.project,
                                  location=settings.location, credentials=credentials,
                                  http_options=types.HttpOptions(api_version="v1", timeout=60000))
        self.storage = storage.Client(project=settings.project, credentials=credentials)

    @staticmethod
    def job(value) -> Job:
        state = getattr(value.state, "value", value.state)
        output = getattr(getattr(value, "output_info", None), "gcs_output_directory", None)
        if not output:
            uris = getattr(getattr(value, "dest", None), "gcs_uri", None)
            if isinstance(uris, list) and uris:
                output = uris[0]
        error = getattr(value, "error", None)
        return Job(value.name, str(state), output, str(error) if error else None)

    def upload(self, bucket: str, name: str, local: Path, mime: str) -> bool:
        from google.api_core.exceptions import NotFound
        checksum = sha256_file(local)
        blob = self.storage.bucket(bucket).blob(name)
        try:
            blob.reload(timeout=60)
            if blob.size == local.stat().st_size and (blob.metadata or {}).get("sha256") == checksum:
                return False
            generation = blob.generation
        except NotFound:
            generation = 0
        blob.metadata = {"sha256": checksum}
        blob.upload_from_filename(str(local), content_type=mime, checksum="crc32c",
                                  if_generation_match=generation, timeout=120)
        return True

    def validate_reference(self, bucket: str, name: str, mime: str) -> None:
        blob = self.storage.bucket(bucket).blob(name)
        blob.reload(timeout=60)
        if blob.size > 30 * 1024 * 1024:
            raise ValueError("远程参考图超过 30 MB")
        if blob.content_type not in {mime, "application/octet-stream", None}:
            raise ValueError("远程参考图的 MIME 类型与后缀不符")

    def create_job(self, model: str, input_uri: str, output_prefix: str, display_name: str) -> Job:
        from google.genai.types import CreateBatchJobConfig
        return self.job(self.genai.batches.create(
            model=model, src=input_uri,
            config=CreateBatchJobConfig(dest=output_prefix, display_name=display_name)))

    def find_jobs(self, display_name: str, input_uri: str) -> list[Job]:
        found = []
        for job in self.genai.batches.list(config={"page_size": 100}):
            sources = getattr(getattr(job, "src", None), "gcs_uri", None) or []
            if job.display_name == display_name and input_uri in sources:
                found.append(self.job(job))
        return found

    def get_job(self, name: str) -> Job:
        return self.job(self.genai.batches.get(name=name))

    def cancel_job(self, name: str) -> None:
        self.genai.batches.cancel(name=name)

    def list_outputs(self, uri: str) -> list[CloudObject]:
        bucket, prefix = split_gcs(uri)
        prefix = prefix.rstrip("/") + "/"
        return [CloudObject(b.name, str(b.generation), b.size)
                for b in self.storage.list_blobs(bucket, prefix=prefix, timeout=60)
                if b.name.lower().endswith(".jsonl")]

    def download(self, bucket: str, obj: CloudObject, target: Path) -> None:
        blob = self.storage.bucket(bucket).blob(obj.name, generation=int(obj.generation))
        blob.download_to_filename(str(target), checksum="auto", timeout=120)

    def close(self) -> None:
        self.genai.close()
        self.storage.close()

    def check_connection(self, bucket: str) -> dict:
        """Read-only diagnostics; does not upload objects or create a prediction job."""
        from itertools import islice
        permissions = self.storage.bucket(bucket).test_iam_permissions([
            "storage.objects.get", "storage.objects.list", "storage.objects.create",
            "storage.objects.delete"], timeout=30)
        list(islice(self.storage.list_blobs(bucket, prefix="batches/", max_results=1, timeout=30), 1))
        list(islice(self.genai.batches.list(config={"page_size": 1}), 1))
        return {"storage_connection": "ok", "vertex_batch_list": "ok",
                "bucket_permissions": permissions,
                "note": "未创建生图任务；服务代理读写权限仍需首次真实任务验证"}
