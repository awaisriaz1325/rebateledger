"""Object storage adapter (ADR 0009). Keys are tenant-prefixed and random; files are
never served inline — downloads go through an authorised API endpoint."""

from __future__ import annotations

import secrets
import uuid
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO, Protocol

from app.core.config import get_settings


class Storage(Protocol):
    def put(self, key: str, data: BinaryIO) -> int: ...
    def open(self, key: str) -> BinaryIO: ...
    def delete(self, key: str) -> None: ...
    def size(self, key: str) -> int: ...


def new_key(tenant_id: uuid.UUID, kind: str) -> str:
    if not kind.isidentifier():
        raise ValueError("kind must be a simple identifier")
    return f"{tenant_id}/{kind}/{secrets.token_hex(16)}"


class LocalStorage:
    """Development/test storage under RL_STORAGE_DIR (outside any web root)."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("invalid storage key")
        return path

    def put(self, key: str, data: BinaryIO) -> int:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        with path.open("wb") as fh:
            while chunk := data.read(1024 * 1024):
                fh.write(chunk)
                size += len(chunk)
        return size

    def open(self, key: str) -> BinaryIO:
        return self._path(key).open("rb")

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def size(self, key: str) -> int:
        return self._path(key).stat().st_size


@lru_cache(maxsize=1)
def get_storage() -> Storage:
    # GcsStorage is added in Phase 11 behind the same interface.
    return LocalStorage(get_settings().storage_dir)
