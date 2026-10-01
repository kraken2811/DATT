"""Channel adapter extension point for Email, future Telegram and Slack.

Return only after provider acceptance. Raise on delivery failure; the shared
worker owns retries/cooldown/history. Implementations must not log credentials.
"""
from typing import Protocol

class NotificationAdapter(Protocol):
    def send(self, notification) -> None: ...
