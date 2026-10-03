"""Small public input models; cloud response objects stay in the cloud adapter."""

from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .files import project_name


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BatchCreate(InputModel):
    project_name: str
    image_output_dir: str | None = None
    source_batch_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")

    @field_validator("project_name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        return project_name(value)


class TaskInput(InputModel):
    name: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1)
    refs: list[str] = Field(default_factory=list, max_length=14)
    temperature: float | None = Field(default=None, ge=0, le=2)
    aspect_ratio: str = "16:9"
    image_size: str = "1K"
    # 期望数量只用于补充提示词；一个任务仍然对应一行请求。
    image_count: int = Field(default=1, ge=1, le=4, strict=True)
    generation_config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name", "prompt")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("名称和提示词不能为空")
        return value

    @field_validator("aspect_ratio")
    @classmethod
    def valid_ratio(cls, value: str) -> str:
        if value not in {"1:1", "3:2", "2:3", "3:4", "4:3", "4:5", "5:4",
                         "9:16", "16:9", "21:9", "9:21", "1:4", "4:1", "1:8", "8:1"}:
            raise ValueError("不支持的宽高比")
        return value

    @field_validator("image_size")
    @classmethod
    def valid_size(cls, value: str) -> str:
        if value not in {"512", "1K", "2K", "4K"}:
            raise ValueError("分辨率应为 512、1K、2K 或 4K")
        return value


class Task(TaskInput):
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    created_at: str | None = None


class ReferenceImport(InputModel):
    source: str
    category: str | None = None
    batch_id: str | None = None


class TasksReplace(InputModel):
    tasks: list[TaskInput | Task]


class JsonlImport(InputModel):
    source: str


class OutputDirectory(InputModel):
    path: str | None = None
