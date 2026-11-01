# Contributing

This is an early exploration of silent interfaces. Contributions are welcome, especially experiments that improve measured recognition, setup reliability, provider portability, or device accessibility.

1. Read the [setup guide](docs/SETUP.md), [architecture](docs/ARCHITECTURE.md), and [roadmap](docs/ROADMAP.md).
2. Open an issue for a substantial model change or new external action so the scope and evaluation can be discussed. Small fixes can come directly as pull requests.
3. Fork the repository, work on a branch, and keep changes focused. Preserve upstream license notices.
4. Run the relevant [developer checks](docs/DEVELOPMENT.md). Explain what was tested and what could not be tested.
5. In your PR, state the concrete problem, resulting behavior, verification, and any remaining limitations.

For model/performance changes, provide a reproducible comparison on held-out data, with references withheld from inference. Include silence/unknown examples and disclose warmup, hardware, settings, dataset provenance and split rules. Avoid training/evaluating on the same phrases or reporting language-model fluency as visual accuracy.

For agent/tools/providers, test malformed output, timeouts, duplicate requests, confirmation, and recovery. Draft captions must not trigger writes. A new provider must never inherit another endpoint's key. External tool execution needs a separate idempotency/reconciliation design.

Keep `.runtime/`, `.env`, keys, private links, recordings, databases, model weights and downloaded vendor trees out of commits and issue attachments. Share only footage whose participants explicitly agreed to the proposed use/publication. Use synthetic or deliberately public fixtures when possible. See [security guidance](SECURITY.md).

There is no required paid API account for unit tests. [Good first contributions and larger experiments →](docs/ROADMAP.md)
