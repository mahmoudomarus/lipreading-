import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_export import ExportError, export_mp4


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg is required")
class ExportTests(unittest.TestCase):
    def test_browser_recording_converts_to_h264_aac_and_temp_files_are_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            sample = Path(directory) / "browser.webm"
            subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=blue:s=320x180:r=12",
                    "-f",
                    "lavfi",
                    "-i",
                    "anullsrc=r=24000:cl=mono",
                    "-t",
                    "0.6",
                    "-c:v",
                    "libvpx",
                    "-deadline",
                    "realtime",
                    "-c:a",
                    "libopus",
                    "-y",
                    str(sample),
                ],
                check=True,
                capture_output=True,
            )
            factory = tempfile.TemporaryDirectory
            created = []

            def temporary(**kwargs):
                context = factory(**kwargs)
                created.append(context.name)
                return context

            with patch("video_export.tempfile.TemporaryDirectory", side_effect=temporary):
                result = export_mp4(sample.read_bytes())
            self.assertTrue(all(not Path(path).exists() for path in created))
            self.assertIn(b"ftyp", result[:40])
            target = Path(directory) / "result.mp4"
            target.write_bytes(result)
            metadata = json.loads(
                subprocess.run(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-show_streams",
                        "-show_format",
                        "-of",
                        "json",
                        str(target),
                    ],
                    check=True,
                    capture_output=True,
                ).stdout
            )
            self.assertEqual({s["codec_name"] for s in metadata["streams"]}, {"h264", "aac"})
            self.assertLess(float(metadata["format"]["duration"]), 1.0)

    def test_invalid_recordings_return_a_clean_error(self):
        for data in (b"", b"not a recording"):
            with self.assertRaises(ExportError) as error:
                export_mp4(data)
            self.assertNotIn("/tmp/", str(error.exception))
