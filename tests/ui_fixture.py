"""Opt-in UI acceptance server. All provider operations are local test doubles.

Run: python -m tests.ui_fixture
Then set VBS_CONNECTION_FILE to .runtime/ui-fixture-connection.json for Vite.
This server never reads credentials or writes the user's data directory.
"""
import base64
import copy
import json
from pathlib import Path
import secrets
import socket
import time
import uuid
import uvicorn
from backend.api import create_app
from backend.config import Settings
from backend.files import write_json
from backend.models import TaskInput
from backend.service import Studio
from .fakes import FakeCloud, response


class PreviewCloud(FakeCloud):
    def __init__(self):
        super().__init__()
        self.created = {}

    def create_job(self, *args):
        job = super().create_job(*args)
        self.created[job.name] = time.monotonic()
        return job

    def get_job(self, name):
        if self.jobs[name].state == 'JOB_STATE_PENDING' and time.monotonic() - self.created[name] > 8:
            _, uri, _ = self.job_inputs[name]
            from backend.jsonl import split_gcs
            data = self.objects[split_gcs(uri)][0]
            rows = []
            for line in data.decode().splitlines():
                request = json.loads(line)['request']
                row = response(request)
                part = row['response']['candidates'][0]['content']['parts'][0]
                part['inlineData']['data'] = base64.b64encode(PREVIEW_BYTES).decode()
                # Multiple images in a single task exercise thumbnail selection.
                row['response']['candidates'][0]['content']['parts'] = [copy.deepcopy(part) for _ in range(4)]
                rows.append(row)
            self.finish(name, {'part-1.jsonl': rows})
        return super().get_job(name)


if __name__ == '__main__':
    base = Path(__file__).resolve().parents[1]
    from .fakes import image_bytes
    PREVIEW_BYTES = image_bytes((80, 160, 210))
    existing = sorted((base/'data/batches').glob('*/outputs/images/*.png'))
    if existing:
        PREVIEW_BYTES = existing[0].read_bytes()
    fixture = base/'.runtime/ui-fixture'/uuid.uuid4().hex
    studio = Studio(Settings(fixture, fixture/'data', project='offline-preview', bucket='bucket', poll_seconds=1), PreviewCloud())
    batch = studio.repo.create('界面验收 · 离线测试')
    studio.append_task(batch['id'], TaskInput(name='夏日祭 · 多图预览', prompt='黄昏的夏日祭街道，灯笼亮起，动画风格。', image_count=4))
    submitted = studio.submit(batch['id'])
    studio.cloud.created[submitted['job_name']] -= 10
    studio.poll(batch['id'])
    draft = studio.repo.create('自由创作 · 离线测试')
    image = fixture/'参考图.png'
    image.write_bytes(PREVIEW_BYTES)
    studio.assets.import_file(str(image), category='styles')
    for index in range(3):
        character = fixture / f'人设参考_{index + 1:02d}.png'
        character.write_bytes(existing[index % len(existing)].read_bytes() if existing else PREVIEW_BYTES)
        studio.assets.import_file(str(character), category='characters')
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    sock.listen(128)
    token = secrets.token_urlsafe(32)
    connection = base/'.runtime/ui-fixture-connection.json'
    write_json(connection, {'url':f'http://127.0.0.1:{sock.getsockname()[1]}','token':token})
    app = create_app(studio, token, lambda: setattr(server,'should_exit',True))
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', log_level='warning', access_log=False))
    print('Offline UI fixture ready', flush=True)
    try:
        server.run(sockets=[sock])
    finally:
        sock.close()
        connection.unlink(missing_ok=True)
