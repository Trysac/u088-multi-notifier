# Security notes

## Threat model

`trysac-multi-notifier` performs outbound HTTPS POST requests through its default transport. It has no inbound surface.

Defended:

- **Secret leakage in errors and reprs**: `repr()` of channels shows only the host (Telegram shows no token). Error messages are short fixed texts without URLs, tokens or bodies. Transport exceptions are replaced by a generic `ChannelError`, not chained, so a URL inside the original exception text is not exposed. `on_event` payloads contain channel, attempt, status, outcome and delay only.
- **Credentials in URLs**: endpoints with embedded credentials (`user@host`) are rejected; ntfy server URLs must not contain query or fragment.
- **Insecure transport**: only https is accepted unless `allow_insecure=True` is passed explicitly.
- **Malformed input**: notification fields are validated (length, control characters, https-only url, tag count); channel configuration is validated, with a 512-character credential cap and a 2048-character endpoint cap.
- **Redirects and response size**: the default transport never follows redirects and reads at most 65,536 response bytes; the request timeout is 10 s.
- **Webhook authenticity**: requests are signed with HMAC-SHA256 following the Standard Webhooks specification.

Not defended:

- The library does not verify TLS certificate pinning or any server identity beyond the standard urllib/ssl defaults.
- Secrets passed as plain strings remain in memory and in the caller's source code; the library does not read secrets from a vault or environment.
- Webhook replay protection is the receiver's responsibility; the library sends a timestamp and a unique id but does not check responses.
- Retries resend the same payload; a server that accepted a request but timed out may receive a duplicate notification.
- Supply chain: mitigated by having no runtime dependencies, Dependabot weekly updates, actions pinned to major versions and minimal workflow permissions; `gitleaks` scans locally and in CI.

To report a vulnerability, see [SECURITY.md](../SECURITY.md).
