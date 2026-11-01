# Security and private data

Lipread Lab is a single-user research prototype, not an audited production service. Do not use uncertain lip predictions as authorization for high-impact actions or expose this backend as a multi-user service without additional isolation and review.

## Data boundaries

- The app token and connected phone link grant access to the computer service. Keep them private. HTTP routes and camera sessions are authenticated.
- Provider credentials stay in process memory and are not returned by configuration endpoints. A new endpoint requires an explicit key; redirects do not forward credentials.
- Camera frames stay in recognition memory unless you choose to record. Studio conversion uses temporary files removed after conversion. Downloaded recordings remain until you remove them.
- Final visual predictions sent with Live replies, reviewed/typed requests, plans/replies, notes, timers and execution receipts are stored in `.runtime/agent.sqlite3`. Recent completed context, including receipts, may be sent to your chosen text provider.
- The HTTPS tunnel relays phone traffic. Provider and tunnel policies apply. Same-computer model endpoints can use loopback HTTP; remote endpoints require HTTPS.
- Logs, private URLs, databases, environment files, user footage and weights are ignored and excluded from source bundles. Review every staged file before publication.

## Operational limits

Use one uvicorn process/worker. Keep the computer and private link under your control. The app has bounded frame/request sizes, serialized camera/model access, a tool allowlist, confirmation for writes and transactional local receipts. These controls do not establish recognition accuracy or make arbitrary future external tools safe.

Disconnecting a provider clears its session key; an already-sent request cannot be recalled. Restarting can reload credentials from the process environment. To remove local personal data, stop the service first, then back up or remove the relevant `.runtime/` files deliberately. Changing an app token also requires reopening/reconnecting private links. Revoke a leaked provider key with its provider.

## Reporting a vulnerability

Use GitHub's **Security → Report a vulnerability** when private reporting is available. Otherwise, ask the maintainer for a private reporting channel without posting exploit details or secrets publicly. Include a minimal reproduction and affected revision, with synthetic data. Ordinary bugs belong in issues after removing all private information.

No response-time or production-support guarantee is offered for this prototype.
