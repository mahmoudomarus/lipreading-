"""Convert an explicitly recorded browser clip to MP4, deleting temporary files."""

import json
import subprocess
import tempfile
from pathlib import Path


class ExportError(ValueError):
    pass


def export_mp4(data):
    if not data or len(data) > 40_000_000:
        raise ExportError("Choose a recording smaller than 40 MB.")
    with tempfile.TemporaryDirectory(prefix="lipread-export-") as directory:
        source = Path(directory) / "input.clip"
        target = Path(directory) / "lipread.mp4"
        source.write_bytes(data)
        try:
            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-protocol_whitelist",
                    "file,pipe",
                    "-show_format",
                    "-show_streams",
                    "-of",
                    "json",
                    str(source),
                ],
                capture_output=True,
                timeout=8,
                check=True,
            )
            metadata = json.loads(probe.stdout)
            try:
                duration = float(metadata.get("format", {}).get("duration", 0))
            except (TypeError, ValueError):
                duration = 0
            videos = [s for s in metadata.get("streams", []) if s.get("codec_type") == "video"]
            # Browser WebM recordings can omit a duration header. ffmpeg's -t
            # still bounds decoding/output when duration is unknown.
            if not videos or duration < 0 or duration > 47:
                raise ExportError("Record a video between 1 and 45 seconds.")
            if max(videos[0].get("width", 0), videos[0].get("height", 0)) > 1920:
                raise ExportError("The recording resolution exceeds the export limit.")
            subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-v",
                    "error",
                    "-protocol_whitelist",
                    "file,pipe",
                    "-i",
                    str(source),
                    "-t",
                    "45",
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a:0?",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "22",
                    "-threads",
                    "2",
                    "-pix_fmt",
                    "yuv420p",
                    "-vf",
                    "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "128k",
                    "-movflags",
                    "+faststart",
                    "-y",
                    str(target),
                ],
                capture_output=True,
                timeout=65,
                check=True,
            )
            if target.stat().st_size > 40_000_000:
                raise ExportError("The converted clip exceeds the export limit.")
            return target.read_bytes()
        except ExportError:
            raise
        except (OSError, subprocess.SubprocessError, ValueError, KeyError):
            raise ExportError(
                "MP4 export could not finish. You can still download the original recording."
            ) from None
