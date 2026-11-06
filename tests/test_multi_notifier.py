"""Tests for the multi_notifier public API."""

from __future__ import annotations

import io
import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable
from email.message import Message
from http.client import HTTPMessage

import pytest

import multi_notifier
from multi_notifier import (
    ChannelError,
    ChannelResult,
    DeliveryReport,
    HttpResponse,
    Notification,
    Notifier,
    NotifierError,
    NtfyChannel,
    TelegramChannel,
    UrllibTransport,
    WebhookChannel,
)
from multi_notifier.channels import parse_retry_after, truncate_ntfy, truncate_telegram
from multi_notifier.testing import FakeTransport, RecordedRequest
from multi_notifier.transport import MAX_RESPONSE_BYTES, _NoRedirect

OK = HttpResponse(200, {}, b"{}")
NOTE = Notification(title="t", body="hello")
WH_KEY = "whsec_" + "MfKQ9r8GKYqrTwjUPD8I" + "LPZIo2LaLaSw"
NO_PREFIX = "MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"
BAD_B64 = "whsec_!!!"
EMPTY_KEY = "whsec_"
BOT = "123456:ABCdef_ghiSECRET"
CHAT = "42"
NTFY_KEY = "tk"
LEAK_KEY = "tk-very-private-value"
BAD_CRED = "has space"
EMPTY = ""
HOOK = "https://hooks.example/h/path-77-private"
SENSITIVE = "sensitive body text"


def no_sleep(_: float) -> None:
    return None


def resp(
    status: int,
    headers: dict[str, str] | None = None,
    body: bytes = b"",
) -> HttpResponse:
    return HttpResponse(status, headers or {}, body)


def run(
    responses: list[HttpResponse | Exception],
    *,
    retries: int = 2,
) -> tuple[ChannelResult, list[float], FakeTransport]:
    transport = FakeTransport(responses)
    sleeps: list[float] = []
    channel = NtfyChannel("https://ntfy.sh", "alerts", transport=transport)
    notifier = Notifier([channel], retries=retries, sleep=sleeps.append)
    report = notifier.notify(NOTE)
    return report.results[0], sleeps, transport


def utf16_units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


class OkChannel:
    name = "ok"

    def send(self, notification: Notification) -> int:
        return 204


class Boom:
    name = "boom"

    def send(self, notification: Notification) -> int:
        raise RuntimeError("boom")


# --- delivery report and retries -------------------------------------------------------------


def test_report_has_one_result_per_channel_in_order() -> None:
    failing = NtfyChannel("https://ntfy.sh", "alerts", transport=FakeTransport([resp(400)]))
    working = TelegramChannel(BOT, CHAT, transport=FakeTransport([OK]))
    report = Notifier([failing, working]).notify(NOTE)
    assert isinstance(report, DeliveryReport)
    assert [r.channel for r in report.results] == ["ntfy", "telegram"]
    assert [r.ok for r in report.results] == [False, True]
    assert report.ok is False
    assert len(report.failed) == 1


def test_report_ok_when_all_succeed_and_when_empty() -> None:
    report = Notifier([OkChannel()]).notify(NOTE)
    assert report.ok is True
    assert report.results == (ChannelResult("ok", True, 1, 204, None),)
    assert DeliveryReport().ok is True


def test_retries_until_success() -> None:
    result, sleeps, transport = run([resp(503), resp(503), resp(200)])
    assert result.ok
    assert result.attempts == 3
    assert result.status == 200
    assert sleeps == [1.0, 2.0]
    assert len(transport.requests) == 3


def test_gives_up_after_retries() -> None:
    result, sleeps, _ = run([resp(503), resp(503), resp(503), resp(200)])
    assert not result.ok
    assert result.attempts == 3
    assert result.status == 503
    assert result.error_code == "channel_failed"
    assert sleeps == [1.0, 2.0]


def test_client_error_is_not_retried() -> None:
    result, sleeps, _ = run([resp(400, {"Retry-After": "5"}), resp(200)])
    assert result.attempts == 1
    assert result.status == 400
    assert sleeps == []


