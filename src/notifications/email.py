"""Email adapter; other channels can implement the same send contract."""
from .base import NotificationAdapter
from .config import valid_address
from email.message import EmailMessage
import smtplib
import ssl


class SMTPEmailAdapter:
    def __init__(self, config, storage_factory=None):
        self.config = config
        if storage_factory is None:
            from src.storage import get_storage
            storage_factory = get_storage
        self.storage_factory = storage_factory

    def message(self, item):
        p = item.payload
        message = EmailMessage()
        vehicle = p.get('alert_type') == 'VEHICLE_WATCHLIST_MATCH'
        message['Subject'] = 'DATT Vehicle Watchlist MATCH' if vehicle else 'DATT Face Watchlist MATCH'
        message['From'] = self.config.sender
        message['To'] = item.recipient
        message['Message-ID'] = f'<datt-notification-{item.id}@datt.local>'
        body = '\n'.join(f'{label}: {p.get(key) if p.get(key) is not None else "unavailable"}' for label, key in (
            ('Target name', 'target_name'), ('Target ID', 'target_id'),
            ('Camera', 'camera_id'), ('Time (UTC)', 'event_time'),
            ('Similarity', 'similarity'), ('FaceEvent ID', 'event_id')))
        if vehicle:
            body = '\n'.join(f'{label}: {p.get(key) if p.get(key) is not None else "unavailable"}' for label,key in (
                ('Alert type','alert_type'),('Plate','plate_number'),('Display name','display_name'),
                ('Camera','camera_id'),('Time (UTC)','event_time'),('OCR confidence','confidence'),('PlateEvent ID','event_id')))
        evidence = None
        if p.get('evidence_key'):
            try:
                with self.storage_factory().open(p['evidence_key']) as stream:
                    evidence = stream.read(5 * 1024 * 1024 + 1)
                if len(evidence) > 5 * 1024 * 1024:
                    evidence = None
            except Exception:
                pass  # Optional evidence cannot prevent a text alert.
        if not evidence: body += '\nEvidence: unavailable'
        message.set_content(body)
        if evidence:
            message.add_attachment(evidence, maintype='image', subtype='jpeg', filename='evidence.jpg')
        return message

    def send(self, item):
        c = self.config
        if not valid_address(item.recipient):
            raise smtplib.SMTPRecipientsRefused({})
        message = self.message(item)
        context = ssl.create_default_context()
        factory = smtplib.SMTP_SSL if c.tls == 'ssl' else smtplib.SMTP
        kwargs = {'timeout': 15}
        if c.tls == 'ssl': kwargs['context'] = context
        with factory(c.host, c.port, **kwargs) as client:
            if c.tls == 'starttls': client.starttls(context=context)
            client.login(c.username, c.password)
            refused = client.send_message(message)
            if refused: raise smtplib.SMTPRecipientsRefused(refused)
