# Channels behind a transport protocol with retries owned by the Notifier

Status: accepted (generated, pending human review)

## Context

Notifications must reach ntfy, Telegram and webhook endpoints reliably without leaking tokens. The Telegram token lives in the request URL, so any exception text from an HTTP library may contain a secret, and tests must not use the network.

## Decision

Each channel performs exactly one send through an injected HttpTransport and raises a ChannelError with a fixed message and a retryable flag. The Notifier owns retry, backoff and event emission. Transport exceptions are swallowed inside the channel and replaced by a ChannelError raised outside the except block, so no cause or context carries the original text. Channels define a repr without secrets or URL paths. The default transport is urllib without redirects and with capped reads, and a FakeTransport provides deterministic tests.

## Consequences

Secret safety is enforced at one boundary per channel and is easy to test. Retry policy is identical for all channels and can be tested with an injected sleep. The cost is that transport diagnostics are intentionally lost, and the webhook message id is regenerated on each attempt because channels are stateless.
