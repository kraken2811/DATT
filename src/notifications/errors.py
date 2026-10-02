"""Public, allowlisted delivery diagnostics; never expose provider exception text."""
import smtplib

ERROR_MESSAGES = {
    'CONFIGURED=false': 'Email configuration is missing or invalid.',
    'cooldown': 'Suppressed by the existing notification cooldown.',
    'event_not_match': 'The source event is no longer eligible.',
    'smtp_timeout': 'SMTP delivery timed out.',
    'smtp_authentication': 'SMTP authentication failed.',
    'smtp_connection': 'Cannot connect to the SMTP service.',
    'invalid_recipient': 'SMTP rejected the recipient address.',
    'delivery_failed': 'Email delivery failed.',
}
RETRY_ERRORS = ('smtp_timeout', 'smtp_authentication', 'smtp_connection',
                'invalid_recipient', 'delivery_failed')


def delivery_error(exc):
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return 'smtp_authentication'
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return 'invalid_recipient'
    if isinstance(exc, TimeoutError):
        return 'smtp_timeout'
    if isinstance(exc, (OSError, smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError)):
        return 'smtp_connection'
    return 'delivery_failed'


def safe_error(code):
    return ERROR_MESSAGES.get(code, ERROR_MESSAGES['delivery_failed']) if code else None
