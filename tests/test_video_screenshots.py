from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from core.video_screenshots import VideoExtractionError, extract_video_frames_to_zip


class VideoScreenshotsTests(unittest.TestCase):
    def test_extracts_jpegs_into_zip_and_cleans_frame_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            video_path = Path(temp_dir_name) / "sample.mp4"
            video_path.write_bytes(b"video")
            frame_directory: Path | None = None

            def fake_ffmpeg(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
                nonlocal frame_directory
                output_pattern = Path(command[-1])
                frame_directory = output_pattern.parent
                frame_directory.mkdir(parents=True, exist_ok=True)
                for index in range(1, 3):
                    frame_path = frame_directory / f"frame-{index:06d}.jpg"
                    frame_path.write_bytes(b"\xff\xd8fake-jpeg\xff\xd9")
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            with patch(
                "core.video_screenshots.probe_video_duration",
                return_value=2.0,
            ), patch("core.video_screenshots.subprocess.run", side_effect=fake_ffmpeg):
                result = extract_video_frames_to_zip(
                    video_path,
                    interval_seconds=1,
                    max_frames=10,
                    max_duration_seconds=10,
                    max_output_bytes=1_000_000,
                    ffmpeg_binary=sys.executable,
                    ffprobe_binary=sys.executable,
                )

            self.assertEqual(result.frame_count, 2)
            self.assertEqual(result.duration_seconds, 2.0)
            with ZipFile(BytesIO(result.archive_bytes)) as archive:
                self.assertEqual(
                    archive.namelist(),
                    [
                        "screenshots/frame-000001.jpg",
                        "screenshots/frame-000002.jpg",
                    ],
                )
            self.assertIsNotNone(frame_directory)
            self.assertFalse(frame_directory.exists())

    def test_rejects_video_longer_than_configured_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            video_path = Path(temp_dir_name) / "sample.mp4"
            video_path.write_bytes(b"video")

            with patch("core.video_screenshots.probe_video_duration", return_value=11.0), patch(
                "core.video_screenshots.subprocess.run"
            ) as run:
                with self.assertRaisesRegex(VideoExtractionError, "Maximum duration"):
                    extract_video_frames_to_zip(
                        video_path,
                        interval_seconds=1,
                        max_frames=10,
                        max_duration_seconds=10,
                        ffmpeg_binary=sys.executable,
                        ffprobe_binary=sys.executable,
                    )
                run.assert_not_called()

    def test_extracts_requested_precise_timestamps_in_input_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            video_path = Path(temp_dir_name) / "sample.mp4"
            video_path.write_bytes(b"video")
            commands: list[list[str]] = []

            def fake_ffmpeg(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
                commands.append(command)
                frame_path = Path(command[-1])
                frame_path.parent.mkdir(parents=True, exist_ok=True)
                frame_path.write_bytes(b"\xff\xd8fake-jpeg\xff\xd9")
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            timestamps = (1.25, 0.0, 4.5)
            with patch(
                "core.video_screenshots.probe_video_duration",
                return_value=5.0,
            ), patch("core.video_screenshots.subprocess.run", side_effect=fake_ffmpeg):
                result = extract_video_frames_to_zip(
                    video_path,
                    timestamps_seconds=timestamps,
                    max_frames=10,
                    max_duration_seconds=10,
                    ffmpeg_binary=sys.executable,
                    ffprobe_binary=sys.executable,
                )

            self.assertEqual(result.timestamps_seconds, timestamps)
            self.assertEqual([command[command.index("-ss") + 1] for command in commands], ["1.25", "0", "4.5"])
            self.assertEqual(result.frame_count, len(timestamps))

    def test_rejects_non_positive_interval(self) -> None:
        with self.assertRaisesRegex(VideoExtractionError, "interval"):
            extract_video_frames_to_zip(
                Path("does-not-need-to-exist.mp4"),
                interval_seconds=0,
                max_frames=1,
            )


if __name__ == "__main__":
    unittest.main()
