"""Line protocol of the current ESP32 reader firmware (``RFID_ESP/ESP32_CARD_READER``).

Reader -> PC, every 750 ms::

    {"type":"login","username":"Erv","uid":"04A1B2C3","scoreloaded":"0","source":"rfid"}
    {"type":"login","username":"Unbekannt","source":"rfid"}        (no card)

plus plain text (boot messages, ``Write failed: ...``, ``Auth failed: ...``,
``Name erfolgreich auf Karte geschrieben.``). PC -> reader: one JSON object
per line (``setname``, ``highscore``, ``config``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

NO_NAME = "Unbekannt"
MAX_NAME = 15  # the name lives in one 16-byte MIFARE block


@dataclass(frozen=True, slots=True)
class Reading:
    """One report of the reader: a card (uid, name or None) or no card."""

    uid: str | None
    name: str | None


@dataclass(frozen=True, slots=True)
class WriteFailure:
    detail: str


@dataclass(frozen=True, slots=True)
class WriteDone:
    pass


Message = Reading | WriteFailure | WriteDone


def parse_line(line: str) -> Message | None:
    """Parse one line; ``None`` for anything that is not interesting."""
    line = line.strip()
    if not line:
        return None
    if line.startswith("{"):
        try:
            data = json.loads(line)
        except ValueError:
            return None
        if not isinstance(data, dict) or data.get("type") != "login":
            return None
        uid = str(data.get("uid") or "").strip().upper() or None
        name = str(data.get("username") or "").strip()
        if uid is None:
            return Reading(None, None)
        return Reading(uid, None if not name or name == NO_NAME else name)
    if line.startswith(("Write failed", "Auth failed")):
        return WriteFailure(line)
    if line.startswith("Name erfolgreich"):
        return WriteDone()
    return None


def setname(name: str) -> str:
    return json.dumps({"type": "setname", "value": name[:MAX_NAME]})


def highscore(value: int | str) -> str:
    return json.dumps({"type": "highscore", "value": str(value)})


def wifi_config(*, ssid: str, password: str, device: str, ip: str, port: int) -> str:
    """The reader's Wi-Fi settings (stored in its flash)."""
    return json.dumps(
        {"type": "config", "ip": ip, "port": port, "device": device, "ssid": ssid,
         "password": password},
    )  # fmt: skip
