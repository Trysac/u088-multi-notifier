"""Behavior tests for the public API of multi_notifier."""

from __future__ import annotations

import pytest

import multi_notifier


def test_normalize_trims_and_lowercases() -> None:
    assert multi_notifier.normalize("  Hello World ") == "hello world"


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_normalize_rejects_blank_input(value: str) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        multi_notifier.normalize(value)


def test_version_is_semver() -> None:
    parts = multi_notifier.__version__.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)