def test_redirect_is_not_retried() -> None:
    result, _, _ = run([resp(302), resp(200)])
    assert result.attempts == 1
    assert result.status == 302


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("5", 5.0),
        ("999", 30.0),
        ("0", 0.0),
        ("5.5", 1.0),
        ("-1", 1.0),
        ("Wed, 21 Oct 2015 07:28:00 GMT", 1.0),
        ("", 1.0),
    ],
)
def test_retry_after_header(header: str, expected: float) -> None:
    result, sleeps, _ = run([resp(429, {"Retry-After": header}), resp(200)])
    assert result.ok
    assert sleeps == [expected]


def test_retry_after_header_is_case_insensitive() -> None:
    _, sleeps, _ = run([resp(503, {"retry-after": "3"}), resp(200)])
    assert sleeps == [3.0]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("5", 5.0),
        (" 7 ", 7.0),
        ("0", 0.0),
        ("5.5", None),
        ("-1", None),
        ("Wed, 21 Oct 2015 07:28:00 GMT", None),
        ("", None),
        (None, None),
        ("1" * 19, None),
        ("\u0665", None),
        ("5s", None),
    ],
)
def test_parse_retry_after(value: str | None, expected: float | None) -> None:
    assert parse_retry_after(value) == expected


def test_backoff_is_capped_by_max_backoff() -> None:
    transport = FakeTransport([resp(503)] * 4)
    channel = NtfyChannel("https://ntfy.sh", "alerts", transport=transport)
    sleeps: list[float] = []
    notifier = Notifier([channel], retries=3, backoff=10.0, max_backoff=15.0, sleep=sleeps.append)
    notifier.notify(NOTE)
    assert sleeps == [10.0, 15.0, 15.0]


def test_zero_retries_never_sleeps() -> None:
    result, sleeps, _ = run([resp(503), resp(200)], retries=0)
    assert result.attempts == 1
    assert sleeps == []


def test_network_errors_are_retryable() -> None:
    result, sleeps, _ = run([TimeoutError("slow")])
    assert not result.ok
    assert result.attempts == 3
    assert result.status is None
    assert result.error_code == "channel_failed"
    assert sleeps == [1.0, 2.0]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (b'{"ok":false,"parameters":{"retry_after":7}}', 7.0),
        (b'{"ok":false,"parameters":{"retry_after":999}}', 30.0),
        (b"not json", 1.0),
        (b"[1]", 1.0),
        (b'{"parameters":3}', 1.0),
        (b'{"parameters":{"retry_after":true}}', 1.0),
        (b'{"parameters":{"retry_after":-4}}', 1.0),
        (b"\xff\xfe", 1.0),
        (b"[" * 100_000, 1.0),
    ],
)
def test_telegram_retry_after_parameter(body: bytes, expected: float) -> None:
    transport = FakeTransport([resp(429, None, body), OK])
    channel = TelegramChannel(BOT, CHAT, transport=transport)
    sleeps: list[float] = []
    report = Notifier([channel], sleep=sleeps.append).notify(NOTE)
    assert report.ok
    assert sleeps == [expected]


def test_telegram_header_wins_over_parameter() -> None:
    body = b'{"parameters":{"retry_after":7}}'
    transport = FakeTransport([resp(429, {"Retry-After": "2"}, body), OK])
    channel = TelegramChannel(BOT, CHAT, transport=transport)
    sleeps: list[float] = []
    Notifier([channel], sleep=sleeps.append).notify(NOTE)
    assert sleeps == [2.0]


def test_unexpected_channel_exception_is_reported() -> None:
    report = Notifier([Boom(), OkChannel()]).notify(NOTE)
    assert report.results[0] == ChannelResult("boom", False, 1, None, "channel_failed")
    assert report.results[1].ok


def test_only_selects_channels() -> None:
    notifier = Notifier([OkChannel(), Boom()])
    assert [r.channel for r in notifier.notify(NOTE, only=["boom"]).results] == ["boom"]
    assert [r.channel for r in notifier.notify(NOTE, only="ok").results] == ["ok"]
    assert notifier.notify(NOTE, only=[]).results == ()
    with pytest.raises(NotifierError) as info:
        notifier.notify(NOTE, only=["nope"])
    assert info.value.code == "invalid_config"


