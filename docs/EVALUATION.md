# Evaluate the existing demo

The evaluator is offline tooling around the existing socket, candidate selector and planner. It does not change the live camera UI, enable a model, execute actions, or save provider keys. Run it against an idle service. It opens camera sessions with `conversation: false`, so test mouth movements do not interrupt real jobs. It never calls `/api/agent/jobs` or confirmation endpoints.

## Data and leakage

Use [the example manifest](examples/heldout.example.jsonl). It is a schema example, not real evaluation data. Each row needs a unique `id`, relative video path, `split` (`diagnostic`, `validation`, `heldout`), `speaker`, and `capture_kind` (`silent_mouthing`, `voiced`, `no_speech`, `synthetic`, `unknown`). Validation/heldout require a verified `reference`. Unknown references are `null` and allowed only for diagnostics. Muting a voiced clip does not turn it into genuinely silent mouthing. `expected_silence` is for no intended speech and requires reference `""`.

Record speaker, session/group, consent/provenance and capture conditions. Use speakers and sentences absent from tuning. Include real silent mouthing, natural no-speech, unrelated facial movements, clear and poor framing, names, numbers and negations. Do not tune against the held-out report. The evaluator rejects overlap of speakers, normalized sentences and exact video hashes between validation and heldout when supplied together or via `--validation-manifest`.

Each run hashes the exact videos. `context` is a fixed string for optional candidate selection; `agent_context` is the existing planner's request/reply/receipt conversation list. Both must be available before inference, identical across comparisons and independent of the reference. Capture requests contain only JPEGs, timestamps, auth and mode/control fields. References, expected actions and review annotations stay in the evaluator. Context selection is optional and limited to the existing candidates; it sees no images and is not verification.

## Commands

```sh
# Baseline first: unchanged full demo, current settings, no optional experiment.
.venv/bin/python scripts/evaluate.py evaluation-data/heldout.jsonl \
  --validation-manifest evaluation-data/validation.jsonl \
  --report .runtime/baseline.json

# Natural endpointing: videos must include an actually recorded pause at the end.
# After EOF wait 6 seconds for pending work, then Finish for cleanup only.
# Outputs arriving after cleanup Finish are excluded from natural scores.
.venv/bin/python scripts/evaluate.py evaluation-data/heldout.jsonl \
  --endpoint natural --report .runtime/natural-baseline.json

# One optional change, in a separate service/worktree, identical capture settings.
# --token-file must belong to that separate service.
.venv/bin/python scripts/evaluate.py evaluation-data/heldout.jsonl \
  --server http://127.0.0.1:8766 --token-file path/to/experiment/.runtime/access-token \
  --compare .runtime/baseline.json --report .runtime/one-change.json

# Existing selector ablation on the SAME final candidates and fixed context.
.venv/bin/python scripts/evaluate.py evaluation-data/heldout.jsonl \
  --assist --report .runtime/existing-selector.json

# Optional command-intent evaluation: reuse existing prompt/schema/validator;
# no job database or tools are opened/executed. Matching provider env required.
.venv/bin/python scripts/evaluate.py evaluation-data/heldout.jsonl \
  --plan-intents --report .runtime/intent-baseline.json
```

`--plan-intents` compares tool names and only the annotated argument fields in `expected_actions`; e.g. timer seconds or note text. An expected empty action list tests unwanted commands. It evaluates the dry-run plan, not confirmation/execution correctness. Omitted commands are errors when a nonempty plan was expected; a held reading remains marked as held in the report. If the key exists only in the running service's memory, configure the matching provider in the evaluator environment or leave intent error rate unmeasured. The evaluator does not extract that key or change the live provider. This mode uses the exact existing `agent.INSTRUCTIONS`, schema, validator and explicit preexisting conversation context.

## Metrics and caveats

- Corpus WER uses word-level substitutions, deletions and insertions, with case/punctuation normalization; it can exceed 100%. No-output labeled speech counts as deletions. Unknown references do not become zero-error observations. Synthetic controls are not representative speech accuracy.
- Visual turns replace their native decoder chunks, matching the current UI; chunks are retained in raw events for inspection and never double counted. Fallback mode scores finalized result events. All readings, including held text, are included in raw WER; `accepted` and `auto_send_count` separately record eligibility for dispatch. The evaluator itself never dispatches them.
- Accepted-reading accuracy is **whole-clip exact transcript match among fully accepted labeled clips**. Clarification frequency is labeled clips with a hold or no final output, not a confidence score. For these metrics use one intended request per clip. Review no-output and held cases separately; missing endpointing is not proof of no speech. Negative controls separately count caption activations and any automatic-send eligibility.
- `critical_spans` marks actual reference names/numbers/negations. Exact occurrence-count changes are a diagnostic proxy; they are not automatic semantic judgments. To count reviewed meaning-changing errors, provide `--annotations path.jsonl` with `id`, the exact `prediction`, `meaning_change` boolean and reviewer `note`. Counts remain null without annotations. Review insertion of negations and changed intent even if not caught by a reference span.
- Latency includes first draft, final from capture start, final minus last supplied frame, and (if a human annotated `speech_end_seconds`) final minus actual articulation end. Postroll can make final-minus-last-frame negative; it is not clamped. Local replay excludes a phone's Wi-Fi/camera scheduling. These are text-delivery measurements; dry planner/assist timings are separate. End-to-end agent-answer latency is not inferred from them.
- `--assist` records an additional side-by-side selection result and its added latency without altering the main baseline prediction. It skips held or single-candidate finals. Single-part turns retain native alternatives; multi-part turns vary the last part only. A skipped single-candidate call provides no evidence about selector quality. A decoder-chunk probe is a distinct diagnostic, not the automatic UI path.
- `--compare` rejects changed IDs, video bytes, references, inference context, annotations defining critical spans/actions, or capture settings. It lists every previously correct → wrong clip as well as wrong → correct. This is a guard against invalid comparisons, not an automatic promotion decision. Keep environment/checkpoint fingerprints and counterbalance repeated run order to avoid warmup/load bias.

Do not report a fitted threshold as calibrated without separate validation and held-out evidence. Keep experimental defaults unchanged until paired evaluation supports promotion. [Current audit, baseline and rollback](BASELINE.md).
