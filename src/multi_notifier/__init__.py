"""Send one notification to ntfy, Telegram and Standard Webhooks endpoints."""

from __future__ import annotations

import logging

from .channels import Channel, NtfyChannel, TelegramChannel, WebhookChannel
from .errors import ChannelError, NotifierError
from .models import ChannelResult, DeliveryReport, HttpResponse, Notification
from .notifier import Notifier
from .transport import HttpTransport, UrllibTransport

__all__ = [
    "Channel",
    "ChannelError",
    "ChannelResult",
    "DeliveryReport",
    "HttpResponse",
    "HttpTransport",
    "Notification",
    "Notifier",
    "NotifierError",
    "NtfyChannel",
    "TelegramChannel",
    "UrllibTransport",
    "WebhookChannel",
    "__version__",
]

__version__ = "0.1.0"

logging.getLogger(__name__).addHandler(logging.NullHandler())
