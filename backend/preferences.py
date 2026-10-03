"""Small persistent appearance and desktop preferences, separate from credentials."""
from typing import Literal
from pydantic import Field
from .models import InputModel
from .files import read_json, write_json, operation_lock


class Preferences(InputModel):
    theme: Literal["light", "dark"] = "light"
    language: Literal["zh-CN", "en"] = "zh-CN"
    close_to_tray: bool = True
    auto_start: bool = False
    start_minimized: bool = False
    sidebar_width: int = Field(default=258, ge=0, le=420, strict=True)


def load_preferences(root):
    path = root / "settings.json"
    return Preferences.model_validate(read_json(path)) if path.exists() else Preferences()


def save_preferences(root, value: Preferences):
    with operation_lock(root / ".runtime/preferences.lock"):
        write_json(root / "settings.json", value.model_dump())
    return value
