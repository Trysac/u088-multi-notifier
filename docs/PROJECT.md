# Project record

## Objective

Send one notification to ntfy, Telegram and Standard Webhooks endpoints through a typed interface with bounded retries, secret-safe errors and an in-memory fake transport. Small automation scripts need to alert a person without each one re-implementing Telegram or webhook code, retries and secret handling.

## Scope

- In scope: the public API documented in [README.md](../README.md): `Notification`, `Notifier`, `NtfyChannel`, `TelegramChannel`, `WebhookChannel`, the `HttpTransport` protocol with `UrllibTransport`, typed errors, and `multi_notifier.testing.FakeTransport`.
- Out of scope: email, receiving messages, interactive buttons, attachments, and asynchronous delivery.

## Timeline

| Date | Event |
|---|---|
| 2026 | Repository created from the factory utility template. |

## Effort metrics

Measured values only; a value that has not been measured stays "pending measurement".

| Metric | Value |
|---|---|
| Tokens (input / output) | 762696 / 98075 |
| Hours (human) | pending measurement |
| Cost (USD) | 1.0055 |

## Factory run u088 (measured from API usage)

| Phase | Model | Batch | Input | Output | Cache write | Cache read | Cost (USD) |
|---|---|---|---|---|---|---|---|
| generation | claude-sonnet-5-5 | yes | 2597 | 79681 | 0 | 4246 | 0.4014 |
| fix-1 | claude-sonnet-5-5 | no | 4 | 496 | 5882 | 24778 | 0.0222 |
| fix-2 | claude-sonnet-5-5 | no | 6 | 550 | 6488 | 40357 | 0.0258 |
| fix-3 | claude-sonnet-5-5 | no | 6 | 757 | 7209 | 41215 | 0.0297 |
| fix-4 | claude-sonnet-5-5 | no | 8 | 1522 | 20303 | 68847 | 0.0729 |
| audit | claude-sonnet-5-5 | no | 14 | 4155 | 47216 | 204249 | 0.1800 |
| fix-1 | claude-sonnet-5-5 | no | 10 | 2761 | 10637 | 79260 | 0.0621 |
| fix-2 | claude-sonnet-5-5 | no | 8 | 1849 | 20633 | 68418 | 0.0769 |
| fix-3 | claude-sonnet-5-5 | no | 8 | 733 | 6494 | 56053 | 0.0292 |
| fix-4 | claude-sonnet-5-5 | no | 6 | 615 | 6760 | 41231 | 0.0272 |
| docs | claude-haiku-5-5 | no | 131375 | 4956 | 0 | 0 | 0.0781 |

Total: $1.0055. Prices: Anthropic list prices.
