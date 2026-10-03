from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from nestris_terminal.config import DEFAULT_PIN, check_pin, hash_pin, load_settings, save_settings


def test_defaults_and_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    s = load_settings(path)
    assert s.http.port == 7991 and s.rfid.driver == "serial"
    assert check_pin(s, DEFAULT_PIN) and not check_pin(s, "0000")

    s.host.url = "http://192.168.1.10:7990"
    s.admin.pin_hash = hash_pin("135790")
    data = s.model_dump()
    data["host"]["token"] = "nltm_secret"
    s2 = type(s).model_validate(data)
    save_settings(s2, path)

    loaded = load_settings(path)
    assert loaded.host.url == "http://192.168.1.10:7990"
    assert loaded.host.token.get_secret_value() == "nltm_secret"
    assert check_pin(loaded, "135790") and not check_pin(loaded, DEFAULT_PIN)


def test_invalid_host_url(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[host]\nurl = "192.168.1.10"\n', encoding="utf-8")
    with pytest.raises(ValidationError):
        load_settings(path)
