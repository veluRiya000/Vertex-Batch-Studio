"""第一课：把软件的配置和路径放在同一个地方管理。

【当前状态】这是已经实现的参考代码，不是等待填空的练习文件。
你看不到 TODO，是因为本文件没有留未实现的函数。

【你需要填写的内容】不是下面的函数，而是项目根目录的 .env 配置文件。
把 .env.example 复制为 .env，再填写自己的 Google Cloud 项目 ID 和桶名。
没有 .env 时也能运行本文件、查看默认路径；联网前才检查云端配置。

【阅读顺序】Settings 的字段 → load() → 最下面的运行入口。
require_cloud() 和 initialize() 可以等你读懂路径后再看。
"""

from dataclasses import dataclass
from pathlib import Path
import os
import math


# dataclass 会根据下面的字段自动生成构造函数。
# frozen=True 表示创建后不能直接修改字段，避免运行中的配置被意外改动。
# 例如：settings = Settings.load()；读取字段用 settings.data_dir。
@dataclass(frozen=True)
class Settings:
    root: Path                              # 软件根目录：VertexBatchStudio/
    data_dir: Path                          # 用户数据目录：默认 root/data/
    project: str = ""                       # Google Cloud 项目 ID，不是批次的项目名称
    bucket: str = ""                        # GCS 桶名，只填名称，不填 gs://
    location: str = "global"                # Vertex AI 调用区域
    model: str = "gemini-3.1-flash-image"    # 生图模型 ID
    credentials_file: Path | None = None    # 密钥文件路径；None 表示使用默认登录凭证
    poll_seconds: float = 30                # 后续监控任务的检查间隔，单位为秒

    def __post_init__(self) -> None:
        # Windows 的 ADMINI~1 短路径和 Administrator 长路径也统一成同一写法。
        # 即使测试或其他模块直接构造 Settings，路径规则仍保持一致。
        root = self.root.expanduser().resolve()
        data = self.data_dir.expanduser()
        object.__setattr__(self, "root", root)
        object.__setattr__(self, "data_dir", (data if data.is_absolute() else root / data).resolve())
        if self.credentials_file:
            credentials = self.credentials_file.expanduser()
            object.__setattr__(self, "credentials_file", (
                credentials if credentials.is_absolute() else root / credentials).resolve())

    # classmethod 让你通过 Settings.load() 调用，不用先手动创建 Settings。
    # cls 在这里就是 Settings 类本身。
    @classmethod
    def load(cls, root: Path | None = None) -> "Settings":
        """读取配置并返回 Settings；本方法不创建目录，也不访问云端。

        root 不传时自动找到软件根目录；测试或指定其他配置目录时可以传入。
        Path | None 表示允许传 Path，也允许传 None。
        """
        # __file__ 是本文件的位置：VertexBatchStudio/backend/config.py。
        # parents[0] 是 backend/；parents[1] 是 VertexBatchStudio/。
        # resolve() 把路径整理成绝对路径，不依赖终端当前在哪个目录。
        root = (root or Path(__file__).resolve().parents[1]).resolve()

        # values 保存从 .env 读到的字符串，例如 {"GCS_BUCKET": "my-bucket"}。
        values: dict[str, str] = {}
        # Path 可以用 / 拼接路径：root / ".env" 表示根目录里的 .env 文件。
        env_file = root / ".env"
        if env_file.exists():
            # utf-8-sig 同时兼容普通 UTF-8 和带 BOM 的 UTF-8 文本。
            for line in env_file.read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                # 跳过空行和独立的注释行；注释要另起一行，不要放在值后面。
                if not line or line.startswith("#"):
                    continue
                # partition 只按第一个 = 拆分，得到键、分隔符和值。
                # 例如 "VBS_DATA_DIR=data" → ("VBS_DATA_DIR", "=", "data")。
                key, sep, value = line.partition("=")
                if not sep:
                    raise ValueError(".env 每行应为 KEY=VALUE")
                # 去除两侧空白和引号；这里只实现简单 KEY=VALUE 格式。
                # 不做 ${变量名} 展开，也不会执行文件里的文字。
                values[key.strip()] = value.strip().strip("\"'")

        def get(key: str, default: str = "") -> str:
            # 优先级：进程环境变量 → .env 中的值 → 这里传入的默认值。
            # 键存在但值为空时，空值会被保留，不会自动替换成 default。
            return os.environ.get(key, values.get(key, default))

        def path(value: str) -> Path:
            # expanduser() 把 ~ 展开为当前用户的主目录。
            p = Path(value).expanduser()
            # 绝对路径直接使用；相对路径以软件根目录为起点。
            # "data" → root/data；"D:/我的图片" → D:/我的图片。
            return (p if p.is_absolute() else root / p).resolve()

        # 配置指定了密钥路径就使用它；否则尝试根目录下的 secrets/key.json。
        # 这里只保存路径，不读取或打印密钥内容。
        credentials = get("GOOGLE_APPLICATION_CREDENTIALS")
        if not credentials and (root / "secrets/key.json").is_file():
            credentials = "secrets/key.json"

        # 配置文件里的值都是字符串，使用 float 转成秒数。
        interval = float(get("VBS_POLL_SECONDS", "30"))
        if not math.isfinite(interval) or interval < 1:
            raise ValueError("轮询间隔至少为 1 秒")

        # 创建并返回配置对象。使用 字段名=值，方便对应上面的字段。
        return cls(
            root=root,
            data_dir=path(get("VBS_DATA_DIR", "data")),
            project=get("GOOGLE_CLOUD_PROJECT"),
            bucket=get("GCS_BUCKET"),
            location=get("GOOGLE_CLOUD_LOCATION", "global"),
            model=get("VERTEX_MODEL", "gemini-3.1-flash-image"),
            credentials_file=path(credentials) if credentials else None,
            poll_seconds=interval,
        )

    def require_cloud(self, check_credentials: bool = True) -> None:
        """联网前检查本地配置；通过检查不代表云端权限已经验证。

        调用示例：settings.require_cloud()。
        不符合要求时抛出 ValueError，由后续界面显示错误信息。
        """
        if not self.project or not self.bucket:
            raise ValueError("请在 .env 配置 GOOGLE_CLOUD_PROJECT 和 GCS_BUCKET")
        if "/" in self.bucket or self.bucket.startswith("gs:"):
            raise ValueError("GCS_BUCKET 只填写桶名，不包含 gs:// 或路径")
        if check_credentials and self.credentials_file and not self.credentials_file.is_file():
            raise ValueError("配置的凭证文件不存在；可留空并使用本地 ADC")

    def initialize(self) -> None:
        """在本地创建公共参考图库、批次目录和归档目录。

        调用示例：settings.initialize()。
        这会实际创建文件夹；仅调用 load() 不会创建它们。
        """
        for sub in ("references/characters", "references/scenes", "references/styles",
                    "batches", "archive"):
            # parents=True：上层目录不存在时也创建。
            # exist_ok=True：目录已经存在时不报错、不覆盖里面的内容。
            (self.data_dir / sub).mkdir(parents=True, exist_ok=True)


# 直接运行本文件时执行下面的代码；被其他模块 import 时不会执行。
# 【你现在的检查入口】在编辑器里运行 config.py，观察这些输出。
# 显示配置并创建本地目录。
if __name__ == "__main__":
    settings = Settings.load()
    settings.require_cloud()
    settings.initialize()
    print("配置检查已通过，数据目录创建成功")
    print("软件根目录：", settings.root)
    print("数据目录：", settings.data_dir)
    print("公共参考图目录：", settings.data_dir / "references")
    print("批次目录：", settings.data_dir / "batches")
    print("归档目录：", settings.data_dir / "archive")
    print("Google Cloud 项目 ID：", settings.project or "尚未填写")
    print("GCS 桶名：", settings.bucket or "尚未填写")
    print("模型：", settings.model)
    print("区域：", settings.location)
    print("轮询间隔：", settings.poll_seconds, "秒")
    if not (settings.root / ".env").exists():
        print("提示：尚未创建 .env；目前显示的是默认值和已有环境变量。")
            
