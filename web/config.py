from __future__ import annotations

import math
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


def _env_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        parsed = float(raw)
    except ValueError:
        return default
    if not math.isfinite(parsed):
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
    max_upload_files: int
    download_ttl_seconds: int
    max_active_jobs: int
    rate_limit_merge_per_min: int
    rate_limit_download_per_min: int
    one_shot_download: bool
    cleanup_interval_seconds: int
    max_video_duration_seconds: int = 600
    max_video_frames: int = 120
    max_video_output_mb: int = 100
    video_frame_interval_seconds: float = 1.0
    video_process_timeout_seconds: int = 300
    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * 1024 * 1024

    @property
    def max_output_bytes(self) -> int:
        # Output is expected to stay around the sum of all inputs.
        return self.max_file_bytes * self.max_upload_files + (2 * 1024 * 1024)

    @property
    def max_request_bytes(self) -> int:
        # Uploaded files + multipart overhead.
        return self.max_file_bytes * self.max_upload_files + (2 * 1024 * 1024)

    @property
    def max_video_output_bytes(self) -> int:
        return self.max_video_output_mb * 1024 * 1024

    @property
    def multipart_memory_limit_bytes(self) -> int:
        # Keep multipart uploads in RAM for expected request sizes.
        return self.max_request_bytes


def load_settings() -> WebSettings:
    return WebSettings(
        max_file_mb=_env_int("MAX_FILE_MB", 15),
        max_upload_files=_env_int("MAX_UPLOAD_FILES", 20, minimum=2),
        download_ttl_seconds=_env_int("DOWNLOAD_TTL_SECONDS", 300),
        max_active_jobs=_env_int("MAX_ACTIVE_JOBS", 20),
        rate_limit_merge_per_min=_env_int("RATE_LIMIT_MERGE_PER_MIN", 10),
        rate_limit_download_per_min=_env_int("RATE_LIMIT_DOWNLOAD_PER_MIN", 30),
        one_shot_download=_env_bool("ONE_SHOT_DOWNLOAD", True),
        cleanup_interval_seconds=_env_int("CLEANUP_INTERVAL_SECONDS", 30),
        max_video_duration_seconds=_env_int("MAX_VIDEO_DURATION_SECONDS", 600),
        max_video_frames=_env_int("MAX_VIDEO_FRAMES", 120),
        max_video_output_mb=_env_int("MAX_VIDEO_OUTPUT_MB", 100),
        video_frame_interval_seconds=_env_float("VIDEO_FRAME_INTERVAL_SECONDS", 1.0, minimum=0.001),
        video_process_timeout_seconds=_env_int("VIDEO_PROCESS_TIMEOUT_SECONDS", 300),
        ffmpeg_binary=os.getenv("FFMPEG_BINARY", "ffmpeg"),
        ffprobe_binary=os.getenv("FFPROBE_BINARY", "ffprobe"),
    )
