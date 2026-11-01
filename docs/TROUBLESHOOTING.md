# Troubleshooting

| Symptom | Check or next step |
| --- | --- |
| Camera button stays disabled | Wait for model startup; run `scripts/doctor.py`; inspect `.runtime/server.log` locally |
| `cloudflared`, `ffmpeg` or `ffprobe` not found | Install that executable and make it available on the launcher's PATH |
| Phone cannot connect | Keep the computer awake; reopen the newest printed HTTPS link; old tunnel origins stop working after restart |
| Access denied | Use the app connection key/link from this installation, not a provider API key |
| Camera permission missing | Open the HTTPS link in a supported browser, allow camera permission and keep the page visible |
| Port 8765 already in use | Stop this project's detached service or the foreground terminal instance before starting another; do not kill unrelated processes |
| Torch/vision/audio import error | Use matching builds for Python 3.11 and your platform; avoid mixing incompatible CPU/CUDA/Metal environments |
| Model checksum mismatch | Preserve the file; use `setup.py --repair` for a verified replacement. If the remote file also fails verification, investigate upstream changes |
| Vendor revision differs | Preserve local edits; the installer intentionally does not reset an existing checkout |
| Poor captions despite good light | The model can still misread silent speech. Compare held-out clips and framing; do not treat an LLM rewrite as verified transcription |
| Long text delay | Keep phrases short and finish manually; measure capture/encoding/decoding/network stages. The current model is offline/windowed |
| Provider connection rejected | Check protocol, base URL, model ID, quota and key. A new endpoint requires its own explicit key |
| Local model unreachable from the phone | `localhost` in model settings refers to the Python computer. Confirm the model server is listening there |
| Agent plan fails validation | The model did not follow the bounded schema; use a more capable compatible model or add a tested adapter, without bypassing validation |
| Note/timer not created | Open the pending action and confirm it. A proposal is not execution |
| Timer has no phone alarm | Only persisted due times/countdowns are implemented; push notifications are not |
| Camera stops on background/lock | Expected phone browser behavior. Computer jobs continue; camera capture requires the page to stay visible |
| MP4 export fails | Check FFmpeg availability and clip length/size. The original browser recording remains available; verify on the target phone |
| Background service not running after reboot/sleep | It is a detached process, not a login service, and it does not prevent sleep. Start it again and use the new link |

Before opening an issue, include OS, Python/library versions, phone/browser, the command used and a minimal reproduction. Remove access tokens, API keys, private URLs, transcripts, database files and personal footage from any logs or screenshots you share.
