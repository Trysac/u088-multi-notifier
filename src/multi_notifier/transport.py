"""HTTP transport protocol and the default urllib implementation."""

from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Mapping
from http.client import HTTPMessage
from typing import IO, Protocol

from .errors import NotifierError
from .models import HttpResponse

__all__ = ["DEFAULT_TIMEOUT", "MAX_RESPONSE_BYTES", "HttpTransport", "UrllibTransport"]

DEFAULT_TIMEOUT = 10.0
MAX_RESPONSE_BYTES = 65_536


class HttpTransport(Protocol):
    """Anything able to POST bytes to a URL and return the response."""

    def post(
        self,
        url: str,
        body: bytes,
        headers: Mapping[str, str],
        timeout: float,
    ) -> HttpResponse:
        """POST ``body`` to ``url`` and return the response, whatever its status."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect so credentials are never replayed to another location."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        return None


class UrllibTransport:
    """Default transport built on urllib.

    Reads at most 65,536 response bytes, applies the given timeout and never follows redirects
    (a 3xx answer is returned as a response). Network failures propagate as exceptions; the
    channels translate them into secret-free ``ChannelError`` instances.
    """

    def __init__(self, opener: urllib.request.OpenerDirector | None = None) -> None:
        """Create the transport, optionally with a custom opener (used by tests)."""
        if opener is None:
            opener = urllib.request.build_opener(_NoRedirect)
        self._opener = opener

    def post(
        self,
        url: str,
        body: bytes,
        headers: Mapping[str, str],
        timeout: float = DEFAULT_TIMEOUT,
    ) -> HttpResponse:
        """POST ``body`` to an http(s) URL and return status, headers and a capped body."""
        if not url.lower().startswith(("https://", "http://")):
            raise NotifierError("invalid_config", "unsupported URL scheme")
        request = urllib.request.Request(  # noqa: S310
            url, data=body, headers=dict(headers), method="POST"
        )
        try:
            with self._opener.open(request, timeout=timeout) as response:
                return HttpResponse(
                    int(response.status),
                    dict(response.headers.items()),
                    response.read(MAX_RESPONSE_BYTES),
                )
        except urllib.error.HTTPError as error:
            try:
                data = error.read(MAX_RESPONSE_BYTES)
            finally:
                error.close()
            return HttpResponse(error.code, dict(error.headers.items()), data)
