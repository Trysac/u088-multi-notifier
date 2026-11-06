"""Notification channels: ntfy, Telegram and Standard Webhooks."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import time
import uuid
from collections.abc import Callable, Mapping
from typing import Protocol
from urllib.parse import urlsplit

from .errors import ChannelError, NotifierError
from .models import HttpResponse, Notification
from .transport import DEFAULT_TIMEOUT, HttpTransport, UrllibTransport

__all__ = [
    "NTFY_LIMIT",
    "TELEGRAM_LIMIT",
    "Channel",
    "NtfyChannel",
    "TelegramChannel",
    "WebhookChannel",
    "parse_retry_after",
    "truncate_ntfy",
    "truncate_telegram",
]

logger = logging.getLogger(__name__)

TELEGRAM_LIMIT = 4096
NTFY_LIMIT = 4096
_MAX_URL = 2048
_MAX_PARSED_BODY = 65_536
_ELLIPSIS = "\u2026"
_JSON_TYPE = "application/json; charset=utf-8"
_PREFIX = "whsec_"
_TOPIC = re.compile(r"[A-Za-z0-9_-]{1,64}")
_BOT_TOKEN = re.compile(r"[A-Za-z0-9:_-]{1,200}")
_MESSAGE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
_RETRY_AFTER = re.compile(r"[0-9]{1,18}")
_NTFY_PRIORITY = {"low": 2, "normal": 3, "high": 4, "urgent": 5}


class Channel(Protocol):
    """A destination for notifications."""

    name: str

    def send(self, notification: Notification) -> int:
        """Deliver once and return the HTTP status; raise ``ChannelError`` on failure."""


def _config_error(message: str) -> NotifierError:
    return NotifierError("invalid_config", message)


def _has_unsafe_char(value: str) -> bool:
    return any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in value)


def _check_endpoint(url: object, label: str, *, allow_insecure: bool, allow_query: bool) -> str:
    problem = f"{label} must be an absolute https URL (http needs allow_insecure=True)"
    if not isinstance(url, str) or not 0 < len(url) <= _MAX_URL or _has_unsafe_char(url):
        raise _config_error(problem)
    try:
        parts = urlsplit(url)
        hostname = parts.hostname
        _ = parts.port
    except ValueError:
        raise _config_error(problem) from None
    schemes = ("https", "http") if allow_insecure else ("https",)
    if parts.scheme not in schemes or not hostname:
        raise _config_error(problem)
    if "@" in parts.netloc:
        raise _config_error(f"{label} must not embed credentials")
    if not allow_query and (parts.query or parts.fragment):
        raise _config_error(f"{label} must not contain a query or fragment")
    return url


def _check_credential(value: object, label: str) -> str:
    if not isinstance(value, str) or not 0 < len(value) <= 512:
        raise _config_error(f"{label} must be a non-empty string")
    if not all(33 <= ord(ch) <= 126 for ch in value):
        raise _config_error(f"{label} contains unsupported characters")
    return value


def parse_retry_after(value: str | None) -> float | None:
    """Parse a Retry-After header, accepting only a non-negative integer of seconds.

    HTTP dates, fractions, negative numbers and anything else return ``None``.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if _RETRY_AFTER.fullmatch(text) is None:
        return None
    return float(int(text))


def _telegram_retry_after(body: bytes) -> float | None:
    try:
        data = json.loads(body[:_MAX_PARSED_BODY])
    except (ValueError, RecursionError):
        return None
    if not isinstance(data, dict):
        return None
    parameters = data.get("parameters")
    if not isinstance(parameters, dict):
        return None
    seconds = parameters.get("retry_after")
    if isinstance(seconds, int) and not isinstance(seconds, bool) and seconds >= 0:
        return float(seconds)
    return None


