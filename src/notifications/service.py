"""Transactional outbox. Only the email worker performs network delivery."""
from datetime import timedelta, timezone
import logging
import threading
from sqlalchemy import select
from src.db.models import Notification, Target, FaceEvent, PlateEvent, VehicleWatchlist, VehicleWatchlistResult, utc_now
from .config import EmailConfig
from .email import SMTPEmailAdapter

log = logging.getLogger('datt.notifications')


class NotificationService:
    def __init__(self, db, config=None, adapters=None):
        self.db = db
        self.config = config or EmailConfig.from_env()
        self.adapters = adapters if adapters is not None else {'email': SMTPEmailAdapter(self.config)}
        self._stop = threading.Event()
        self._thread = None
        log.info('[NOTIFICATIONS] CONFIGURED=%s', str(self.config.configured).lower())

    def enqueue_face(self, session, event, dto):
        if event.decision != 'FACE_MATCH' or not event.target_id:
            return
        # Serialize cooldown reservations across PostgreSQL producer processes.
        target = session.scalar(select(Target).where(Target.id == event.target_id).with_for_update())
        if target is None: return
        now = utc_now()
        for recipient in self.config.recipients or ('',):
            existing = session.scalar(select(Notification.id).where(
                Notification.event_id == event.id, Notification.channel == 'email',
                Notification.recipient == recipient))
            if existing: continue
            configured = self.config.configured
            recent = session.scalar(select(Notification.id).where(
                Notification.target_id == event.target_id,
                Notification.camera_id == dto.camera_id,
                Notification.channel == 'email', Notification.recipient == recipient,
                Notification.status.in_(('pending', 'sent')),
                Notification.created_at > now - timedelta(seconds=self.config.cooldown)).limit(1))
            status = 'failed' if not configured else ('suppressed' if recent else 'pending')
            timestamp = event.created_at
            if timestamp.tzinfo is None: timestamp = timestamp.replace(tzinfo=timezone.utc)
            session.add(Notification(event_id=event.id, target_id=event.target_id,
                camera_id=dto.camera_id, channel='email', recipient=recipient,
                status=status, error='CONFIGURED=false' if not configured else ('cooldown' if recent else None),
                created_at=now, next_attempt_at=now, payload={
                    'event_id': str(event.id), 'target_id': str(event.target_id),
                    'target_name': dto.target_name or target.name, 'camera_id': dto.camera_id,
                    'event_time': timestamp.astimezone(timezone.utc).isoformat(),
                    'similarity': event.similarity, 'evidence_key': event.face_crop_path}))
            session.flush()

    def enqueue_vehicle(self, session, event, match):
        if match.decision != 'MATCH' or not match.watchlist_id or match.plate_event_id != event.id: return
        target=session.scalar(select(VehicleWatchlist).where(VehicleWatchlist.id==match.watchlist_id).with_for_update())
        if target is None or target.status != 'active': return
        now=utc_now()
        for recipient in self.config.recipients or ('',):
            if session.scalar(select(Notification.id).where(Notification.plate_event_id==event.id,
                Notification.channel=='email',Notification.recipient==recipient)): continue
            recent=session.scalar(select(Notification.id).where(Notification.vehicle_watchlist_id==target.id,
                Notification.camera_id==(match.camera_id or ''),Notification.channel=='email',Notification.recipient==recipient,
                Notification.status.in_(('pending','sent')),Notification.created_at>now-timedelta(seconds=self.config.cooldown)).limit(1))
            status='failed' if not self.config.configured else ('suppressed' if recent else 'pending')
            session.add(Notification(plate_event_id=event.id,vehicle_watchlist_id=target.id,
                camera_id=match.camera_id or '',channel='email',recipient=recipient,status=status,
                error='CONFIGURED=false' if not self.config.configured else ('cooldown' if recent else None),
                created_at=now,next_attempt_at=now,payload={
                    'alert_type':'VEHICLE_WATCHLIST_MATCH','event_id':str(event.id),
                    'plate_number':match.normalized_plate,'display_name':match.display_name,
                    'camera_id':match.camera_id,'event_time':event.created_at.isoformat(),
                    'confidence':event.confidence,'evidence_key':event.plate_crop_path}))
            session.flush()

    def deliver_one(self, now=None):
        if not self.config.configured: return False
        now = now or utc_now()
        # Lock through bounded SMTP delivery: other PostgreSQL workers skip this row.
        # No CV/persistence session is held here. Crash recovery is at-least-once.
        with self.db.transaction() as session:
            item = session.scalar(select(Notification).where(
                Notification.status == 'pending', Notification.next_attempt_at <= now
            ).order_by(Notification.created_at).with_for_update(skip_locked=True).limit(1))
            if item is None: return False
            if item.plate_event_id:
                event=session.get(PlateEvent,item.plate_event_id)
                match=session.scalar(select(VehicleWatchlistResult).where(VehicleWatchlistResult.plate_event_id==item.plate_event_id))
                qualifies=event is not None and match is not None and match.decision=='MATCH'
            else:
                event = session.get(FaceEvent, item.event_id)
                qualifies=event is not None and event.decision=='FACE_MATCH' and event.target_id is not None
            if not qualifies:
                item.status, item.error = 'suppressed', 'event_not_match'
                return True
            try:
                self.adapters[item.channel].send(item)
            except Exception:
                # Never retain provider exception text (may contain credentials).
                item.error = 'delivery_failed'
                if item.retry_count >= self.config.max_retries:
                    item.status = 'failed'
                else:
                    item.retry_count += 1
                    item.next_attempt_at = now + timedelta(seconds=min(
                        3600, self.config.retry_seconds * 2 ** (item.retry_count - 1)))
            else:
                item.status, item.sent_at, item.error = 'sent', utc_now(), None
        return True

    def start(self):
        if not self.config.configured or self._thread is not None: return
        def loop():
            while not self._stop.is_set():
                try:
                    if self.deliver_one(): continue
                except Exception:
                    log.warning('[NOTIFICATIONS] worker unavailable; check migration/configuration')
                self._stop.wait(1)
        self._thread = threading.Thread(target=loop, name='NotificationEmailWorker', daemon=True)
        self._thread.start()

    def stop(self, timeout=1):
        self._stop.set()
        if self._thread: self._thread.join(timeout=timeout)
