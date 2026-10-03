from __future__ import annotations

import json

from nestris_terminal.rfid import protocol
from nestris_terminal.rfid.protocol import (
    CardData,
    CardPresent,
    CardRemoved,
    Hello,
    Log,
    Result,
    Status,
)


def test_hello() -> None:
    line = (
        '{"type":"hello","proto":2,"fw":"1.0.0","build":"x","board":"esp32dev","serial":"A4CF",'
        '"display":"128x64","lang":"de","reader":"ok","chip":"0x92",'
        '"card":{"uid":"04a1b2c3","name":"Erv","format":"retroverse"},"id":3}'
    )
    msg = protocol.parse_line(line)
    assert isinstance(msg, Hello)
    assert (msg.proto, msg.fw, msg.display, msg.reader_ok, msg.id) == (
        2,
        "1.0.0",
        "128x64",
        True,
        3,
    )
    assert msg.card == CardData("04A1B2C3", "Erv", "retroverse")
    assert msg.raw["lang"] == "de"


def test_card_events_and_status() -> None:
    present = '{"type":"card","state":"present","uid":"04A1B2C3","name":null,"format":"blank"}'
    assert protocol.parse_line(present) == CardPresent(CardData("04A1B2C3", None, "blank"))
    removed = '{"type":"card","state":"removed","uid":"04a1b2c3"}'
    assert protocol.parse_line(removed) == CardRemoved("04A1B2C3")
    # Unknown formats are treated as unreadable rather than trusted.
    weird = protocol.parse_line('{"type":"card","state":"present","uid":"01020304","format":"x"}')
    assert isinstance(weird, CardPresent) and weird.card.format == "unreadable"
    status = protocol.parse_line(
        '{"type":"status","card":null,"reader":"missing","uptime_s":12,"host":true}'
    )
    assert status == Status(card=None, reader_ok=False, host=True, uptime_s=12)


def test_results_and_logs() -> None:
    ok = '{"type":"result","id":7,"ok":true,"uid":"04A1","name":"Erv"}'
    assert protocol.parse_line(ok) == Result(7, True, uid="04A1", name="Erv")
    failed = '{"type":"result","id":8,"ok":false,"error":"timeout","detail":"no card"}'
    assert protocol.parse_line(failed) == Result(8, False, error="timeout", detail="no card")
    assert protocol.parse_line('{"type":"log","level":"warn","msg":"x"}') == Log("warn", "x")


def test_noise_and_v1_lines_are_ignored() -> None:
    for junk in (
        "",
        "ets Jun  8 2016 00:22:57",  # ESP32 boot ROM
        "{broken",
        "[1,2]",
        '{"type":"login","username":"Erv","uid":"04A1B2C3","source":"rfid"}',  # v1 firmware
        '{"type":"card","state":"present"}',  # no uid
    ):
        assert protocol.parse_line(junk) is None


def test_commands() -> None:
    assert json.loads(protocol.write(5, "Erv", uid="04A1B2C3", timeout_ms=9000)) == {
        "type": "write",
        "id": 5,
        "name": "Erv",
        "timeout_ms": 9000,
        "uid": "04A1B2C3",
    }
    show = json.loads(protocol.show(6, ["Erv", "x" * 30, "3", "4", "5"], ttl_ms=100))
    assert show["lines"] == ["Erv", "x" * 21, "3", "4"] and show["ttl_ms"] == 100
    config = json.loads(protocol.config(7, display="128x64"))
    assert config == {"type": "config", "id": 7, "display": "128x64"}
    for build, kind in (
        (protocol.hello, "hello"),
        (protocol.ping, "ping"),
        (protocol.cancel, "cancel"),
    ):
        assert json.loads(build(1)) == {"type": kind, "id": 1}
