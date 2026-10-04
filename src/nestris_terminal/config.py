"""Settings of the terminal.

Sources, later wins: defaults, the TOML file
(``%APPDATA%\\NestrisTerminal\\config.toml``, or ``NESTRIS_TERMINAL_CONFIG``),
environment variables ``NESTRIS_TERMINAL__<SECTION>__<KEY>``. The hidden
config menu edits the file through :func:`save_settings`.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sys
from pathlib import Path
from typing import Any, ClassVar, Literal

import tomli_w
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

APP_NAME = "NestrisTerminal"
DEFAULT_PIN = "2580"
_PIN_ITERATIONS = 200_000


def default_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / APP_NAME


def default_config_path() -> Path:
    override = os.environ.get("NESTRIS_TERMINAL_CONFIG")
    return Path(override) if override else default_data_dir() / "config.toml"


class HostSettings(BaseModel):
    # NestrisLTM base URL, e.g. http://192.168.1.10:7990
    url: str = "http://127.0.0.1:7990"
    # NestrisLTM API token with the "terminal" scope.
    token: SecretStr = SecretStr("")
    timeout_s: float = Field(default=8.0, gt=0)

    @field_validator("url")
    @classmethod
    def _url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("must start with http:// or https://")
        return value


class RfidSettings(BaseModel):
    driver: Literal["serial", "fake"] = "serial"
    # Empty = pick the first USB serial port that looks like the ESP32 reader.
    port: str = ""
    baud: int = 115200
    write_timeout_s: float = Field(default=15.0, gt=0, le=60)

    @model_validator(mode="before")
    @classmethod
    def _drop_legacy_keys(cls, data: Any) -> Any:
        # Reader protocol v1: the terminal decided when a card was removed.
        # The v2 firmware does that itself; old config files still carry the key.
        if isinstance(data, dict):
            data = {k: v for k, v in data.items() if k != "removed_after_s"}
        return data


class KioskSettings(BaseModel):
    fullscreen: bool = True
    hide_cursor: bool = False
    lang: Literal["de", "en"] = "de"
    # Player page closes this long after the card left (slips are forgiven).
    card_grace_s: float = Field(default=3.0, ge=0)
    # Player page / menus fall back to the main menu without touches.
    idle_timeout_s: float = Field(default=120.0, ge=10)


class AdminSettings(BaseModel):
    # pbkdf2-sha256 "salt$hash"; empty = the default PIN (shown in the README).
    pin_hash: str = ""


class HttpSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=7991, ge=1, le=65535)


class LogSettings(BaseModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    to_file: bool = True
    buffer_size: int = Field(default=1000, ge=100)


class UpdateSettings(BaseModel):
    # Automatic checks against GitHub releases; installing is always a click.
    enabled: bool = True
    channel: Literal["stable", "beta"] = "stable"
    owner: str = "oe7set"
    app_repo: str = "nestris-terminal"
    reader_repo: str = "nestris-rfid-reader"
    # Optional GitHub token (private forks, shared IP hitting the rate limit).
    token: SecretStr = SecretStr("")
    check_interval_h: float = Field(default=24.0, ge=1)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NESTRIS_TERMINAL__", env_nested_delimiter="__", extra="forbid"
    )

    config_file: ClassVar[Path | None] = None

    data_dir: Path = Field(default_factory=default_data_dir)
    host: HostSettings = Field(default_factory=HostSettings)
    rfid: RfidSettings = Field(default_factory=RfidSettings)
    kiosk: KioskSettings = Field(default_factory=KioskSettings)
    admin: AdminSettings = Field(default_factory=AdminSettings)
    http: HttpSettings = Field(default_factory=HttpSettings)
    log: LogSettings = Field(default_factory=LogSettings)
    updates: UpdateSettings = Field(default_factory=UpdateSettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        sources: list[PydanticBaseSettingsSource] = [init_settings, env_settings]
        if cls.config_file is not None and cls.config_file.is_file():
            sources.append(TomlConfigSettingsSource(settings_cls, toml_file=cls.config_file))
        return tuple(sources)

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"


def load_settings(config_file: Path | None = None, **overrides: Any) -> Settings:
    Settings.config_file = config_file if config_file is not None else default_config_path()
    return Settings(**overrides)


def save_settings(settings: Settings, path: Path | None = None) -> Path:
    """Write the settings (incl. secrets) to the TOML file, atomically."""
    target = path or Settings.config_file or default_config_path()
    data = settings.model_dump(mode="json", exclude={"data_dir"})
    data["host"]["token"] = settings.host.token.get_secret_value()
    data["updates"]["token"] = settings.updates.token.get_secret_value()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(tomli_w.dumps(data), encoding="utf-8")
    os.replace(tmp, target)
    return target


# ---------------------------------------------------------------- admin PIN


def hash_pin(pin: str) -> str:
    salt = secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), _PIN_ITERATIONS)
    return f"{salt}${digest.hex()}"


def check_pin(settings: Settings, pin: str) -> bool:
    stored = settings.admin.pin_hash
    if not stored:
        return hmac.compare_digest(pin, DEFAULT_PIN)
    salt, _, expected = stored.partition("$")
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), _PIN_ITERATIONS)
    return hmac.compare_digest(digest.hex(), expected)
