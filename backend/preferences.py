"""Small persistent appearance and desktop preferences, separate from credentials."""
from typing import Literal
from pydantic import Field
from .models import InputModel
from .files import read_json, write_json, operation_lock


class NotificationPreferences(InputModel):
    enabled: bool = True
    mode: Literal["all", "each"] = "all"
    image_batches: bool = True
    harness_tasks: bool = True
    include_failures: bool = True
    sound_enabled: bool = True
    sound: Literal["soft", "chime", "double", "custom"] = "soft"
    custom_sound_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}\.(wav|mp3)$")
    custom_sound_name: str | None = Field(default=None, max_length=160)


class Preferences(InputModel):
    notifications: NotificationPreferences = Field(default_factory=NotificationPreferences)
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
