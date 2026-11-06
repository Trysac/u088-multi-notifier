# Architecture

## Purpose

`trysac-multi-notifier` (import name `multi_notifier`) is a small, dependency-free Python library that sends one notification to ntfy, Telegram and Standard Webhooks endpoints, with bounded retries, secret-safe errors and an in-memory fake transport.

## Shape

```text
caller code --> multi_notifier (public API in __init__.py)
                    |
                    +-- notifier.py   Notifier: retries, events, DeliveryReport
                    +-- channels.py   NtfyChannel, TelegramChannel, WebhookChannel
                    +-- models.py     Notification, HttpResponse, ChannelResult, DeliveryReport
                    +-- transport.py  HttpTransport protocol, UrllibTransport (default)
                    +-- errors.py     NotifierError, ChannelError
                    +-- testing.py    FakeTransport (deterministic, for tests)
```

- **Public API**: the names listed in `__all__` of `src/multi_notifier/__init__.py`. Anything else is internal.
- **Errors**: typed `NotifierError` and `ChannelError` carrying a stable `code`; messages never include URLs, tokens or bodies.
- **Side effects**: the default `UrllibTransport` performs HTTP POST requests; `Notifier` sleeps between retries through an injectable `sleep` callable. Logging uses `logging.getLogger(__name__)` with a `NullHandler`.

## Decisions

Architecture decisions are recorded in [decisions/](decisions/) as numbered ADRs.
