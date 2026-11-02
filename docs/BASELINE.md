# Baseline and reproducible measurements

## Branch timing diagnostic

The current runtime at source revision `a909f1b2dbfd76699ee6255512b8d542a21b9b9c` was checked on an Apple M1 with 8 GiB RAM, macOS 27.0.1 arm64 and Python 3.11.11. Recognition used CPU, four threads, live beam 4, phrase beam 12, CTC weight 0.1, trained-LM weight 0.3 and detection caching. PyTorch/vision/audio were 2.11.0 / 0.26.0 / 2.11.0, MediaPipe 1.2.0 and NumPy 2.4.4. Full package versions, source-file fingerprints, pinned vendor revision and all six asset hashes accompany the [per-run report](examples/latency-diagnostic.json).

One reused development clip was replayed over a localhost WebSocket, with no phone, browser, Wi-Fi or tunnel. After a cold smoke and one discarded warmup, ten runs used the same process with no agent workload. Each session sent only JPEGs at 25 FPS, quality 90, maximum edge 800, and explicit Finish at EOF. The last frame was at 2.960 seconds. Results describe delivery at the replay client, not pure model time or articulation-end latency.

| Delivery interval | Median seconds | Nearest-rank p95 seconds | Range seconds |
| --- | --- | --- | --- |
| Capture start to first draft | 2.228 | 4.102 | 1.970 to 4.102 |
| Capture start to final turn | 5.677 | 7.479 | 4.575 to 7.479 |
| Last supplied frame to final turn | 2.717 | 4.519 | 1.615 to 4.519 |

All ten runs produced `THE SUNRISE WOULD BE TOO SOON`; there were no no-output runs or socket errors. With only ten observations, nearest-rank p95 is the maximum and is not a stable population tail estimate. The first cold smoke delivered its first draft at 8.437 s and final at 14.444 s; it is excluded from the table. Capture kind, intended reference and redistribution permission for this preexisting clip are unverified. It is excluded from accuracy scoring and is not redistributed.

The earlier reference deployment had medians of 1.968 s / 4.544 s / 1.584 s at those same boundaries. This branch's observed run was slower. The runs were not alternating paired measurements under controlled machine load, so no causal speedup or slowdown is attributed to the patches. Investigate performance before claiming no unacceptable latency regression. [Accuracy and device limits](../README.md#1-what-it-is).

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
