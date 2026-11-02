# Model and component provenance

The original work is the camera transport, inference adapter, window/turn scheduling, guards, UI, evaluator and bounded agent. Recognition weights and trained decoding come from upstream. No model was trained for this project and no upstream benchmark is a measured phone or silent-mouthing result here.

## Required code and assets

The exact inference tree is [Chaplin at 7aee1f8fca776ce4f63690063310b53573b7d804](https://github.com/amanvirparhar/chaplin/tree/7aee1f8fca776ce4f63690063310b53573b7d804). It contains Auto-AVSR/ESPnet-derived pipeline code. Chaplin's wrapper license is MIT; file-level Auto-AVSR notices identify Apache 2.0. A separate Auto-AVSR upstream commit is not tracked by that checkout; use the pinned Chaplin tree as the reproducible code boundary.

| Asset | Role and requirement | Bytes | SHA256 and source |
| --- | --- | --- | --- |
| `vsr.pth` | Required visual recognition weights | 1,001,908,942 | `e740cef369abeabd0ba2c18e37a0661342e1d94d432d6caa77755a11821d8fe3` · [download](https://huggingface.co/Amanvir/LRS3_V_WER19.1/resolve/main/model.pth) |
| `vsr.json` | Required visual architecture/token config | 5,512 | `e062e8c58579f54cb51087e639e674781189809905db4162efe0fe1325356d4f` · [download](https://huggingface.co/Amanvir/LRS3_V_WER19.1/resolve/main/model.json) |
| `lm.pth` | Required trained subword beam-decoder weights | 215,076,928 | `c75aa39020dec98f432c8689b145d3f4cc407d4daa90a0c64202386c34f83c18` · [download](https://huggingface.co/Amanvir/lm_en_subword/resolve/main/model.pth) |
| `lm.json` | Required decoder architecture config | 951 | `6e2d2004e4066af3e5a3d74c53b0d648fd53904da07178671d1cbe28a206d548` · [download](https://huggingface.co/Amanvir/lm_en_subword/resolve/main/model.json) |
| `face_detector.tflite` | Required BlazeFace short-range float16 detector | 229,746 | `b4578f35940bf5a1a655214a1cce5cab13eba73c1297cd78e1a04c2380b0152f` · [download](https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/blaze_face_short_range.tflite) |
| `face_landmarker.task` | Optional to start the backend; required for visual pause endpoints; installed by default | 3,758,596 | `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff` · [download](https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task) |

Setup verifies content hashes, including for upstream `main` or `latest` URLs. The six assets total 1,220,980,675 bytes. Parameter counts for these exact artifacts have not been independently verified; file size is not a parameter count. The MediaPipe task bundle contains several component networks.

## Training and license boundaries

| Component | Verified provenance | Code terms | Weight and data terms |
| --- | --- | --- | --- |
| Visual checkpoint `Amanvir/LRS3_V_WER19.1` | [Pinned Chaplin README](https://github.com/amanvirparhar/chaplin/blob/7aee1f8fca776ce4f63690063310b53573b7d804/README.md) identifies an Auto-AVSR model trained on LRS3. Full mixture and exact training recipe are not independently established for this artifact. | Auto-AVSR-derived files carry Apache 2.0 notices | The checkpoint repository has no README/model card or license metadata at inspected HF revision `c0b413f56b164565865a63f00774ee55a9738cc5`; a permissive weight grant is unverified. Review originating dataset terms separately. |
| Decoder `Amanvir/lm_en_subword` | Exact weights/config above; token language prior in beam search. Training corpus is undocumented in the inspected repository. | Vendored decoder files carry their upstream notices | No README/model card or license metadata at inspected HF revision `f4e39b6d0904b2a900c53a2fff0377796c797bdc`; weight/data grants remain unverified. |
| MediaPipe detector and landmarker | Google-published short-range float16 detector and face-landmarker float16 task; [official task description](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker) identifies the bundle's detector, mesh and blendshape components. Exact training corpus/parameter count is unverified here. | MediaPipe code is Apache 2.0; retain upstream notices | Check the linked model cards and downloaded model notices; this project's MIT license does not establish separate asset/data permissions. |

The [Auto-AVSR license statement](https://github.com/mpc001/auto_avsr#license) explicitly distinguishes code from pretrained model/dataset terms. Upstream training provenance is a source attribution, not an independent data audit. Unresolved rights are not permission to redistribute or use weights commercially. Source packages exclude weights, datasets and vendor downloads. See [third-party notices](../THIRD_PARTY.md).

## Optional hosted components

| Component | Exact default/configuration | Role and boundary |
| --- | --- | --- |
| Candidate selector | Uses the configured `AGENT_MODEL`/endpoint | Optional choice of an existing supported candidate. No unconstrained rewriting or independent visual verification. Manual comparison only on assembled turns. |
| Assistant/planner | Responses, `gpt-6.1-sol`, low reasoning effort by default; replaceable through Settings/environment | Receives text and up to four completed earlier tasks, never frames. Provider terms apply. Hosted parameter count/training data and immutable backend revision are unavailable. |
| Research | Included hosted Responses web-search integration | Sends the research question and returns cited results; capability is endpoint-dependent. |
| Generated speech | `AGENT_VOICE_MODEL=gpt-realtime-2.1-mini` by default | Optional text-only output, rejected on transcript mismatch. No microphone input. Provider terms apply. |

Record the exact nonsecret configuration with an experiment. Hosted IDs may be mutable and are not checkpoint hashes. [The baseline report](BASELINE.md) records the local recognizer's environment and assets separately from assistant integration checks.
