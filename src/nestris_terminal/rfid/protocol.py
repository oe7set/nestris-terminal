"""Reader protocol v2 (``../nestris-rfid-reader/docs/PROTOCOL.md``).

JSON lines over USB serial. The reader announces itself with ``hello``,
reports card changes as ``card`` events, sends a ``status`` heartbeat every
2 s and answers every command with ``result`` (``hello`` with ``hello``).
Lines that are not JSON objects (ESP32 boot text) are ignored.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

PROTOCOL = 2
MAX_NAME = 15  # one 16-byte MIFARE block minus the terminating zero
FORMATS = {"retroverse", "legacy", "blank", "corrupt", "unreadable", "unsupported"}


@dataclass(frozen=True, slots=True)
class CardData:
    uid: str
    name: str | None
    format: str

    def as_dict(self) -> dict[str, Any]:
        return {"uid": self.uid, "name": self.name, "format": self.format}


@dataclass(frozen=True, slots=True)
class Hello:
    proto: int
    fw: str
    board: str
    serial: str
    display: str
    reader_ok: bool
    chip: str
    card: CardData | None
    id: int | None = None
    raw: dict[str, Any] = field(default_factory=dict, compare=False)


@dataclass(frozen=True, slots=True)
class CardPresent:
    card: CardData


@dataclass(frozen=True, slots=True)
class CardRemoved:
    uid: str


@dataclass(frozen=True, slots=True)
class Status:
    card: CardData | None
    reader_ok: bool
    host: bool
    uptime_s: int


@dataclass(frozen=True, slots=True)
class Result:
    id: int | None
    ok: bool
    error: str | None = None
    detail: str | None = None
    uid: str | None = None
    name: str | None = None


@dataclass(frozen=True, slots=True)
class Log:
    level: str
    msg: str


Message = Hello | CardPresent | CardRemoved | Status | Result | Log


def _card(data: Any) -> CardData | None:
    if not isinstance(data, dict) or not isinstance(data.get("uid"), str):
        return None
    name = data.get("name")
    fmt = data.get("format")
    return CardData(
        uid=data["uid"].strip().upper(),
        name=name if isinstance(name, str) and name else None,
        format=fmt if fmt in FORMATS else "unreadable",
    )


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def parse_line(line: str) -> Message | None:
    """Parse one line from the reader; ``None`` for anything unknown."""
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        data = json.loads(line)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    kind = data.get("type")
    if kind == "hello":
        return Hello(
            proto=_int(data.get("proto")) or 0,
            fw=str(data.get("fw") or ""),
            board=str(data.get("board") or ""),
            serial=str(data.get("serial") or ""),
            display=str(data.get("display") or "none"),
            reader_ok=data.get("reader") == "ok",
            chip=str(data.get("chip") or ""),
            card=_card(data.get("card")),
            id=_int(data.get("id")),
            raw=data,
        )
    if kind == "card":
        if data.get("state") == "present":
            card = _card(data)
            return CardPresent(card) if card else None
        if data.get("state") == "removed" and isinstance(data.get("uid"), str):
            return CardRemoved(data["uid"].strip().upper())
        return None
    if kind == "status":
        return Status(
            card=_card(data.get("card")),
            reader_ok=data.get("reader") == "ok",
            host=bool(data.get("host")),
            uptime_s=_int(data.get("uptime_s")) or 0,
        )
    if kind == "result":
        return Result(
            id=_int(data.get("id")),
            ok=data.get("ok") is True,
            error=data.get("error") if isinstance(data.get("error"), str) else None,
            detail=data.get("detail") if isinstance(data.get("detail"), str) else None,
            uid=data.get("uid") if isinstance(data.get("uid"), str) else None,
            name=data.get("name") if isinstance(data.get("name"), str) else None,
        )
    if kind == "log":
        return Log(level=str(data.get("level") or "info"), msg=str(data.get("msg") or ""))
    return None


# ---------------------------------------------------------------- commands


def _dump(data: dict[str, Any]) -> str:
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def hello(id: int) -> str:
    return _dump({"type": "hello", "id": id})


def ping(id: int) -> str:
    return _dump({"type": "ping", "id": id})


def write(id: int, name: str, *, uid: str | None = None, timeout_ms: int = 15000) -> str:
    data: dict[str, Any] = {"type": "write", "id": id, "name": name, "timeout_ms": timeout_ms}
    if uid:
        data["uid"] = uid
    return _dump(data)


def show(id: int, lines: list[str], *, uid: str | None = None, ttl_ms: int = 0) -> str:
    data: dict[str, Any] = {"type": "show", "id": id, "lines": [s[:21] for s in lines[:4]]}
    if uid:
        data["uid"] = uid
    if ttl_ms:
        data["ttl_ms"] = ttl_ms
    return _dump(data)


def cancel(id: int) -> str:
    return _dump({"type": "cancel", "id": id})


def config(id: int, **settings: Any) -> str:
    return _dump({"type": "config", "id": id, **settings})


def reboot(id: int) -> str:
    return _dump({"type": "reboot", "id": id})
