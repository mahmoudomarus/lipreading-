# Baseline and reproducible measurements

## Paired timing diagnostic

**No measurable regression on this clip**, using a 15% tolerance for median capture-start-to-final delivery. The branch median was 4.532 seconds versus 4.974 seconds for old code, a ratio of 0.911. This is a local single-clip check, not a claim of general speed improvement, phone performance or recognition accuracy.

Old source was `7512390a0a9483ff612b9d7718c93d1211897c7b`; branch source was `70e01e3b822bfaa7e69c7c88b9089ca41321e102` (later changes add browser pause/resume, direct local links and camera diagnostics; these replay timings describe the recorded source, not a new browser benchmark). Testing followed a Mac restart, on Apple M1 / 8 GiB RAM, macOS 27.0.1 arm64 and Python 3.11.11. CPU recognition used four threads, live beam 4, phrase beam 12, CTC weight 0.1, trained-LM weight 0.3 and detection caching. [The public report](examples/paired-latency.json) includes exact package versions, source/archive hashes, vendor revision, all asset hashes and individual measurements.

Three pairs ran old/new, new/old, then old/new. Each arm started a fresh process, discarded one full-clip warmup and measured two replays: six measured replays per version, twelve total, grouped into three paired blocks. One recognizer ran at a time with empty job stores and the text provider disabled. The same clip and replay client sent camera-only JPEGs at 25 FPS, quality 90, maximum edge 800, over localhost WebSocket. Explicit Finish at EOF completed each replay; the last supplied frame was at 2.960 seconds. There was no phone, browser, Wi-Fi or tunnel in this measurement path.

| Delivery interval | Old median seconds | Branch median seconds | Old p95 seconds | Branch p95 seconds |
| --- | --- | --- | --- | --- |
| Capture start to first draft | 2.098 | 1.956 | 2.237 | 2.133 |
| Capture start to final turn | 4.974 | 4.532 | 5.675 | 5.128 |
| Last supplied frame to final turn | 2.014 | 1.572 | 2.715 | 2.168 |

All twelve measured replays produced `THE SUNRISE WOULD BE TOO SOON`, with no missing outputs or socket errors. With six observations per version, nearest-rank p95 equals the maximum. Startup and discarded warmup measurements are retained separately in the report. The clip's intended reference, capture kind and redistribution consent are unverified; it is excluded from accuracy scoring and is not redistributed.

Load checks targeted at least 70% CPU idle and fewer than 200 swap-in pages per sample. Thirteen of eighteen checks missed that target after five attempts; those blocks/replays continued with the measured load recorded. The measured replays had the following paging totals (16,384 bytes per page):

| During measured replays | Old code | Branch |
| --- | --- | --- |
| Swap-in pages | 840 | 1,072 |
| Swap-out pages | 28,528 | 0 |

Paging and background load limit causal interpretation even after restarting. The result meets the defined per-clip regression bar; it does not establish statistical equivalence or explain earlier noisy timings. [Earlier unpaired measurements](examples/latency-diagnostic.json) remain archived. [Accuracy and device limits](../README.md#1-what-it-is).

## Agent integration diagnostic

The same branch with the configured Responses text model `gpt-6.1-sol` completed a calculator request at 5.000 s while an earlier research request continued to 11.674 s. Both used the production authenticated HTTP path and returned tool receipts. A separate actual research request was cancelled while `researching` and remained cancelled after five seconds. These are single integration observations demonstrating concurrency/cancellation, not a representative agent-latency benchmark. No recognition-to-command accuracy follows from typed requests.

## Reproduce a timing report

Start an idle development service and supply a consented clip:

```sh
.venv/bin/python scripts/measure_latency.py path/to/clip.mp4 \
  --warmup 1 --runs 10 --report .runtime/repeated-latency.json
```

The script records video SHA256, capture settings, status, each measured replay and nearest-rank p95. It ignores audio and keeps warmup out of measured distributions. Use one model process on constrained machines. Record source and checkpoint revisions, hardware, device, load and run order with any report. Alternate baseline and experiment order when comparing configurations; a faster later run alone is not evidence of a speedup.

## Accuracy baseline

| Measure | Current evidence |
| --- | --- |
| Held-out WER on voiced video | Not measured |
| Held-out WER on genuine silent mouthing | Not measured |
| Accepted exact-reading accuracy and clarification | Not measured |
| Meaning-changing and command-intent errors | Not measured |
| Natural no-speech false activations | Not measured |

Use the [recording protocol](RECORDING.md), [example manifest](examples/heldout.example.jsonl) and [evaluation guide](EVALUATION.md). Keep speaker, sentence and inference context separation explicit. A raw prediction is never a reference transcript.

## Default review holds

Native review holds remain blocking through turn assembly and final assessment. This preserves uncertain readings for explicit review and can increase clarification requests even for correctly recognized speech. There is no opt-in flag for retaining a hold. Measure acceptance and clarification on separate validation and held-out clips before changing the underlying thresholds.
