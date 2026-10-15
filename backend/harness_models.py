"""Validated local inputs for the private Batch model bridge."""
from typing import Any
from pydantic import Field, field_validator, model_validator
from .models import InputModel
from .harness_profiles import profile


class HarnessRun(InputModel):
    run_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    session_id: str = Field(min_length=1, max_length=160)
    workspace: str = Field(min_length=1)
    budget_usd: float = Field(default=5, gt=0, allow_inf_nan=False)
    max_rounds: int = Field(default=20, ge=1, strict=True)
    limits_enabled: bool = Field(default=False, strict=True)


class HarnessRequest(InputModel):
    request_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    run_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    session_id: str = Field(min_length=1, max_length=160)
    step_id: str = Field(min_length=1, max_length=160)
    model: str = "gemini-4-argon"
    request: dict[str, Any]

    @field_validator("model")
    @classmethod
    def argon(cls, value):
        profile(value)
        return value

    @model_validator(mode="after")
    def model_output(self):
        spec = profile(self.model)
        cap = self.request.get("generationConfig", {}).get("maxOutputTokens", 65536)
        if cap > spec["output_limit"]:
            raise ValueError(f"{spec['label']} 官方最大输出为 {spec['output_limit']} Token，请调整输出额度")
        return self

    @field_validator("request")
    @classmethod
    def request_fields(cls, value):
        allowed = {"contents", "systemInstruction", "tools", "toolConfig", "generationConfig"}
        if set(value) - allowed or not isinstance(value.get("contents"), list) or not value["contents"]:
            raise ValueError("Gemini 请求字段无效")
        config = value.get("generationConfig", {})
        if not isinstance(config, dict):
            raise ValueError("生成参数必须是对象")
        if set(config) - {"maxOutputTokens", "thinkingConfig"}:
            raise ValueError("Argon 不接受当前生成参数")
        cap = config.get("maxOutputTokens", 65536)
        if type(cap) is not int or not 1 <= cap <= 1048576:
            raise ValueError("输出额度须在模型总额度 1–1048576 Token 内")
        thinking = config.get("thinkingConfig", {})
        if not isinstance(thinking, dict) or set(thinking) - {"thinkingLevel"} or thinking.get("thinkingLevel", "MEDIUM") not in {"LOW", "MEDIUM", "HIGH"}:
            raise ValueError("思考等级只支持 LOW、MEDIUM、HIGH")
        return value


class HarnessStart(InputModel):
    offline: bool = False


class HarnessResume(InputModel):
    limits_enabled: bool | None = Field(default=None, strict=True)
    budget_usd: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    max_rounds: int | None = Field(default=None, ge=1, strict=True)
