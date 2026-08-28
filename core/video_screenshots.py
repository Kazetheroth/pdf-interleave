from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Sequence
from zipfile import ZIP_DEFLATED, ZipFile


class VideoExtractionError(ValueError):
    """Raised when a video cannot be inspected or converted to screenshots."""


@dataclass(frozen=True)
class VideoScreenshotsResult:
    """The temporary extraction result returned to the web adapter."""

    archive_bytes: bytes
    frame_count: int
    duration_seconds: float
    timestamps_seconds: tuple[float, ...] = ()


def extract_video_frames_to_zip(
    video_path: Path,
    *,
    interval_seconds: float | None = None,
    timestamps_seconds: Sequence[float] | None = None,
    max_frames: int,
    max_duration_seconds: float | None = None,
    max_output_bytes: int | None = None,
    ffmpeg_binary: str = "ffmpeg",
    ffprobe_binary: str = "ffprobe",
    timeout_seconds: int = 300,
) -> VideoScreenshotsResult:
    """Extract JPEG frames at precise times or a regular interval.

    The input and individual extracted frames are kept in temporary storage by
    this function. They are removed before it returns, leaving only the ZIP
    bytes in memory for the caller to store or send to a client.
    """

    _validate_options(
        interval_seconds=interval_seconds,
        timestamps_seconds=timestamps_seconds,
        max_frames=max_frames,
        max_duration_seconds=max_duration_seconds,
        max_output_bytes=max_output_bytes,
        timeout_seconds=timeout_seconds,
    )

    video_path = Path(video_path)
    if not video_path.is_file():
        raise VideoExtractionError(f"Video file not found: {video_path}")

    duration_seconds = probe_video_duration(
        video_path,
        ffprobe_binary=ffprobe_binary,
        timeout_seconds=timeout_seconds,
    )
    if max_duration_seconds is not None and duration_seconds > max_duration_seconds:
        raise VideoExtractionError(
            "Video is too long. "
            f"Maximum duration is {_format_seconds(max_duration_seconds)} seconds."
        )

    ffmpeg_command = _resolve_binary(ffmpeg_binary, label="ffmpeg")
    timestamps = _normalise_timestamps(timestamps_seconds)
    if timestamps is not None:
        if len(timestamps) > max_frames:
            raise VideoExtractionError(
                f"At most {max_frames} screenshots can be requested in one batch."
            )
        for timestamp in timestamps:
            if timestamp >= duration_seconds and duration_seconds > 0:
                raise VideoExtractionError(
                    "Screenshot time "
                    f"{_format_seconds(timestamp)} seconds is outside the video duration "
                    f"({_format_seconds(duration_seconds)} seconds)."
                )
    else:
        # _validate_options guarantees that interval_seconds is present in this
        # branch, but keeping this guard makes the type contract explicit.
        if interval_seconds is None:
            raise VideoExtractionError("Screenshot interval is required when no timestamps are supplied.")
        interval = _format_seconds(interval_seconds)

    interval_value = interval_seconds
    if interval_value is None:
        interval_value = 0.0

    with tempfile.TemporaryDirectory(prefix="pdf-interleave-video-frames-") as frame_dir_name:
        frame_dir = Path(frame_dir_name)
        if timestamps is not None:
            frame_paths = _extract_at_timestamps(
                video_path,
                frame_dir=frame_dir,
                timestamps=timestamps,
                ffmpeg_command=ffmpeg_command,
                timeout_seconds=timeout_seconds,
            )
        else:
            frame_paths = _extract_at_interval(
                video_path,
                frame_dir=frame_dir,
                interval=interval,
                max_frames=max_frames,
                ffmpeg_command=ffmpeg_command,
                timeout_seconds=timeout_seconds,
            )

        archive_bytes = _zip_frames(
            frame_paths,
            max_output_bytes=max_output_bytes,
        )
        return VideoScreenshotsResult(
            archive_bytes=archive_bytes,
            frame_count=len(frame_paths),
            duration_seconds=duration_seconds,
            timestamps_seconds=(
                tuple(timestamps)
                if timestamps is not None
                else tuple((index - 1) * interval_value for index in range(1, len(frame_paths) + 1))
            ),
        )


