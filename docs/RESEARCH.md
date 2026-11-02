# Recognition research references

The implemented system uses windowed Auto-AVSR inference, a trained decoder language model and an optional candidate selector. Work starts with the [current baseline](BASELINE.md), [recorded errors](RECORDING.md) and [paired evaluation](EVALUATION.md). Investigate crop, tracking, lighting and endpoint failures separately from visually ambiguous words.

## Primary projects and papers

- [Auto-AVSR](https://github.com/mpc001/auto_avsr) and [Chaplin](https://github.com/amanvirparhar/chaplin): the recognition code and inference pipeline used by the adapter.
- [TorchAudio AVSR recipes](https://github.com/pytorch/audio/blob/main/examples/avsr/README.md): a research reference for online visual and audio-visual modeling. The application has no validated replacement checkpoint from that recipe.
- [LipLearner paper](https://arxiv.org/abs/2302.05907) and [authors' code](https://github.com/rkmtlab/LipLearner): research on personalized silent commands. No such classifier is implemented here.
- [VALLR](https://arxiv.org/abs/2503.21408): research on visual speech and language modeling. Any adaptation needs the same held-out comparison as other changes.

## Experimental method

Collect observed reference/prediction pairs before building a homophene map or changing decoding. Prioritize frequent errors and meaning-changing names, numbers and negations. Candidate oracle WER can reveal whether the correct reading already exists in the beam. Evaluate the existing selector before adding another layer. Model plausibility and self-reported confidence are not independent visual verification.

Calibrate any acceptance thresholds on validation clips only, then measure accepted-reading accuracy versus clarification on excluded speakers and sentences. Preserve the full working demo as the main baseline. [Limitations](../README.md#1-what-it-is) are maintained centrally.
