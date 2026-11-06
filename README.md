# multi-notifier

[![PyPI version](https://img.shields.io/pypi/v/trysac-multi-notifier)](https://pypi.org/project/trysac-multi-notifier/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-multi-notifier)](LICENSE)
[![CI](https://github.com/Trysac/u088-multi-notifier/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u088-multi-notifier/actions/workflows/ci.yml)

Send one notification to ntfy, Telegram and Standard Webhooks endpoints through a typed interface with bounded retries, secret-safe errors and fakes

## Problem

Describe in two or three sentences the concrete problem this utility solves, who hits it, and what
they do today without it. Replace this paragraph when the first real feature lands.

## Install

```sh
pip install trysac-multi-notifier
# or
uv add trysac-multi-notifier
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
import multi_notifier

# normalize() trims surrounding whitespace and lower-cases the text.
print(multi_notifier.normalize("  Hello World "))  # -> "hello world"

# Blank input is rejected explicitly instead of returning an empty string.
try:
    multi_notifier.normalize("   ")
except ValueError as exc:
    print(f"rejected: {exc}")
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) and [decisions](docs/decisions/)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)
- [Changelog](CHANGELOG.md) and [contributing guide](CONTRIBUTING.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
