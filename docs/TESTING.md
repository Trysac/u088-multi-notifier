# Testing

## Running

```sh
uv run pytest --cov=multi_notifier   # tests with coverage report
uv run python scripts/check.py      # every gate, as CI runs it
```

## Policy

- Branch coverage of `src/multi_notifier` must stay at or above 80 %; the gate fails below it.
- Tests exercise the public API (`import multi_notifier`) and assert observable effects: return values, raised exceptions and their codes and messages.
- Tests are deterministic: they use `FakeTransport`, an injected `sleep` and an injected `clock`; no network and no wall clock.

## Layout

Tests live under `tests/`, one file per public module (`tests/test_<module>.py`). Shared fixtures go in `tests/conftest.py`.

Behaviour covered by the specification's acceptance criteria includes: report ordering and `ok` semantics; retry counts and sleep sequence (503, 503, 200 with retries=2 gives 3 attempts and sleeps 1.0 and 2.0); Retry-After handling; secret absence from reprs, errors and events; the Standard Webhooks signature test vector; notification and URL validation; Telegram and ntfy truncation; and the ntfy JSON payload and priority mapping.
