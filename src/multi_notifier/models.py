"""Immutable data types shared by every channel."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit

from .errors import NotifierError

__all__ = ["ChannelResult", "DeliveryReport", "HttpResponse", "Notification", "Priority"]

Priority = Literal["low", "normal", "high", "urgent"]

MAX_TITLE_LENGTH = 250
MAX_BODY_LENGTH = 65_536
MAX_TAGS = 20
MAX_TAG_LENGTH = 64
MAX_URL_LENGTH = 2048
_PRIORITIES = ("low", "normal", "high", "urgent")


def _invalid(message: str) -> NotifierError:
    return NotifierError("invalid_notification", message)


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{field_name} must be a string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise _invalid(f"{field_name} must be valid Unicode text") from None
    return value


def _single_line(value: str) -> bool:
    return "\r" not in value and "\n" not in value


def _check_url(value: object) -> str:
    url = _text(value, "url")
    if len(url) > MAX_URL_LENGTH:
        raise _invalid("url is too long")
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in url):
        raise _invalid("url must not contain whitespace or control characters")
    try:
        parts = urlsplit(url)
    except ValueError:
        raise _invalid("url is not valid") from None
    if parts.scheme != "https" or not parts.hostname:
        raise _invalid("url must be an absolute https URL")
    return url


@dataclass(frozen=True)
class Notification:
    """A message to deliver.

    Validation happens at construction and raises ``NotifierError`` with the code
    ``invalid_notification``: the title has 1-250 characters without CR or LF, the body has at
    most 65,536 characters, at most 20 tags of 1-64 characters are allowed and the optional url
    must be an absolute https URL.
    """

    title: str
    body: str
    priority: Priority = "normal"
    tags: tuple[str, ...] = ()
    url: str | None = None

    def __post_init__(self) -> None:
        title = _text(self.title, "title")
        if not 1 <= len(title) <= MAX_TITLE_LENGTH or not _single_line(title):
            raise _invalid("title must be 1-250 characters without line breaks")
        if len(_text(self.body, "body")) > MAX_BODY_LENGTH:
            raise _invalid("body must be at most 65536 characters")
        if self.priority not in _PRIORITIES:
            raise _invalid("priority must be low, normal, high or urgent")
        tags: object = self.tags
        if isinstance(tags, list):
            tags = tuple(tags)
            object.__setattr__(self, "tags", tags)
        if not isinstance(tags, tuple) or len(tags) > MAX_TAGS:
            raise _invalid("tags must be a tuple of at most 20 strings")
        for tag in tags:
            text = _text(tag, "tag")
            if not 1 <= len(text) <= MAX_TAG_LENGTH or not _single_line(text):
                raise _invalid("each tag must be 1-64 characters without line breaks")
        if self.url is not None:
            _check_url(self.url)


@dataclass(frozen=True)
class HttpResponse:
    """The parts of an HTTP response the channels need."""

    status: int
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""


@dataclass(frozen=True)
class ChannelResult:
    """Outcome of delivering one notification through one channel."""

    channel: str
    ok: bool
    attempts: int
    status: int | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class DeliveryReport:
    """Per-channel results, in channel order."""

    results: tuple[ChannelResult, ...] = ()

    @property
    def ok(self) -> bool:
        """True when every selected channel delivered the notification."""
        return all(result.ok for result in self.results)

    @property
    def failed(self) -> tuple[ChannelResult, ...]:
        """The results of the channels that did not deliver."""
        return tuple(result for result in self.results if not result.ok)
