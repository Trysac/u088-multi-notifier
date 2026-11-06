# multi-notifier

[![PyPI version](https://img.shields.io/pypi/v/trysac-multi-notifier)](https://pypi.org/project/trysac-multi-notifier/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-multi-notifier)](LICENSE)
[![CI](https://github.com/Trysac/u088-multi-notifier/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u088-multi-notifier/actions/workflows/ci.yml)

Send one notification to ntfy, Telegram and Standard Webhooks endpoints through a typed interface with bounded retries, secret-safe errors and an in-memory fake transport.

## Problem

Small automation scripts each grow their own Telegram or webhook code, with no retries and bot tokens leaking into logs and exception messages. Apprise covers many services but is large and is configured through URL strings that embed secrets. This library offers three HTTP channels, bounded retries, secret-safe errors and an in-memory transport for tests.

## Install

```sh
pip install trysac-multi-notifier
# or
uv add trysac-multi-notifier
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
from multi_notifier import HttpResponse, Notification, Notifier, NtfyChannel
from multi_notifier.testing import FakeTransport

transport = FakeTransport([HttpResponse(200, {}, b"{}")])
notifier = Notifier([NtfyChannel("https://ntfy.sh", "alerts", transport=transport)])
report = notifier.notify(Notification(title="Backup", body="finished", priority="high"))
print(report.ok, report.results[0].attempts)
```

Production code passes real channels (default urllib transport) instead of the fake one: `NtfyChannel(...)`, `TelegramChannel(bot_token, chat_id)`, `WebhookChannel(url, secret="whsec_...")`.

## Public API

- `Notification(title, body, priority='normal', tags=(), url=None)`: frozen dataclass validated at construction. Title 1-250 characters without CR or LF; body at most 65,536 characters; at most 20 tags of 1-64 characters; url must be an absolute https URL.
- `NtfyChannel(server_url, topic, *, token=None, transport=None, allow_insecure=False)`: publishes JSON to the topic; priorities low, normal, high, urgent map to 2, 3, 4, 5.
- `TelegramChannel(bot_token, chat_id, *, transport=None)`: sends plain text (no parse_mode).
- `WebhookChannel(url, *, secret, transport=None, clock=time.time, id_factory=..., allow_insecure=False)`: POSTs JSON signed per the Standard Webhooks specification; `signature(msg_id, timestamp, body)` returns the `v1,` signature.
- `Notifier(channels, *, retries=2, backoff=1.0, max_backoff=30.0, sleep=time.sleep, on_event=None)`: `notify(notification, *, only=None)` returns a `DeliveryReport` with one `ChannelResult` per channel and never raises because a channel failed.
- `HttpTransport` (Protocol), `HttpResponse`, `UrllibTransport`, `multi_notifier.testing.FakeTransport`.
- Errors: `NotifierError` with `code` in `invalid_config`, `invalid_notification`, `channel_failed`; `ChannelError` (code `channel_failed`, `retryable`, `status`, `retry_after`). Messages never contain URLs, tokens or bodies, and are capped at 200 characters.

Limits: Telegram text is cut to 4096 UTF-16 code units ending in U+2026; ntfy message is cut to 4096 UTF-8 bytes without an ellipsis; the default transport times out after 10 s, reads at most 65,536 response bytes and never follows redirects.

Retries: HTTP 429, 5xx and network errors are retried. The delay is `min(max_backoff, backoff * 2**n)`, or a non-negative integer Retry-After (or Telegram `parameters.retry_after`) capped at `max_backoff`.

## Why not Apprise?

Apprise supports many more services, but it is large and configured through URL strings that embed secrets. This library is typed, has no runtime dependencies, keeps secrets out of errors and reprs, and provides deterministic fakes, at the cost of supporting only three channels.

## Security

See [docs/SECURITY.md](docs/SECURITY.md) for the threat model and its limits.

## Documentation

- [Architecture](docs/ARCHITECTURE.md) and [decisions](docs/decisions/)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)
- [Changelog](CHANGELOG.md) and [contributing guide](CONTRIBUTING.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
