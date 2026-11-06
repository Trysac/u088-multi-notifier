"""Typed errors raised by multi_notifier."""

from __future__ import annotations

from typing import Literal

__all__ = ["ChannelError", "ErrorCode", "NotifierError"]

ErrorCode = Literal["invalid_config", "invalid_notification", "channel_failed"]

_MAX_MESSAGE = 200


class NotifierError(Exception):
    """Base class of every error raised by the library.

    Messages never contain URLs, tokens or message bodies and are capped at 200 characters.

    Attributes:
        code: Stable machine-readable error code.
        message: Short human readable description.
    """

    def __init__(self, code: ErrorCode, message: str) -> None:
        """Create the error with a stable ``code`` and a short ``message``."""
        text = message[:_MAX_MESSAGE]
        super().__init__(text)
        self.code: ErrorCode = code
        self.message: str = text


class ChannelError(NotifierError):
    """A channel failed to deliver a notification.

    Attributes:
        retryable: True when another attempt may succeed (HTTP 429, 5xx, network errors).
        status: HTTP status code when the server answered, otherwise None.
        retry_after: Server supplied delay in seconds, when one was usable.
    """

    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        status: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        """Create a ``channel_failed`` error."""
        super().__init__("channel_failed", message)
        self.retryable = retryable
        self.status = status
        self.retry_after = retry_after
