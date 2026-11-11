"""Nextcloud through its WebDAV API (docs.nextcloud.com → Client APIs → WebDAV).

Files live under  {base}/remote.php/dav/files/{user}/{path}.  Auth: Basic with the user's (app) password.
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from urllib.parse import quote, unquote, urlparse

import httpx

from stemchub.config import Settings

_DAV = "{DAV:}"
_PROPFIND_BODY = """<?xml version="1.0"?>
<d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/><d:getetag/><d:getcontentlength/><d:getlastmodified/></d:prop></d:propfind>"""


@dataclass(frozen=True)
class RemoteFile:
    path: str  # relative to the user's root, no leading slash, e.g. "INDUZELL/U3/day05/a.czi"
    is_dir: bool
    etag: str | None
    size: int | None


class NextcloudError(RuntimeError):
    pass


class NextcloudClient:
    def __init__(self, settings: Settings, timeout: float = 60.0):
        self.base = settings.nextcloud_url.rstrip("/")
        self.user = settings.nextcloud_user
        self._dav_root = f"/remote.php/dav/files/{quote(self.user)}/"
        self.client = httpx.Client(auth=(self.user, settings.nextcloud_password), timeout=timeout)

    def close(self) -> None:
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _url(self, path: str) -> str:
        return self.base + self._dav_root + quote(path.strip("/"))

    def _check(self, response: httpx.Response, what: str) -> httpx.Response:
        if response.status_code >= 400:
            raise NextcloudError(f"{what} failed: HTTP {response.status_code}")
        return response

    def status(self) -> dict:
        r = self.client.get(f"{self.base}/status.php")
        return self._check(r, "status").json()

    def list_dir(self, path: str) -> list[RemoteFile]:
        r = self.client.request("PROPFIND", self._url(path) + "/", headers={"Depth": "1"}, content=_PROPFIND_BODY)
        if r.status_code == 404:
            return []
        self._check(r, f"PROPFIND {path}")
        files = []
        for resp in ET.fromstring(r.content).iter(f"{_DAV}response"):
            href = unquote(urlparse(resp.findtext(f"{_DAV}href", "")).path)
            rel = href.split(self._dav_root, 1)[-1].strip("/")
            if rel == path.strip("/"):
                continue  # the folder itself
            prop = resp.find(f"{_DAV}propstat/{_DAV}prop")
            is_dir = prop is not None and prop.find(f"{_DAV}resourcetype/{_DAV}collection") is not None
            etag = prop.findtext(f"{_DAV}getetag") if prop is not None else None
            size = prop.findtext(f"{_DAV}getcontentlength") if prop is not None else None
            files.append(RemoteFile(rel, is_dir, etag.strip('"') if etag else None, int(size) if size else None))
        return files

    def walk(self, path: str, max_depth: int = 4) -> list[RemoteFile]:
        """All files below path (Depth: infinity is often disabled, so we recurse with Depth: 1)."""
        out, todo = [], [(path, 0)]
        while todo:
            current, depth = todo.pop()
            for f in self.list_dir(current):
                if f.is_dir:
                    if depth < max_depth:
                        todo.append((f.path, depth + 1))
                else:
                    out.append(f)
        return out

    def download(self, path: str, target: Path) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        with self.client.stream("GET", self._url(path)) as r:
            self._check(r, f"GET {path}")
            with open(target, "wb") as fh:
                for chunk in r.iter_bytes(1 << 20):
                    fh.write(chunk)
        return target

    def read_text(self, path: str) -> str:
        r = self.client.get(self._url(path))
        return self._check(r, f"GET {path}").content.decode("utf-8-sig", errors="replace")

    def mkdirs(self, path: str) -> None:
        parts = [p for p in path.strip("/").split("/") if p]
        for i in range(1, len(parts) + 1):
            r = self.client.request("MKCOL", self._url("/".join(parts[:i])))
            if r.status_code not in (201, 405):  # 405 = already exists
                self._check(r, f"MKCOL {path}")

    def exists(self, path: str) -> bool:
        r = self.client.request("PROPFIND", self._url(path), headers={"Depth": "0"}, content=_PROPFIND_BODY)
        if r.status_code == 404:
            return False
        self._check(r, f"PROPFIND {path}")
        return True

    def upload(self, path: str, data: bytes | Path | BinaryIO) -> None:
        """PUT a file. Paths and file objects are streamed in 1 MB pieces (confocal stacks can be several GB)."""
        self.mkdirs(str(Path(path).parent).replace("\\", "/"))
        if isinstance(data, bytes):
            self._check(self.client.put(self._url(path), content=data), f"PUT {path}")
            return
        fh = open(data, "rb") if isinstance(data, Path) else data
        try:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(0)
            chunks = iter(lambda: fh.read(1 << 20), b"")
            r = self.client.put(self._url(path), content=chunks, headers={"Content-Length": str(size)})
            self._check(r, f"PUT {path}")
        finally:
            if isinstance(data, Path):
                fh.close()
