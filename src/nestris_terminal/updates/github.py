"""The releases of a GitHub repository (unauthenticated by default).

Mirrors ``GitHubReleases`` in nestris-ltm (``services/updates.py``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from nestris_terminal import __version__
from nestris_terminal.updates.releases import Version

MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024
SUMS_FILE = "SHA256SUMS.txt"


class UpdateError(Exception):
    """An update step failed; ``code`` is stable for the UI."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    size: int


@dataclass(frozen=True)
class Release:
    tag: str
    version: Version
    prerelease: bool
    notes: str
    published_at: str | None
    html_url: str
    assets: dict[str, Asset] = field(default_factory=dict)

    def find(self, prefix: str, suffix: str) -> str | None:
        """The asset ``<prefix><version><suffix>``, in either spelling of the
        version (``0.2.0b1`` and ``0.2.0-beta.1`` name the same release)."""
        exact = f"{prefix}{self.version}{suffix}"
        if exact in self.assets:
            return exact
        for name in self.assets:
            if name.startswith(prefix) and name.endswith(suffix):
                found = Version.parse(name.removeprefix(prefix).removesuffix(suffix))
                if found == self.version:
                    return name
        return None

    @property
    def signed(self) -> bool:
        return SUMS_FILE in self.assets and (SUMS_FILE + ".sig") in self.assets

    def summary(self) -> dict[str, Any]:
        return {
            "version": str(self.version),
            "tag": self.tag,
            "prerelease": self.prerelease,
            "published_at": self.published_at,
            "notes": self.notes,
            "url": self.html_url,
        }


class GitHubReleases:
    API = "https://api.github.com"

    def __init__(
        self,
        owner: str,
        repo: str,
        token: str = "",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.owner = owner
        self.repo = repo
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": f"RetroverseTerminal/{__version__}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.AsyncClient(
            headers=headers, transport=transport, timeout=30.0, follow_redirects=True
        )
        self._etag: str | None = None
        self._cached: list[Release] = []

    async def close(self) -> None:
        await self._client.aclose()

    async def list(self) -> list[Release]:
        """Published releases, newest version first (drafts dropped)."""
        headers = {"If-None-Match": self._etag} if self._etag else {}
        r = await self._client.get(
            f"{self.API}/repos/{self.owner}/{self.repo}/releases",
            params={"per_page": 30},
            headers=headers,
        )
        if r.status_code == 304:  # unchanged: does not count against the rate limit
            return self._cached
        if r.status_code == 404:
            raise UpdateError("not_found", f"github.com/{self.owner}/{self.repo} not found")
        if r.status_code == 403 and r.headers.get("x-ratelimit-remaining") == "0":
            raise UpdateError("rate_limited", "GitHub rate limit reached, try again later")
        r.raise_for_status()
        releases = []
        for item in r.json():
            if item.get("draft"):
                continue
            version = Version.parse(str(item.get("tag_name", "")))
            if version is None:
                continue
            assets = {
                a["name"]: Asset(a["name"], a["browser_download_url"], int(a.get("size", 0)))
                for a in item.get("assets", [])
            }
            releases.append(
                Release(
                    tag=item["tag_name"],
                    version=version,
                    prerelease=bool(item.get("prerelease")) or version.is_prerelease,
                    notes=str(item.get("body") or ""),
                    published_at=item.get("published_at"),
                    html_url=str(item.get("html_url") or ""),
                    assets=assets,
                )
            )
        releases.sort(key=lambda rel: rel.version, reverse=True)
        self._etag = r.headers.get("etag")
        self._cached = releases
        return releases

    async def fetch(self, url: str, max_bytes: int = 1024 * 1024) -> bytes:
        r = await self._client.get(url)
        r.raise_for_status()
        if len(r.content) > max_bytes:
            raise UpdateError("too_large", f"{url} is larger than expected")
        return r.content

    async def download(
        self, url: str, dest: Path, progress: Callable[[int, int], None] | None = None
    ) -> Path:
        tmp = dest.with_suffix(dest.suffix + ".part")
        async with self._client.stream("GET", url) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length") or 0)
            done = 0
            with tmp.open("wb") as fh:
                async for chunk in r.aiter_bytes(256 * 1024):
                    done += len(chunk)
                    if done > MAX_DOWNLOAD_BYTES:
                        raise UpdateError("too_large", "download larger than 500 MB")
                    fh.write(chunk)
                    if progress:
                        progress(done, total)
        tmp.replace(dest)
        return dest
