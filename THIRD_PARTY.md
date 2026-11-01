# Third-party software and weights

The MIT license at this repository root covers this project's original adapter, harness, interface, and scripts. It does not replace upstream licenses or model/data terms.

- [Chaplin](https://github.com/amanvirparhar/chaplin), Amanvir Parhar, pinned commit `7aee1f8fca776ce4f63690063310b53573b7d804`, MIT. Its checkout contains the complete license and upstream notices. `scripts/setup.py` downloads it separately; source bundles exclude it.
- [Auto-AVSR](https://github.com/mpc001/auto_avsr), Pingchuan Ma and collaborators, contains Apache 2.0 code and notices within the vendored pipeline. Preserve all file-level notices and the upstream license if redistributing modified upstream code.
- [Visual checkpoint](https://huggingface.co/Amanvir/LRS3_V_WER19.1) and [language decoder](https://huggingface.co/Amanvir/lm_en_subword): downloaded separately, not included in our source archive. Review model cards and originating training-data terms before redistribution or commercial use. A permissive wrapper license is not a blanket license for weights or datasets.
- [MediaPipe](https://github.com/google-ai-edge/mediapipe) and its BlazeFace detector: downloaded/installed separately; upstream code/model notices apply.
- FastAPI, Starlette, uvicorn, httpx, websockets, PyTorch, torchvision, torchaudio, OpenCV, NumPy, Pillow, scikit-image, SentencePiece, PyAV, and qrcode retain their individual licenses. FFmpeg is an external executable; build-dependent LGPL/GPL terms apply if you redistribute it.

No training videos, user footage, credentials, or model weights are shipped in the source bundle.
