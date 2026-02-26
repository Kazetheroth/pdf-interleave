from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class StoredPdf:
    bytes: bytes
    created_at: float
    expires_at: float
    filename: str
    size: int


class StoreFullError(RuntimeError):
    """Raised when RAM store reached capacity."""


class RamTokenStore:
    def __init__(self, *, max_entries: int) -> None:
        self._max_entries = max_entries
        self._entries: dict[str, StoredPdf] = {}
        self._lock = threading.Lock()

    def put(self, *, pdf_bytes: bytes, filename: str, ttl_seconds: int) -> tuple[str, StoredPdf]:
        now = time.time()
        with self._lock:
            self._purge_expired_locked(now)
            if len(self._entries) >= self._max_entries:
                raise StoreFullError("Too many active jobs. Try again later.")

            token = self._generate_unique_token_locked()
            entry = StoredPdf(
                bytes=pdf_bytes,
                created_at=now,
                expires_at=now + ttl_seconds,
                filename=filename,
                size=len(pdf_bytes),
            )
            self._entries[token] = entry
            return token, entry

    def get_valid(self, token: str) -> StoredPdf | None:
        now = time.time()
        with self._lock:
            self._purge_expired_locked(now)
            return self._entries.get(token)

    def pop_valid(self, token: str) -> StoredPdf | None:
        now = time.time()
        with self._lock:
            self._purge_expired_locked(now)
            return self._entries.pop(token, None)

    def delete(self, token: str) -> bool:
        with self._lock:
            return self._entries.pop(token, None) is not None

    def purge_expired(self) -> int:
        now = time.time()
        with self._lock:
            before = len(self._entries)
            self._purge_expired_locked(now)
            return before - len(self._entries)

    def active_count(self) -> int:
        now = time.time()
        with self._lock:
            self._purge_expired_locked(now)
            return len(self._entries)

    def _purge_expired_locked(self, now: float) -> None:
        expired_tokens = [token for token, entry in self._entries.items() if entry.expires_at <= now]
        for token in expired_tokens:
            self._entries.pop(token, None)

    def _generate_unique_token_locked(self) -> str:
        while True:
            token = secrets.token_urlsafe(32)
            if token not in self._entries:
                return token
