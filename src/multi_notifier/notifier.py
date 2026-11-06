"""Deliver one notification to several channels with bounded retries."""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable, Iterable, Sequence

from .channels import Channel
from .errors import ChannelError, NotifierError
from .models import ChannelResult, DeliveryReport, Notification

__all__ = ["Notifier"]

logger = logging.getLogger(__name__)

MAX_RETRIES = 10
MAX_CHANNELS = 50


def _config_error(message: str) -> NotifierError:
    return NotifierError("invalid_config", message)


def _non_negative(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _config_error(f"{label} must be a number")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise _config_error(f"{label} must be a finite number >= 0")
    return number


class Notifier:
    """Fan a notification out to channels, retrying transient failures.

    Retryable failures are HTTP 429, 5xx and network errors. The delay before retry ``n``
    (counting from zero) is ``min(max_backoff, backoff * 2**n)``, or the server supplied
    Retry-After seconds capped at ``max_backoff``. ``notify`` never raises because a channel
    failed; failures are reported in the ``DeliveryReport``.
    """

    def __init__(
        self,
        channels: Sequence[Channel],
        *,
        retries: int = 2,
        backoff: float = 1.0,
        max_backoff: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        on_event: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        """Configure the notifier; raises ``NotifierError`` (``invalid_config``) on bad input."""
        if isinstance(channels, str | bytes):
            raise _config_error("channels must be a sequence of channel objects")
        items = tuple(channels)
        if not 1 <= len(items) <= MAX_CHANNELS:
            raise _config_error("between 1 and 50 channels are required")
        for item in items:
            if not isinstance(getattr(item, "name", None), str):
                raise _config_error("every channel needs a string name")
            if not callable(getattr(item, "send", None)):
                raise _config_error("every channel needs a send method")
        if isinstance(retries, bool) or not isinstance(retries, int):
            raise _config_error("retries must be an integer")
        if not 0 <= retries <= MAX_RETRIES:
            raise _config_error("retries must be between 0 and 10")
        if not callable(sleep):
            raise _config_error("sleep must be callable")
        if on_event is not None and not callable(on_event):
            raise _config_error("on_event must be callable")
        self._channels = items
        self._retries = retries
        self._backoff = _non_negative(backoff, "backoff")
        self._max_backoff = _non_negative(max_backoff, "max_backoff")
        self._sleep = sleep
        self._on_event = on_event

    def __repr__(self) -> str:
        names = [channel.name for channel in self._channels]
        return f"Notifier(channels={names!r}, retries={self._retries})"

    def notify(
        self,
        notification: Notification,
        *,
        only: Iterable[str] | None = None,
    ) -> DeliveryReport:
        """Deliver ``notification`` and report one result per selected channel, in order.

        ``only`` restricts delivery to channels with the given names; an unknown name raises
        ``NotifierError`` with code ``invalid_config``.
        """
        if not isinstance(notification, Notification):
            raise NotifierError("invalid_notification", "notification must be a Notification")
        selected = self._select(only)
        return DeliveryReport(tuple(self._deliver(channel, notification) for channel in selected))

    def _select(self, only: Iterable[str] | None) -> tuple[Channel, ...]:
        if only is None:
            return self._channels
        names = {only} if isinstance(only, str) else set(only)
        known = {channel.name for channel in self._channels}
        if not names <= known:
            raise _config_error("only names an unknown channel")
        return tuple(channel for channel in self._channels if channel.name in names)

    def _delay(self, index: int, error: ChannelError) -> float:
        if error.retry_after is not None:
            return min(self._max_backoff, error.retry_after)
        computed: float = self._backoff * float(2**index)
        return min(self._max_backoff, computed)

    def _deliver(self, channel: Channel, notification: Notification) -> ChannelResult:
        name = channel.name
        attempt = 0
        while True:
            attempt += 1
            try:
                status = channel.send(notification)
            except ChannelError as exc:
                error = exc
            except Exception:
                logger.debug("channel %s raised an unexpected error", name)
                error = ChannelError("unexpected channel failure", retryable=False)
            else:
                self._emit(name, attempt, status, "sent", None)
                return ChannelResult(name, True, attempt, status, None)
            if error.retryable and attempt <= self._retries:
                delay = self._delay(attempt - 1, error)
                self._emit(name, attempt, error.status, "retry", delay)
                self._sleep(delay)
                continue
            self._emit(name, attempt, error.status, "failed", None)
            return ChannelResult(name, False, attempt, error.status, error.code)

    def _emit(
        self,
        channel: str,
        attempt: int,
        status: int | None,
        outcome: str,
        delay: float | None,
    ) -> None:
        logger.debug("channel=%s attempt=%d outcome=%s", channel, attempt, outcome)
        if self._on_event is None:
            return
        event: dict[str, object] = {
            "channel": channel,
            "attempt": attempt,
            "status": status,
            "outcome": outcome,
            "delay": delay,
        }
        try:
            self._on_event(event)
        except Exception:
            logger.debug("on_event callback raised an exception")