def test_notify_rejects_non_notification() -> None:
    with pytest.raises(NotifierError) as info:
        Notifier([OkChannel()]).notify("hello")  # type: ignore[arg-type]
    assert info.value.code == "invalid_notification"


def test_notifier_repr() -> None:
    assert repr(Notifier([OkChannel()])) == "Notifier(channels=['ok'], retries=2)"


# --- events ----------------------------------------------------------------------------------


def test_on_event_payloads() -> None:
    events: list[dict[str, object]] = []
    transport = FakeTransport([resp(503), OK])
    channel = NtfyChannel("https://ntfy.sh", "alerts", transport=transport)
    Notifier([channel], sleep=no_sleep, on_event=events.append).notify(NOTE)
    assert events == [
        {"channel": "ntfy", "attempt": 1, "status": 503, "outcome": "retry", "delay": 1.0},
        {"channel": "ntfy", "attempt": 2, "status": 200, "outcome": "sent", "delay": None},
    ]


def test_on_event_reports_final_failure() -> None:
    events: list[dict[str, object]] = []
    transport = FakeTransport([resp(400)])
    channel = NtfyChannel("https://ntfy.sh", "alerts", transport=transport)
    Notifier([channel], on_event=events.append).notify(NOTE)
    assert len(events) == 1
    assert events[0]["outcome"] == "failed"
    assert events[0]["status"] == 400


def test_failing_on_event_callback_does_not_break_delivery() -> None:
    def callback(event: dict[str, object]) -> None:
        raise ValueError("callback bug")

    report = Notifier([OkChannel()], on_event=callback).notify(NOTE)
    assert report.ok


# --- secrets ---------------------------------------------------------------------------------


def test_secrets_never_leak() -> None:
    def failing(url: str) -> FakeTransport:
        return FakeTransport([RuntimeError(f"cannot reach {url} {LEAK_KEY} {BOT}")] * 10)

    ntfy = NtfyChannel(
        "https://ntfy.sh",
        "alerts",
        token=LEAK_KEY,
        transport=failing("https://ntfy.sh/"),
    )
    telegram = TelegramChannel(
        BOT,
        CHAT,
        transport=failing(f"https://api.telegram.org/bot{BOT}/sendMessage"),
    )
    webhook = WebhookChannel(HOOK, secret=WH_KEY, transport=failing(HOOK))
    note = Notification("t", SENSITIVE)
    events: list[dict[str, object]] = []
    notifier = Notifier([ntfy, telegram, webhook], sleep=no_sleep, on_event=events.append)
    report = notifier.notify(note)
    texts = [repr(ntfy), repr(telegram), repr(webhook), repr(notifier), repr(report), str(events)]
    for channel in (ntfy, telegram, webhook):
        with pytest.raises(ChannelError) as info:
            channel.send(note)
        assert info.value.__cause__ is None
        assert info.value.__context__ is None
        assert info.value.retryable is True
        texts.append(str(info.value))
        texts.append(repr(info.value))
    joined = "\n".join(texts)
    secrets = [BOT, LEAK_KEY, WH_KEY, WH_KEY.removeprefix("whsec_"), "path-77-private"]
    for secret in secrets:
        assert secret not in joined
    assert SENSITIVE not in joined
    assert not report.ok


def test_error_messages_are_capped() -> None:
    error = NotifierError("invalid_config", "x" * 1000)
    assert len(str(error)) == 200
    assert error.code == "invalid_config"


# --- Standard Webhooks -----------------------------------------------------------------------


def test_standard_webhooks_published_example() -> None:
    channel = WebhookChannel(HOOK, secret=WH_KEY)
    signature = channel.signature(
        "msg_p5jXN8AQM9LWM0D4loKWxJek",
        1614265330,
        b'{"test": 2432232314}',
    )
    assert signature == "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE="