def _header(headers: Mapping[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name:
            return value
    return None


def _classify(response: HttpResponse, *, telegram: bool = False) -> int:
    status = response.status
    if 200 <= status < 300:
        return status
    retryable = status == 429 or status >= 500
    retry_after: float | None = None
    if retryable:
        retry_after = parse_retry_after(_header(response.headers, "retry-after"))
        if retry_after is None and telegram:
            retry_after = _telegram_retry_after(response.body)
    raise ChannelError(
        f"server answered with HTTP status {status}",
        retryable=retryable,
        status=status,
        retry_after=retry_after,
    )


def _post(
    transport: HttpTransport,
    url: str,
    body: bytes,
    headers: Mapping[str, str],
) -> HttpResponse:
    response: HttpResponse | None = None
    try:
        response = transport.post(url, body, headers, DEFAULT_TIMEOUT)
    except Exception:
        logger.debug("transport raised an exception")
    if response is None:
        # Raised outside the except block: the original exception text may hold the URL.
        raise ChannelError("network error while sending", retryable=True)
    return response


def _dump(payload: Mapping[str, object]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _utf16_length(text: str) -> int:
    return len(text) + sum(1 for char in text if ord(char) > 0xFFFF)


def truncate_telegram(text: str, limit: int = TELEGRAM_LIMIT) -> str:
    """Cut ``text`` to ``limit`` UTF-16 code units at a code-point boundary.

    A cut text ends with U+2026 and the result is never longer than ``limit`` units.
    """
    if _utf16_length(text) <= limit:
        return text
    budget = limit - 1
    used = 0
    end = 0
    for index, char in enumerate(text):
        width = 2 if ord(char) > 0xFFFF else 1
        if used + width > budget:
            break
        used += width
        end = index + 1
    return text[:end] + _ELLIPSIS


def truncate_ntfy(text: str, limit: int = NTFY_LIMIT) -> str:
    """Cut ``text`` to at most ``limit`` UTF-8 bytes without splitting a character."""
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    return encoded[:limit].decode("utf-8", errors="ignore")


class NtfyChannel:
    """Publish to an ntfy topic using JSON publishing."""

    name: str = "ntfy"

    def __init__(
        self,
        server_url: str,
        topic: str,
        *,
        token: str | None = None,
        transport: HttpTransport | None = None,
        allow_insecure: bool = False,
    ) -> None:
        """Configure the channel; raises ``NotifierError`` (``invalid_config``) on bad input."""
        base = _check_endpoint(
            server_url,
            "server_url",
            allow_insecure=allow_insecure,
            allow_query=False,
        )
        if not isinstance(topic, str) or _TOPIC.fullmatch(topic) is None:
            raise _config_error("topic must be 1-64 characters of letters, digits, _ or -")
        self._url = base.rstrip("/") + "/"
        self._host = urlsplit(base).hostname
        self._topic = topic
        self._token = None if token is None else _check_credential(token, "token")
        self._transport: HttpTransport = UrllibTransport() if transport is None else transport

    def __repr__(self) -> str:
        return f"NtfyChannel(host={self._host!r})"

    def send(self, notification: Notification) -> int:
        """Publish ``notification`` once and return the HTTP status."""
        payload: dict[str, object] = {
            "topic": self._topic,
            "title": notification.title,
            "message": truncate_ntfy(notification.body),
            "priority": _NTFY_PRIORITY[notification.priority],
            "tags": list(notification.tags),
            "click": notification.url,
        }
        headers = {"Content-Type": _JSON_TYPE}
        if self._token is not None:
            headers["Authorization"] = f"Bearer {self._token}"
        return _classify(_post(self._transport, self._url, _dump(payload), headers))


class TelegramChannel:
    """Send plain text through the Telegram Bot API (no parse_mode, so no markup injection)."""

    name: str = "telegram"

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        *,
        transport: HttpTransport | None = None,
    ) -> None:
        """Configure the channel; raises ``NotifierError`` (``invalid_config``) on bad input."""
        if not isinstance(bot_token, str) or _BOT_TOKEN.fullmatch(bot_token) is None:
            raise _config_error("bot_token has an unsupported format")
        if not isinstance(chat_id, str) or not 0 < len(chat_id) <= 128:
            raise _config_error("chat_id must be a non-empty string")
        self._url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self._chat_id = chat_id
        self._transport: HttpTransport = UrllibTransport() if transport is None else transport

    def __repr__(self) -> str:
        return "TelegramChannel()"

    def send(self, notification: Notification) -> int:
        """Send ``notification`` once and return the HTTP status."""
        text = f"{notification.title}\n\n{notification.body}"
        if notification.url is not None:
            text += f"\n{notification.url}"
        payload: dict[str, object] = {
            "chat_id": self._chat_id,
            "text": truncate_telegram(text),
        }
        headers = {"Content-Type": _JSON_TYPE}
        response = _post(self._transport, self._url, _dump(payload), headers)
        return _classify(response, telegram=True)


def _new_id() -> str:
    return uuid.uuid4().hex


class WebhookChannel:
    """POST a JSON document signed as described by the Standard Webhooks specification."""

    name: str = "webhook"

    def __init__(
        self,
        url: str,
        *,
        secret: str,
        transport: HttpTransport | None = None,
        clock: Callable[[], float] = time.time,
        id_factory: Callable[[], str] = _new_id,
        allow_insecure: bool = False,
    ) -> None:
        """Configure the channel; ``secret`` is ``whsec_`` followed by the base64 signing key."""
        self._url = _check_endpoint(url, "url", allow_insecure=allow_insecure, allow_query=True)
        if not isinstance(secret, str) or not secret.startswith(_PREFIX):
            raise _config_error("secret must start with whsec_")
        try:
            key = base64.b64decode(secret.removeprefix(_PREFIX), validate=True)
        except ValueError:
            raise _config_error("secret is not valid base64") from None
        if not key:
            raise _config_error("secret must hold a signing key")
        self._key = key
        self._host = urlsplit(self._url).hostname
        self._clock = clock
        self._id_factory = id_factory
        self._transport: HttpTransport = UrllibTransport() if transport is None else transport

    def __repr__(self) -> str:
        return f"WebhookChannel(host={self._host!r})"

    def signature(self, msg_id: str, timestamp: int, body: bytes) -> str:
        """Return ``v1,`` plus base64(HMAC-SHA256(key, ``id.timestamp.body``))."""
        signed = f"{msg_id}.{timestamp}.".encode() + body
        digest = hmac.new(self._key, signed, hashlib.sha256).digest()
        return "v1," + base64.b64encode(digest).decode("ascii")

    def send(self, notification: Notification) -> int:
        """POST ``notification`` once and return the HTTP status."""
        msg_id = self._id_factory()
        if not isinstance(msg_id, str) or _MESSAGE_ID.fullmatch(msg_id) is None:
            raise ChannelError("id_factory returned an invalid message id", retryable=False)
        timestamp = int(self._clock())
        payload: dict[str, object] = {
            "title": notification.title,
            "body": notification.body,
            "priority": notification.priority,
            "tags": list(notification.tags),
            "url": notification.url,
        }
        body = _dump(payload)
        headers = {
            "Content-Type": _JSON_TYPE,
            "webhook-id": msg_id,
            "webhook-timestamp": str(timestamp),
            "webhook-signature": self.signature(msg_id, timestamp, body),
        }
        return _classify(_post(self._transport, self._url, body, headers))
