from __future__ import annotations

import json

from nestris_terminal.rfid import protocol
from nestris_terminal.rfid.protocol import Reading, WriteDone, WriteFailure


def test_login_lines() -> None:
    line = '{"type":"login","username":"Erv","uid":"04a1b2c3","scoreloaded":"0","source":"rfid"}'
    assert protocol.parse_line(line) == Reading("04A1B2C3", "Erv")
    assert protocol.parse_line(
        '{"type":"login","username":"Unbekannt","source":"rfid"}'
    ) == Reading(None, None)
    blank = '{"type":"login","username":"Unbekannt","uid":"0BADCAFE","source":"rfid"}'
    assert protocol.parse_line(blank) == Reading("0BADCAFE", None)


def test_other_lines() -> None:
    assert protocol.parse_line("Write failed: STATUS_TIMEOUT") == WriteFailure(
        "Write failed: STATUS_TIMEOUT"
    )
    assert protocol.parse_line("Auth failed: X") == WriteFailure("Auth failed: X")
    assert protocol.parse_line("Name erfolgreich auf Karte geschrieben.") == WriteDone()
    for junk in ("", "Device start...", "{broken", '{"type":"other"}', "[1,2]"):
        assert protocol.parse_line(junk) is None


def test_commands() -> None:
    assert json.loads(protocol.setname("A" * 30)) == {"type": "setname", "value": "A" * 15}
    assert json.loads(protocol.highscore(159867)) == {"type": "highscore", "value": "159867"}
    cfg = json.loads(
        protocol.wifi_config(ssid="LAN", password="pw", device="t1", ip="10.0.0.2", port=5000)
    )
    assert cfg["type"] == "config" and cfg["ssid"] == "LAN"
