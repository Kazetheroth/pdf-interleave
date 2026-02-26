from __future__ import annotations

import os
from dataclasses import dataclass


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return max(parsed, minimum)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


@dataclass(frozen=True)
class WebSettings:
    max_file_mb: int
    download_ttl_seconds: int
    max_active_jobs: int
    rate_limit_merge_per_min: int
    rate_limit_download_per_min: int
    one_shot_download: bool
    cleanup_interval_seconds: int

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * 1024 * 1024

    @property
    def max_output_bytes(self) -> int:
        # Output is expected to stay around the sum of both inputs.
        return self.max_file_bytes * 2 + (2 * 1024 * 1024)

    @property
    def max_request_bytes(self) -> int:
        # Two files + multipart overhead.
        return self.max_file_bytes * 2 + (2 * 1024 * 1024)

    @property
    def multipart_memory_limit_bytes(self) -> int:
        # Keep multipart uploads in RAM for expected request sizes.
        return self.max_request_bytes


def load_settings() -> WebSettings:
    return WebSettings(
        max_file_mb=_env_int("MAX_FILE_MB", 15),
        download_ttl_seconds=_env_int("DOWNLOAD_TTL_SECONDS", 300),
        max_active_jobs=_env_int("MAX_ACTIVE_JOBS", 20),
        rate_limit_merge_per_min=_env_int("RATE_LIMIT_MERGE_PER_MIN", 10),
        rate_limit_download_per_min=_env_int("RATE_LIMIT_DOWNLOAD_PER_MIN", 30),
        one_shot_download=_env_bool("ONE_SHOT_DOWNLOAD", True),
        cleanup_interval_seconds=_env_int("CLEANUP_INTERVAL_SECONDS", 30),
    )
