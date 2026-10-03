"""Command-line entrypoint: usable backend before a frontend has been designed."""

import argparse
from dataclasses import replace
import json
from pathlib import Path
import secrets
import socket
import sys
import re
from .config import Settings
from .files import read_json, write_json, operation_lock
from .jsonl import import_jsonl
from .models import TaskInput
from .service import Studio


def show(value):
    print(json.dumps(value, ensure_ascii=False, indent=2), flush=True)


def parser():
    p = argparse.ArgumentParser(description="VertexBatchStudio 本地生图批次后端")
    p.add_argument("--root", type=Path, help="软件根目录，默认从代码位置确定")
    commands = p.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="创建批次")
    create.add_argument("name")
    create.add_argument("--output", help="图片导出目录，默认批次内 outputs/images")
    commands.add_parser("list", help="列出批次")
    commands.add_parser("doctor", help="离线配置和依赖检查")
    commands.add_parser("check-cloud", help="只读验证云端连接和桶权限")
    commands.add_parser("stop", help="正常停止已运行的本机后端")
    serve = commands.add_parser("serve", help="启动本地接口与后台监控")
    serve.add_argument("--port", type=int, default=0, help="0 表示自动选择空闲端口")
    ref = commands.add_parser("import-ref", help="导入参考图")
    ref.add_argument("source")
    selection = ref.add_mutually_exclusive_group(required=True)
    selection.add_argument("--category", choices=["characters", "scenes", "styles"])
    selection.add_argument("--batch", dest="batch_id")
    refs = commands.add_parser("references", help="列出公共参考图及指定批次的临时图")
    refs.add_argument("--batch", dest="batch_id")
    for name in ("status", "tasks", "prepare", "submit", "poll", "watch", "cancel",
                 "results", "extract", "retry", "clone", "archive"):
        c = commands.add_parser(name)
        c.add_argument("batch_id")
    for name in ("set-tasks", "import-jsonl"):
        c = commands.add_parser(name)
        c.add_argument("batch_id")
        c.add_argument("source")
    output = commands.add_parser("set-output")
    output.add_argument("batch_id")
    output.add_argument("path", nargs="?")
    attach = commands.add_parser("attach")
    attach.add_argument("batch_id")
    attach.add_argument("job_name")
    return p


def serve(settings: Settings, port: int):
    import uvicorn
    from .api import create_app
    runtime = settings.root / ".runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    with operation_lock(runtime / "server.lock"):
        studio = Studio(settings)
        token = secrets.token_urlsafe(32)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", port))
        sock.listen(128)
        actual_port = sock.getsockname()[1]
        app = create_app(studio, token, lambda: setattr(server, "should_exit", True))
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=actual_port,
                                              log_level="info", access_log=False))
        connection = runtime / "connection.json"
        write_json(connection, {"url": f"http://127.0.0.1:{actual_port}", "token": token})
        print(f"本地接口：http://127.0.0.1:{actual_port}", flush=True)
        print(f"连接信息：{connection}（包含本机访问令牌）", flush=True)
        try:
            server.run(sockets=[sock])
        finally:
            sock.close()
            connection.unlink(missing_ok=True)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    studio = None
    try:
        settings = Settings.load(args.root)
        if args.command == "stop":
            connection = settings.root / ".runtime/connection.json"
            if not connection.exists():
                show({"status": "stopped"})
                return 0
            info = read_json(connection)
            if not re.fullmatch(r"http://127\.0\.0\.1:[0-9]+", info.get("url", "")):
                raise ValueError("连接记录不是本机后端地址")
            import httpx
            with httpx.Client(trust_env=False, timeout=10) as client:
                response = client.post(info["url"] + "/shutdown", headers={"X-VBS-Token": info["token"]})
                response.raise_for_status()
                show(response.json())
            return 0
        if args.command == "serve":
            serve(settings, args.port)
            return 0
        studio = Studio(settings)
        repo = studio.repo
        cmd = args.command
        if cmd == "create":
            show(repo.create(args.name, args.output))
        elif cmd == "list":
            show(repo.list())
        elif cmd == "doctor":
            from importlib.metadata import version, PackageNotFoundError
            installed = {}
            for name in ("fastapi", "uvicorn", "pydantic", "Pillow", "google-genai", "google-cloud-storage"):
                try:
                    installed[name] = version(name)
                except PackageNotFoundError:
                    installed[name] = "未安装"
            try:
                settings.require_cloud()
                validation = "通过（尚未验证云端权限）"
            except ValueError as exc:
                validation = str(exc)
            show({"root": str(settings.root), "data_dir": str(settings.data_dir),
                  "project": settings.project, "bucket": settings.bucket,
                  "model": settings.model, "location": settings.location,
                  "config_check": validation, "dependencies": installed})
        elif cmd == "check-cloud":
            show(studio.cloud.check_connection(settings.bucket))
        elif cmd == "import-ref":
            show(studio.assets.import_file(args.source, args.category, args.batch_id))
        elif cmd == "references":
            show(studio.assets.list(args.batch_id))
        elif cmd == "status":
            show(repo.get(args.batch_id))
        elif cmd == "tasks":
            show([t.model_dump() for t in repo.tasks(args.batch_id)])
        elif cmd == "set-tasks":
            values = read_json(Path(args.source))
            if isinstance(values, dict):
                values = values["tasks"]
            inputs = [TaskInput.model_validate({k: v for k, v in t.items() if k not in {"id", "created_at"}}) for t in values]
            show([t.model_dump() for t in repo.replace_tasks(args.batch_id, inputs)])
        elif cmd == "import-jsonl":
            show([t.model_dump() for t in import_jsonl(repo, args.batch_id, args.source)])
        elif cmd == "prepare":
            manifest = studio.prepare(args.batch_id)
            show({"task_count": len(manifest["requests"]), "input_uri": manifest["input_uri"],
                  "output_prefix": manifest["output_prefix"]})
        elif cmd == "watch":
            import time
            while True:
                try:
                    batch = studio.poll(args.batch_id)
                    show({"phase": batch["phase"], "cloud_state": batch["cloud_state"],
                          "counts": batch.get("counts", {}), "last_error": batch["last_error"]})
                    if batch["phase"] in {"completed", "completed_with_errors", "failed", "cancelled", "paused"}:
                        break
                except Exception as exc:
                    print(f"检查失败，稍后重试：{exc}", file=sys.stderr)
                time.sleep(settings.poll_seconds)
        elif cmd == "set-output":
            show(repo.set_output(args.batch_id, args.path))
        elif cmd == "attach":
            show(studio.attach(args.batch_id, args.job_name))
        elif cmd in {"retry", "clone"}:
            show(studio.retry(args.batch_id, failed_only=cmd == "retry"))
        elif cmd == "archive":
            show(repo.archive(args.batch_id))
        elif cmd == "extract":
            show(studio.extract_local(args.batch_id))
        else:
            show(getattr(studio, cmd)(args.batch_id))
        return 0
    except KeyboardInterrupt:
        print("本地处理已停止；已提交的云端任务继续运行。", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    finally:
        if studio:
            studio.close()