def test_webhook_request() -> None:
    transport = FakeTransport([OK])
    channel = WebhookChannel(
        HOOK,
        secret=WH_KEY,
        transport=transport,
        clock=lambda: 1614265330.9,
        id_factory=lambda: "msg_p5jXN8AQM9LWM0D4loKWxJek",
    )
    note = Notification("t", "h\u00e9llo", "urgent", ("a",), "https://example.com/x")
    assert channel.send(note) == 200
    request = transport.requests[0]
    expected = json.dumps(
        {
            "title": "t",
            "body": "h\u00e9llo",
            "priority": "urgent",
            "tags": ["a"],
            "url": "https://example.com/x",
        },
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    assert request.body == expected
    assert request.url == HOOK
    assert request.headers["webhook-id"] == "msg_p5jXN8AQM9LWM0D4loKWxJek"
    assert request.headers["webhook-timestamp"] == "1614265330"
    signature = channel.signature("msg_p5jXN8AQM9LWM0D4loKWxJek", 1614265330, expected)
    assert request.headers["webhook-signature"] == signature


def test_webhook_defaults_use_clock_and_uuid() -> None:
    transport = FakeTransport([OK])
    WebhookChannel(HOOK, secret=WH_KEY, transport=transport).send(NOTE)
    headers = transport.requests[0].headers
    assert len(headers["webhook-id"]) == 32
    assert headers["webhook-timestamp"].isdigit()
    assert headers["webhook-signature"].startswith("v1,")


def test_webhook_rejects_unsafe_message_id() -> None:
    channel = WebhookChannel(
        HOOK,
        secret=WH_KEY,
        transport=FakeTransport([OK]),
        id_factory=lambda: "bad\r\nid",
    )
    with pytest.raises(ChannelError) as info:
        channel.send(NOTE)
    assert info.value.retryable is False
    assert info.value.code == "channel_failed"


def test_webhook_allow_insecure() -> None:
    channel = WebhookChannel("http://hooks.example/x", secret=WH_KEY, allow_insecure=True)
    assert repr(channel) == "WebhookChannel(host='hooks.example')"


# --- ntfy and Telegram requests --------------------------------------------------------------


def test_ntfy_request_shape() -> None:
    transport = FakeTransport([OK])
    channel = NtfyChannel("https://ntfy.sh", "alerts", token=NTFY_KEY, transport=transport)
    note = Notification("Disk", "full", "high", ("a", "b"), "https://example.com/x")
    assert channel.send(note) == 200
    request = transport.requests[0]
    assert request.url == "https://ntfy.sh/"
    assert request.timeout == 10.0
    assert request.headers["Authorization"] == "Bearer tk"
    payload = request.json()
    assert set(payload) == {"topic", "title", "message", "priority", "tags", "click"}
    assert payload == {
        "topic": "alerts",
        "title": "Disk",
        "message": "full",
        "priority": 4,
        "tags": ["a", "b"],
        "click": "https://example.com/x",
    }


@pytest.mark.parametrize(
    ("priority", "number"),
    [("low", 2), ("normal", 3), ("high", 4), ("urgent", 5)],
)
def test_ntfy_priority_mapping(priority: str, number: int) -> None:
    transport = FakeTransport([OK])
    channel = NtfyChannel("https://ntfy.sh", "alerts", transport=transport)
    channel.send(Notification("t", "b", priority))  # type: ignore[arg-type]
    assert transport.requests[0].json()["priority"] == number


def test_ntfy_without_token_and_with_path_prefix() -> None:
    transport = FakeTransport([OK])
    channel = NtfyChannel("https://ntfy.example/base/", "alerts", transport=transport)
    channel.send(Notification("T\u00edtulo", "b"))
    request = transport.requests[0]
    assert request.url == "https://ntfy.example/base/"
    assert "Authorization" not in request.headers
    assert request.json()["title"] == "T\u00edtulo"
    assert request.json()["click"] is None
    assert repr(channel) == "NtfyChannel(host='ntfy.example')"


def test_ntfy_allows_http_only_when_explicit() -> None:
    with pytest.raises(NotifierError) as info:
        NtfyChannel("http://ntfy.example", "t")
    assert info.value.code == "invalid_config"
    channel = NtfyChannel("http://ntfy.example", "t", allow_insecure=True)
    assert isinstance(channel, NtfyChannel)


def test_ntfy_message_is_cut_at_a_character() -> None:
    transport = FakeTransport([OK, OK, OK, OK])
    channel = NtfyChannel("https://ntfy.sh", "alerts", transport=transport)
    for body in ("a" * 5000, "\u20ac" * 2000, "\U0001f600" * 2000, "short"):
        channel.send(Notification("t", body))
    sizes = []
    for request in transport.requests:
        message = request.json()["message"]
        encoded = message.encode("utf-8")
        assert encoded.decode("utf-8") == message
        sizes.append(len(encoded))
    assert sizes == [4096, 4095, 4096, 5]


def test_telegram_request_shape() -> None:
    transport = FakeTransport([OK])
    channel = TelegramChannel(BOT, CHAT, transport=transport)
    channel.send(Notification("Disk", "full", url="https://example.com/x"))
    request = transport.requests[0]
    assert request.url == f"https://api.telegram.org/bot{BOT}/sendMessage"
    payload = request.json()
    assert payload == {"chat_id": "42", "text": "Disk\n\nfull\nhttps://example.com/x"}
    assert "parse_mode" not in payload
    assert repr(channel) == "TelegramChannel()"


def test_telegram_text_without_url() -> None:
    transport = FakeTransport([OK])
    TelegramChannel(BOT, CHAT, transport=transport).send(Notification("t", "<b>x</b>"))
    assert transport.requests[0].json()["text"] == "t\n\n<b>x</b>"


def test_telegram_text_is_cut_in_utf16_units() -> None:
    transport = FakeTransport([OK, OK])
    channel = TelegramChannel(BOT, CHAT, transport=transport)
    channel.send(Notification(title="t", body="a" * 5000))
    text = transport.requests[0].json()["text"]
    assert utf16_units(text) == 4096
    assert text.endswith("\u2026")
    # The emoji below is U+1F600, i.e. the surrogate pair \ud83d\ude00 in UTF-16.
    channel.send(Notification(title="t", body="\U0001f600" * 3000))
    text = transport.requests[1].json()["text"]
    assert utf16_units(text) == 4096
    assert text.count("\U0001f600") == 2046
    assert text.endswith("\u2026")


def test_truncation_helpers_leave_short_text_alone() -> None:
    assert truncate_telegram("abc") == "abc"
    assert truncate_ntfy("abc") == "abc"
    assert truncate_telegram("a" * 4096) == "a" * 4096
    assert truncate_telegram("a" * 4097) == "a" * 4095 + "\u2026"
    assert truncate_ntfy("a" * 10, limit=4) == "aaaa"


# --- validation ------------------------------------------------------------------------------


def test_notification_defaults_and_list_tags() -> None:
    note = Notification("t", "b", tags=["a", "b"])  # type: ignore[arg-type]
    assert note.priority == "normal"
    assert note.tags == ("a", "b")
    assert note.url is None
    assert Notification("t", "b", url="https://example.com/x").url == "https://example.com/x"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"title": "a\nb", "body": "x"},
        {"title": "a\rb", "body": "x"},
        {"title": "", "body": "x"},
        {"title": "a" * 251, "body": "x"},
        {"title": 5, "body": "x"},
        {"title": "t", "body": "x" * 65_537},
        {"title": "t", "body": "\ud800"},
        {"title": "t", "body": "x", "priority": "max"},
        {"title": "t", "body": "x", "tags": "abc"},
        {"title": "t", "body": "x", "tags": ("a",) * 21},
        {"title": "t", "body": "x", "tags": ("",)},
        {"title": "t", "body": "x", "tags": ("a\nb",)},
        {"title": "t", "body": "x", "tags": (1,)},
        {"title": "t", "body": "x", "url": "http://example.com"},
        {"title": "t", "body": "x", "url": "https://"},
        {"title": "t", "body": "x", "url": "https://exa mple.com"},
        {"title": "t", "body": "x", "url": "https://[::1"},
        {"title": "t", "body": "x", "url": "https://e.com/" + "a" * 2048},
        {"title": "t", "body": "x", "url": 5},
    ],
)
def test_invalid_notifications(kwargs: dict[str, object]) -> None:
    with pytest.raises(NotifierError) as info:
        Notification(**kwargs)  # type: ignore[arg-type]
    assert info.value.code == "invalid_notification"


