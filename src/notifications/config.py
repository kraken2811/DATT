"""Notification configuration. Credentials are never included in repr/logs."""
from dataclasses import dataclass, field
import os
from email.utils import parseaddr

NAMES = ('DATT_EMAIL_USERNAME', 'DATT_EMAIL_PASSWORD', 'DATT_EMAIL_TO')


def load_colab_secrets():
    # Call in the notebook kernel before launching the backend, not in workers.
    from google.colab import userdata
    for name in NAMES:
        if not os.getenv(name):
            try:
                value = userdata.get(name)
                if value: os.environ[name] = value
            except (userdata.SecretNotFoundError, userdata.NotebookAccessError):
                pass


def valid_address(value):
    return bool(value and '\n' not in value and '\r' not in value
                and parseaddr(value)[1] == value and '@' in value and len(value) <= 320)


@dataclass(frozen=True)
class EmailConfig:
    host: str = ''
    port: int = 587
    username: str = field(default='', repr=False)
    password: str = field(default='', repr=False)
    sender: str = field(default='', repr=False)
    recipients: tuple[str, ...] = field(default=(), repr=False)
    tls: str = 'starttls'
    cooldown: int = 300
    max_retries: int = 3
    retry_seconds: int = 30

    @property
    def configured(self):
        return bool(self.host and valid_address(self.sender) and self.recipients
                    and all(valid_address(x) for x in self.recipients)
                    and self.username and self.password and self.tls in ('starttls', 'ssl')
                    and 1 <= self.port <= 65535 and self.cooldown >= 0
                    and 0 <= self.max_retries <= 10 and self.retry_seconds > 0)

    @classmethod
    def from_env(cls):
        try:
            return cls(host=os.getenv('DATT_EMAIL_HOST', 'smtp.gmail.com'),
                       port=int(os.getenv('DATT_EMAIL_PORT', '587')),
                       username=os.getenv('DATT_EMAIL_USERNAME', ''),
                       password=os.getenv('DATT_EMAIL_PASSWORD', ''),
                       sender=os.getenv('DATT_EMAIL_FROM') or os.getenv('DATT_EMAIL_USERNAME', ''),
                       recipients=tuple(dict.fromkeys(x.strip() for x in os.getenv('DATT_EMAIL_TO', '').split(',') if x.strip())),
                       tls=os.getenv('DATT_EMAIL_TLS', 'starttls'),
                       cooldown=int(os.getenv('DATT_NOTIFICATION_COOLDOWN_SECONDS', '300')),
                       max_retries=int(os.getenv('DATT_NOTIFICATION_MAX_RETRIES', '3')),
                       retry_seconds=int(os.getenv('DATT_NOTIFICATION_RETRY_SECONDS', '30')))
        except ValueError:
            return cls()
