"""Explicit offline DSH preview in an isolated directory; no cloud credentials."""
from pathlib import Path
import json
import signal
import threading
import sys
from backend.config import Settings
from backend.harness_runtime import HarnessRuntime


if __name__ == "__main__":
    base=Path(__file__).resolve().parents[1]
    stop_file=base/'.runtime/harness-preview.stop'
    if '--stop' in sys.argv:
        stop_file.write_text('stop',encoding='utf-8')
        raise SystemExit(0)
    stop_file.unlink(missing_ok=True)
    root=base/".runtime/harness-preview-v2"
    root.mkdir(parents=True,exist_ok=True)
    runtime=HarnessRuntime(Settings(root,root/'data'))
    url=runtime.start('http://127.0.0.1:1','offline-unused',offline=True)
    connection=base/'.runtime/harness-preview.json'
    connection.write_text(json.dumps({'url':url}),encoding='utf-8')
    print('Offline DSH preview ready (authentication URL kept private).',flush=True)
    stop=threading.Event()
    signal.signal(signal.SIGINT,lambda *_:stop.set())
    signal.signal(signal.SIGTERM,lambda *_:stop.set())
    try:
        while not stop.wait(1):
            if stop_file.exists():break
    finally:
        runtime.close()
        connection.unlink(missing_ok=True)
        stop_file.unlink(missing_ok=True)