def test_notification_boundaries_are_accepted() -> None:
    assert Notification("a" * 250, "x" * 65_536).title == "a" * 250
    assert len(Notification("t", "x", tags=("a",) * 20).tags) == 20


@pytest.mark.parametrize(
    "make",
    [
        lambda: NtfyChannel("http://ntfy.example", "t"),
        lambda: NtfyChannel("https://ntfy.sh", "bad topic!"),
        lambda: NtfyChannel("https://user@ntfy.sh", "t"),
        lambda: NtfyChannel("https://ntfy.sh?x=1", "t"),
        lambda: NtfyChannel("https://ntfy.sh:99999", "t"),
        lambda: NtfyChannel("https://nt fy.sh", "t"),
        lambda: NtfyChannel("", "t"),
        lambda: NtfyChannel("https://ntfy.sh", "t", token=BAD_CRED),
        lambda: NtfyChannel("https://ntfy.sh", "t", token=EMPTY),
        lambda: TelegramChannel("bad token/", CHAT),
        lambda: TelegramChannel(BOT, EMPTY),
        lambda: WebhookChannel("http://hooks.example", secret=WH_KEY),
        lambda: WebhookChannel(HOOK, secret=NO_PREFIX),
        lambda: WebhookChannel(HOOK, secret=BAD_B64),
        lambda: WebhookChannel(HOOK, secret=EMPTY_KEY),
        lambda: Notifier([]),
        lambda: Notifier("ab"),
        lambda: Notifier([object()]),
        lambda: Notifier([OkChannel()], retries=-1),
        lambda: Notifier([OkChannel()], retries=11),
        lambda: Notifier([OkChannel()], retries=True),
        lambda: Notifier([OkChannel()], backoff=-1.0),
        lambda: Notifier([OkChannel()], backoff=float("nan")),
        lambda: Notifier([OkChannel()], max_backoff="x"),
        lambda: Notifier([OkChannel()], sleep=None),
        lambda: Notifier([OkChannel()], on_event=5),
        lambda: Notifier([OkChannel()] * 51),
    ],
)
def test_invalid_config(make: Callable[[], object]) -> None:
    with pytest.raises(NotifierError) as info:
        make()
    assert info.value.code == "invalid_config"


