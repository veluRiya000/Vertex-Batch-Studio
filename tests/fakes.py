"""A deterministic provider double: no Google credentials or network required."""

from dataclasses import replace
from io import BytesIO
from pathlib import Path
import base64
import copy
import json
from PIL import Image
from backend.cloud import Job, CloudObject
from backend.files import sha256_file
from backend.jsonl import split_gcs


def image_bytes(color=(1, 2, 3), format="PNG"):
    stream = BytesIO()
    Image.new("RGB", (8, 8), color).save(stream, format=format)
    return stream.getvalue()


def response(request, color=(1, 2, 3), format="PNG"):
    mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}[format]
    return {"request": copy.deepcopy(request), "status": "", "response": {
        "candidates": [{"content": {"parts": [{"inlineData": {
            "mimeType": mime, "data": base64.b64encode(image_bytes(color, format)).decode()}}]}}]}}


class FakeCloud:
    def __init__(self):
        self.objects = {}
        self.jobs = {}
        self.job_inputs = {}
        self.creates = 0
        self.uploads = []
        self.downloads = []
        self.create_timeout = False
        self.upload_error = False
        self.create_error = None
        self.download_error = None

    def put(self, bucket, name, data):
        previous = self.objects.get((bucket, name))
        generation = int(previous[1]) + 1 if previous else 1
        self.objects[bucket, name] = (data, str(generation))

    def upload(self, bucket, name, local, mime):
        if self.upload_error:
            raise ConnectionError("upload unavailable")
        content = local.read_bytes()
        previous = self.objects.get((bucket, name))
        if previous and previous[0] == content:
            return False
        self.put(bucket, name, content)
        self.uploads.append((bucket, name, mime, sha256_file(local)))
        return True

    def validate_reference(self, bucket, name, mime):
        if (bucket, name) not in self.objects:
            raise ValueError("reference not found")

    def create_job(self, model, input_uri, output_prefix, display_name):
        self.creates += 1
        if self.create_error:
            raise self.create_error
        name = f"projects/demo/locations/global/batchPredictionJobs/{self.creates}"
        job = Job(name, "JOB_STATE_PENDING")
        self.jobs[name] = job
        self.job_inputs[name] = (display_name, input_uri, output_prefix)
        if self.create_timeout:
            self.create_timeout = False
            raise TimeoutError("accepted but connection dropped")
        return job

    def find_jobs(self, display_name, input_uri):
        return [job for name, job in self.jobs.items()
                if self.job_inputs[name][:2] == (display_name, input_uri)]

    def get_job(self, name):
        return self.jobs[name]

    def cancel_job(self, name):
        self.jobs[name] = replace(self.jobs[name], state="JOB_STATE_CANCELLED")

    def list_outputs(self, uri):
        bucket, prefix = split_gcs(uri)
        return [CloudObject(name, generation, len(data))
                for (b, name), (data, generation) in self.objects.items()
                if b == bucket and name.startswith(prefix.rstrip("/") + "/") and name.endswith(".jsonl")]

    def download(self, bucket, obj, target):
        if self.download_error:
            raise self.download_error
        data, generation = self.objects[bucket, obj.name]
        if generation != obj.generation:
            raise ConnectionError("generation changed")
        target.write_bytes(data)
        self.downloads.append(obj.name)

    def finish(self, job_name, rows_by_file, state="JOB_STATE_SUCCEEDED"):
        uri = "gs://bucket/actual-output/" + job_name.rsplit("/", 1)[-1] + "/"
        self.jobs[job_name] = replace(self.jobs[job_name], state=state, output_uri=uri)
        bucket, prefix = split_gcs(uri)
        for file, rows in rows_by_file.items():
            data = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode()
            self.put(bucket, prefix + file, data)