def probe_video_duration(
    video_path: Path,
    *,
    ffprobe_binary: str = "ffprobe",
    timeout_seconds: int = 60,
) -> float:
    """Return the duration of the first video stream in seconds."""

    _validate_timeout(timeout_seconds)
    probe_command = _resolve_binary(ffprobe_binary, label="ffprobe")
    command = [
        probe_command,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "format=duration:stream=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]

    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise VideoExtractionError("The ffprobe executable is not available on the server.") from exc
    except subprocess.TimeoutExpired as exc:
        raise VideoExtractionError("Reading the video metadata took too long and was stopped.") from exc
    except subprocess.CalledProcessError as exc:
        detail = _last_error_line(exc.stderr)
        suffix = f" {detail}" if detail else ""
        raise VideoExtractionError(f"The uploaded file is not a readable video.{suffix}") from exc

    durations: list[float] = []
    for raw_value in completed.stdout.splitlines():
        try:
            value = float(raw_value.strip())
        except ValueError:
            continue
        if math.isfinite(value) and value >= 0:
            durations.append(value)

    if not durations:
        raise VideoExtractionError("The video duration could not be determined.")
    return max(durations)


def _extract_at_interval(
    video_path: Path,
    *,
    frame_dir: Path,
    interval: str,
    max_frames: int,
    ffmpeg_command: str,
    timeout_seconds: int,
) -> list[Path]:
    output_pattern = frame_dir / "frame-%06d.jpg"
    command = [
        ffmpeg_command,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-i",
        str(video_path),
        "-map",
        "0:v:0",
        "-vf",
        f"fps=1/{interval}",
        "-frames:v",
        str(max_frames),
        "-q:v",
        "2",
        str(output_pattern),
    ]
    completed = _run_ffmpeg(command, timeout_seconds=timeout_seconds)
    frame_paths = sorted(frame_dir.glob("frame-*.jpg"))
    if not frame_paths:
        detail = _last_error_line(completed.stderr)
        suffix = f" {detail}" if detail else ""
        raise VideoExtractionError(f"No video frames were found.{suffix}")
    return frame_paths


def _extract_at_timestamps(
    video_path: Path,
    *,
    frame_dir: Path,
    timestamps: Sequence[float],
    ffmpeg_command: str,
    timeout_seconds: int,
) -> list[Path]:
    frame_paths: list[Path] = []
    for index, timestamp in enumerate(timestamps, start=1):
        frame_path = frame_dir / f"frame-{index:06d}.jpg"
        command = [
            ffmpeg_command,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-ss",
            _format_seconds(timestamp),
            "-i",
            str(video_path),
            "-map",
            "0:v:0",
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(frame_path),
        ]
        _run_ffmpeg(
            command,
            timeout_seconds=timeout_seconds,
            error_message=(
                "ffmpeg could not extract screenshot at "
                f"{_format_seconds(timestamp)} seconds."
            ),
        )
        if not frame_path.is_file() or frame_path.stat().st_size == 0:
            raise VideoExtractionError(
                "No video frame was found at "
                f"{_format_seconds(timestamp)} seconds."
            )
        frame_paths.append(frame_path)
    return frame_paths


def _run_ffmpeg(
    command: list[str],
    *,
    timeout_seconds: int,
    error_message: str = "ffmpeg could not extract screenshots.",
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        # This is also handled by _resolve_binary in normal operation. Keep
        # this branch for a binary that disappears between lookup and run.
        raise VideoExtractionError("The ffmpeg executable is not available on the server.") from exc
    except subprocess.TimeoutExpired as exc:
        raise VideoExtractionError("Video processing took too long and was stopped.") from exc
    except subprocess.CalledProcessError as exc:
        detail = _last_error_line(exc.stderr)
        suffix = f" {detail}" if detail else ""
        raise VideoExtractionError(f"{error_message}{suffix}") from exc
    return completed


def _zip_frames(frame_paths: list[Path], *, max_output_bytes: int | None) -> bytes:
    archive = BytesIO()
    try:
        with ZipFile(archive, mode="w", compression=ZIP_DEFLATED, compresslevel=6) as zip_file:
            for frame_path in frame_paths:
                try:
                    frame_bytes = frame_path.read_bytes()
                except OSError as exc:
                    raise VideoExtractionError("A generated screenshot could not be read.") from exc

                zip_file.writestr(f"screenshots/{frame_path.name}", frame_bytes)
                if max_output_bytes is not None and archive.tell() > max_output_bytes:
                    raise VideoExtractionError("The generated screenshots archive is too large.")
    except OSError as exc:
        raise VideoExtractionError("The screenshots archive could not be created.") from exc

    archive_bytes = archive.getvalue()
    if max_output_bytes is not None and len(archive_bytes) > max_output_bytes:
        raise VideoExtractionError("The generated screenshots archive is too large.")
    return archive_bytes


def _validate_options(
    *,
    interval_seconds: float | None,
    timestamps_seconds: Sequence[float] | None,
    max_frames: int,
    max_duration_seconds: float | None,
    max_output_bytes: int | None,
    timeout_seconds: int,
) -> None:
    if interval_seconds is not None and (
        not math.isfinite(interval_seconds) or interval_seconds <= 0
    ):
        raise VideoExtractionError("Screenshot interval must be greater than 0 seconds.")
    if interval_seconds is None and timestamps_seconds is None:
        raise VideoExtractionError("Screenshot interval or precise timestamps are required.")
    if timestamps_seconds is not None and len(timestamps_seconds) < 1:
        raise VideoExtractionError("At least one precise timestamp is required.")
    if timestamps_seconds is not None:
        _normalise_timestamps(timestamps_seconds)
    if max_frames < 1:
        raise VideoExtractionError("Maximum screenshot count must be at least 1.")
    if max_duration_seconds is not None and (
        not math.isfinite(max_duration_seconds) or max_duration_seconds <= 0
    ):
        raise VideoExtractionError("Maximum video duration must be greater than 0 seconds.")
    if max_output_bytes is not None and max_output_bytes < 1:
        raise VideoExtractionError("Maximum screenshots archive size must be greater than 0 bytes.")
    _validate_timeout(timeout_seconds)


def _normalise_timestamps(timestamps: Sequence[float] | None) -> tuple[float, ...] | None:
    if timestamps is None:
        return None

    normalised: list[float] = []
    for timestamp in timestamps:
        if not math.isfinite(timestamp) or timestamp < 0:
            raise VideoExtractionError("Screenshot times must be finite and at least 0 seconds.")
        normalised.append(float(timestamp))

    if len(set(normalised)) != len(normalised):
        raise VideoExtractionError("Screenshot times must not contain duplicates.")
    return tuple(normalised)


def _validate_timeout(timeout_seconds: int) -> None:
    if timeout_seconds < 1:
        raise VideoExtractionError("Video processing timeout must be at least 1 second.")


def _resolve_binary(binary: str, *, label: str) -> str:
    resolved = shutil.which(binary)
    if resolved is None:
        raise VideoExtractionError(f"The {label} executable is not available on the server.")
    return resolved


def _format_seconds(value: float) -> str:
    return format(value, ".12g")


def _last_error_line(stderr: str | bytes | None) -> str:
    if not stderr:
        return ""
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    return lines[-1] if lines else ""
