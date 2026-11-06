# Usage

`multi_notifier` sends one `Notification` to ntfy, Telegram and Standard Webhooks endpoints
through a typed interface. It has no runtime dependencies.

## Channels

- `NtfyChannel(server_url, topic, *, token=None, transport=None, allow_insecure=False)` uses
  ntfy JSON publishing, so non-ASCII titles need no header encoding. The message is cut to 4096
  UTF-8 bytes at a character boundary.
- `TelegramChannel(bot_token, chat_id, *, transport=None)` posts plain text (no `parse_mode`) to
  `sendMessage`. The text is the title, a blank line, the body and the url line when set, cut to
  4096 UTF-16 code units with U+2026 appended.
- `WebhookChannel(url, *, secret, transport=None, clock=time.time, id_factory=..., allow_insecure=False)`
  follows Standard Webhooks: headers `webhook-id`, `webhook-timestamp` and `webhook-signature`
  (`v1,` plus base64 of HMAC-SHA256 over `id.timestamp.body`). The secret is `whsec_` followed by
  the base64 key. The message id comes from `id_factory` on every attempt.

## Retries

`Notifier(channels, retries=2, backoff=1.0, max_backoff=30.0)` retries HTTP 429, 5xx and network
errors. The delay is `min(max_backoff, backoff * 2**attempt)`, or the `Retry-After` header when it
is a non-negative integer of seconds (Telegram `parameters.retry_after` is also honoured), capped
at `max_backoff`. `notify` never raises because a channel failed; inspect the `DeliveryReport`.

## Secret handling

Tokens, secrets and URLs are never part of `repr()`, error messages, reports or `on_event`
payloads. Transport exceptions are replaced by a fixed `ChannelError` message and are not chained,
because the Telegram token is part of the request URL. `on_event` payloads only carry `channel`,
`attempt`, `status`, `outcome` and `delay`.

## Testing

```python
from multi_notifier import HttpResponse
from multi_notifier.testing import FakeTransport

transport = FakeTransport([HttpResponse(503), HttpResponse(200)])
```

The default transport uses urllib with a 10 second timeout, reads at most 65,536 response bytes
and never follows redirects.