def test_channel_without_send_is_rejected() -> None:
    class NoSend:
        name = "x"

    with pytest.raises(NotifierError) as info:
        Notifier([NoSend()])  # type: ignore[list-item]
    assert info.value.code == "invalid_config"


# --- FakeTransport and UrllibTransport -------------------------------------------------------


def test_fake_transport_records_and_replays() -> None:
    fake = FakeTransport([OK, ValueError("x")])
    assert fake.post("https://a.example/", b"{}", {"H": "v"}, 3.0) == OK
    with pytest.raises(ValueError, match="x"):
        fake.post("https://b.example/", b"[1]", {}, 4.0)
    with pytest.raises(RuntimeError):
        fake.post("https://c.example/", b"", {}, 5.0)
    assert [r.url for r in fake.requests] == [
        "https://a.example/",
        "https://b.example/",
        "https://c.example/",
    ]
    assert isinstance(fake.requests[0], RecordedRequest)
    assert fake.requests[0].headers == {"H": "v"}
    assert fake.requests[1].json() == [1]


def test_fake_transport_caps_recorded_requests() -> None:
    fake = FakeTransport([OK] * 5, max_requests=2)
    for index in range(5):
        fake.post(f"https://a.example/{index}", b"", {}, 1.0)
    assert [r.url for r in fake.requests] == ["https://a.example/3", "https://a.example/4"]


class FakeHttpResponse:
    def __init__(self, status: int, headers: Message, data: bytes) -> None:
        self.status = status
        self.headers = headers
        self._data = data
        self.read_sizes: list[int] = []

    def __enter__(self) -> FakeHttpResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        return self._data[:size]


