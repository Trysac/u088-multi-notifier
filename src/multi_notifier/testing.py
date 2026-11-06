"""Deterministic in-memory transport for tests."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .models import HttpResponse

__all__ = ["FakeTransport", "RecordedRequest"]


@dataclass(frozen=True)
class RecordedRequest:
    """One request seen by a ``FakeTransport``."""

    url: str
    body: bytes
    headers: Mapping[str, str]
    timeout: float

    def json(self) -> Any:
        """Decode the request body as JSON."""
        return json.loads(self.body)


class FakeTransport:
    """Replays canned responses (or raises canned exceptions) and records requests.

    At most ``max_requests`` requests are kept; the oldest are dropped first. When no canned
    response is left, ``post`` raises ``RuntimeError``.
    """

    def __init__(
        self,
        responses: Sequence[HttpResponse | Exception] = (),
        *,
        max_requests: int = 1000,
    ) -> None:
        """Create the transport with the responses to replay, in order."""
        self._responses = list(responses)
        self._max_requests = max_requests
        self.requests: list[RecordedRequest] = []

    def post(
        self,
        url: str,
        body: bytes,
        headers: Mapping[str, str],
        timeout: float,
    ) -> HttpResponse:
        """Record the request, then return or raise the next canned outcome."""
        self.requests.append(RecordedRequest(url, body, dict(headers), timeout))
        if len(self.requests) > self._max_requests:
            del self.requests[0]
        if not self._responses:
            raise RuntimeError("FakeTransport has no response left")
        outcome = self._responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
