"""Client of the NestrisLTM terminal API (``/api/terminal/v1``)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from nestris_terminal import __version__
from nestris_terminal.config import HostSettings

log = structlog.get_logger(__name__)
PREFIX = "/api/terminal/v1"


class HostError(RuntimeError):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class HostClient:
    def __init__(
        self,
        settings: HostSettings,
        transport: httpx.AsyncBaseTransport | None = None,
        reader_fw: Callable[[], str | None] = lambda: None,
    ) -> None:
        self.settings = settings
        self._reader_fw = reader_fw
        self._client = httpx.AsyncClient(
            base_url=settings.url + PREFIX,
            headers={
                "Authorization": f"Bearer {settings.token.get_secret_value()}",
                # NestrisLTM's device overview (Geräte) shows them.
                "X-Terminal-Version": __version__,
            },
            timeout=settings.timeout_s,
            transport=transport,
            event_hooks={"request": [self._add_reader_header]},
        )
        self.reachable: bool | None = None
        self.last_error: str | None = None
        self.last_ok: datetime | None = None
        self.server: dict[str, Any] | None = None

    async def _add_reader_header(self, request: httpx.Request) -> None:
        fw = self._reader_fw()
        if fw:
            request.headers["X-Reader-Firmware"] = fw

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            self.reachable = False
            self.last_error = f"{type(exc).__name__}: {exc}"
            raise HostError(0, "host not reachable") from exc
        self.reachable = True
        self.last_ok = datetime.now(UTC)
        if response.status_code >= 400:
            detail = response.reason_phrase
            try:
                body = response.json()
                if isinstance(body, dict) and isinstance(body.get("detail"), str):
                    detail = body["detail"]
                elif isinstance(body, dict) and isinstance(body.get("detail"), list):
                    detail = "; ".join(str(d.get("msg", d)) for d in body["detail"])
            except ValueError:
                pass
            if response.status_code in (401, 403):
                self.last_error = f"{response.status_code}: {detail} (check host.token)"
            raise HostError(response.status_code, detail)
        return response

    async def _json(self, method: str, path: str, **kwargs: Any) -> Any:
        return (await self._request(method, path, **kwargs)).json()

    # ------------------------------------------------------------ endpoints

    async def ping(self) -> dict[str, Any]:
        result: dict[str, Any] = await self._json("GET", "/ping")
        self.server = result
        self.last_error = None
        return result

    async def card(self, uid: str, name: str | None) -> dict[str, Any]:
        params = {"name": name} if name else None
        result: dict[str, Any] = await self._json("GET", f"/card/{uid}", params=params)
        return result

    async def link_card(self, uid: str, player_id: int) -> dict[str, Any]:
        result: dict[str, Any] = await self._json(
            "POST", f"/card/{uid}/link", json={"player_id": player_id}
        )
        return result

    async def nickname(self, value: str) -> dict[str, Any]:
        result: dict[str, Any] = await self._json("GET", "/nickname", params={"value": value})
        return result

    async def register(self, data: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = await self._json("POST", "/players", json=data)
        return result

    async def profile(self, player_id: int) -> dict[str, Any]:
        result: dict[str, Any] = await self._json("GET", f"/players/{player_id}")
        return result

    async def self_report(self, player_id: int, data: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = await self._json("POST", f"/players/{player_id}/games", json=data)
        return result

    async def highscore(self) -> dict[str, Any]:
        result: dict[str, Any] = await self._json("GET", "/highscore")
        return result

    async def recording(self, game_id: int) -> tuple[bytes, str]:
        response = await self._request("GET", f"/games/{game_id}/recording")
        return response.content, response.headers.get("X-Recording-Source", "recording")
