# Baseline and reproducible measurements

## Reference timing diagnostic

One previously used development clip was replayed through the reference deployment after one discarded warmup, followed by ten measured runs. Capture used the production JPEG socket in live mode, explicit Finish at EOF, 25 FPS source timing, quality 90 and an 800 pixel maximum edge. Recognition used CPU, four threads, fast beam 4, detailed beam 12, CTC weight 0.1 and language-model weight 0.3. Each replay began a fresh camera session and submitted no agent jobs.

| Delivery interval | Median seconds | p95 seconds | Range seconds |
| --- | --- | --- | --- |
| Capture start to first draft | 1.968 | 2.224 | 1.823–2.224 |
| Capture start to final turn | 4.544 | 5.673 | 4.310–5.673 |
| Last captured frame to final turn | 1.584 | 2.713 | 1.350–2.713 |

The last supplied frame was at 2.960 seconds. The output was the same across all measured runs. [Per-run timings, clip hash and configuration](examples/latency-diagnostic.json) distinguish this reference diagnostic from future experiments. These numbers do not benchmark the refactored session implementation or a physical phone connection. The source clip has no verified transcript; its development reuse excludes it from held-out accuracy evaluation. [Project limitations](../README.md#limitations).

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
