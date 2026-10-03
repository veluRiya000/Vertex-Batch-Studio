import uuid

from backend.files import write_json

from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.config import Settings
from backend.files import project_name as validate_project_name

def create_batch_directory(
    data_dir: Path,
    name: str,
) -> Path:
    # 调用已有的检查函数，拒绝空名称和非法字符。
    name = validate_project_name(name)

    # 明确使用北京时间，避免电脑时区影响日期。
    beijing = timezone(timedelta(hours=8))
    date = datetime.now(beijing).strftime("%Y%m%d")
    base_name = f"{date}_{name}"

    batches_dir = data_dir / "batches"
    archive_dir = data_dir / "archive"
    batches_dir.mkdir(parents=True, exist_ok=True)

    number = 1

    while True:
        # 第一次不加序号，之后加 _02、_03……
        folder_name = (
            base_name if number == 1
            else f"{base_name}_{number:02d}"
        )
        batch_dir = batches_dir / folder_name

        # 已归档的同名批次也占用这个名称。
        if (archive_dir / folder_name).exists():
            number += 1
            continue

        try:
            # 这里不使用 exist_ok=True，防止复用旧批次。
            batch_dir.mkdir()
            break
        except FileExistsError:
            number += 1

    # 在新批次里面创建所需的子目录。
    for folder in (
        "inputs",
        "custom_refs",
        "outputs/raw",
        "outputs/images",
        "logs",
    ):
        (batch_dir / folder).mkdir(parents=True)

        # 字典保存这个批次的信息。
    batch_info = {
        "id": uuid.uuid4().hex,
        "project_name": name,
        "folder": batch_dir.name,
        "created_at": datetime.now(beijing).isoformat(),
        "phase": "draft",
    }

    # 将字典保存为当前批次目录中的 batch.json。
    write_json(batch_dir / "batch.json", batch_info)

    return batch_dir


if __name__ == "__main__":
    settings = Settings.load()
    result = create_batch_directory(
        settings.data_dir,
        "我的第一个批次",
    )
    print("批次目录已创建：", result)




