"""Exercise the installed Google SDK's actual wire conversion, without network."""

import json
import unittest
import httpx
from google import genai
from google.oauth2.credentials import Credentials
from backend.cloud import GoogleCloud


class GoogleAdapterTests(unittest.TestCase):
    def test_sdk_creates_lists_and_reads_actual_output_directory(self):
        calls = []
        job = {
            "name": "projects/demo/locations/global/batchPredictionJobs/123",
            "displayName": "vbs-test", "state": "JOB_STATE_SUCCEEDED",
            "inputConfig": {"instancesFormat": "jsonl", "gcsSource": {"uris": ["gs://bucket/input.jsonl"]}},
            "outputConfig": {"predictionsFormat": "jsonl", "gcsDestination": {"outputUriPrefix": "gs://bucket/output/"}},
            "outputInfo": {"gcsOutputDirectory": "gs://bucket/output/generated-subfolder/"},
        }

        def transport(request):
            calls.append(request)
            if request.method == "GET" and request.url.path.endswith("batchPredictionJobs"):
                return httpx.Response(200, json={"batchPredictionJobs": [job]})
            return httpx.Response(200, json=job)

        adapter = GoogleCloud.__new__(GoogleCloud)
        adapter.genai = genai.Client(vertexai=True, project="demo", location="global",
                                     credentials=Credentials(token="offline-test-token"), http_options={
                                         "api_version": "v1", "client_args": {
                                             "transport": httpx.MockTransport(transport), "trust_env": False}})
        try:
            created = adapter.create_job("gemini-3.1-flash-image", "gs://bucket/input.jsonl",
                                         "gs://bucket/output/", "vbs-test")
            body = json.loads(calls[0].content)
            self.assertEqual(body["inputConfig"]["gcsSource"]["uris"], ["gs://bucket/input.jsonl"])
            self.assertEqual(body["outputConfig"]["gcsDestination"]["outputUriPrefix"], "gs://bucket/output/")
            self.assertIn("gemini-3.1-flash-image", body["model"])
            self.assertEqual(created.output_uri, "gs://bucket/output/generated-subfolder/")
            self.assertEqual(adapter.get_job(created.name).state, "JOB_STATE_SUCCEEDED")
            self.assertEqual(len(adapter.find_jobs("vbs-test", "gs://bucket/input.jsonl")), 1)
        finally:
            adapter.genai.close()