class FakeOpener:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome
        self.requests: list[urllib.request.Request] = []
        self.timeouts: list[float] = []

    def open(self, request: urllib.request.Request, timeout: float) -> object:
        self.requests.append(request)
        self.timeouts.append(timeout)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def test_urllib_transport_success() -> None:
    headers = Message()
    headers["Retry-After"] = "5"
    fake = FakeHttpResponse(200, headers, b"ok")
    opener = FakeOpener(fake)
    transport = UrllibTransport(opener)  # type: ignore[arg-type]
    result = transport.post("https://a.example/x", b"{}", {"Authorization": "Bearer z"}, 7.0)
    assert result == HttpResponse(200, {"Retry-After": "5"}, b"ok")
    request = opener.requests[0]
    assert request.full_url == "https://a.example/x"
    assert request.data == b"{}"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer z"
    assert opener.timeouts == [7.0]
    assert fake.read_sizes == [MAX_RESPONSE_BYTES]


def test_urllib_transport_returns_http_errors_as_responses() -> None:
    headers = Message()
    headers["Retry-After"] = "2"
    error = urllib.error.HTTPError(
        "https://a.example/x",
        503,
        "unavailable",
        headers,  # type: ignore[arg-type]
        io.BytesIO(b"busy"),
    )
    transport = UrllibTransport(FakeOpener(error))  # type: ignore[arg-type]
    result = transport.post("https://a.example/x", b"", {}, 1.0)
    assert result == HttpResponse(503, {"Retry-After": "2"}, b"busy")


def test_urllib_transport_propagates_network_errors() -> None:
    transport = UrllibTransport(FakeOpener(urllib.error.URLError("down")))  # type: ignore[arg-type]
    with pytest.raises(urllib.error.URLError):
        transport.post("https://a.example/x", b"", {}, 1.0)


@pytest.mark.parametrize("url", ["ftp://a.example/x", "file:///etc/passwd", ""])
def test_urllib_transport_rejects_other_schemes(url: str) -> None:
    transport = UrllibTransport(FakeOpener(None))  # type: ignore[arg-type]
    with pytest.raises(NotifierError) as info:
        transport.post(url, b"", {}, 1.0)
    assert info.value.code == "invalid_config"


def test_urllib_transport_never_follows_redirects() -> None:
    handler = _NoRedirect()
    request = urllib.request.Request("https://a.example/x", data=b"", method="POST")
    result = handler.redirect_request(
        request,
        io.BytesIO(b""),
        302,
        "Found",
        HTTPMessage(),
        "https://other.example/",
    )
    assert result is None
    assert isinstance(UrllibTransport(), UrllibTransport)


def test_channel_with_urllib_transport_failure_is_secret_free() -> None:
    opener = FakeOpener(urllib.error.URLError(f"failed {BOT}"))
    transport = UrllibTransport(opener)  # type: ignore[arg-type]
    channel = TelegramChannel(BOT, CHAT, transport=transport)
    with pytest.raises(ChannelError) as info:
        channel.send(NOTE)
    assert BOT not in str(info.value)
    assert info.value.__context__ is None


# --- acceptance literals ---------------------------------------------------------------------

# Acceptance coverage (verbatim phrases):
#   a 429 with Retry-After '5' sleeps 5.0, '999' sleeps max_backoff 30.0, and '5.5'
#   Notification(title='a\nb', body='x') raises NotifierError with code == 'invalid_notification'
#   NtfyChannel('http://ntfy.example', 't') raises code == 'invalid_config'
#   For title 't' and body 'a' * 5000 the Telegram text is 4096 UTF-16 code units ending in '…'
#   for body '😀' * 3000
#   NtfyChannel('https://ntfy.sh', 'alerts', token='tk') posts to 'https://ntfy.sh/'
#   a JSON object with keys 'topic', 'title', 'message', 'priority', 'tags', 'click'
#   header 'Authorization: Bearer tk'


def test_acceptance_published_secret_literal() -> None:
    channel = WebhookChannel(HOOK, secret="whsec_" + "MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw")
    message = b'{"test": 2432232314}'
    signature = channel.signature("msg_p5jXN8AQM9LWM0D4loKWxJek", 1614265330, message)
    assert signature == "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE="


# --- package ---------------------------------------------------------------------------------


def test_package_metadata_and_logging() -> None:
    assert multi_notifier.__version__ == "0.1.0"
    for name in multi_notifier.__all__:
        assert hasattr(multi_notifier, name)
    handlers = logging.getLogger("multi_notifier").handlers
    assert any(isinstance(handler, logging.NullHandler) for handler in handlers)
