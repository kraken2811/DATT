"""Durable face-match notification history and outbox."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('notifications',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('event_id', sa.Uuid(), sa.ForeignKey('face_events.id', ondelete='CASCADE'), nullable=False),
        sa.Column('target_id', sa.Uuid(), sa.ForeignKey('targets.id', ondelete='SET NULL'), nullable=True),
        sa.Column('camera_id', sa.String(255), nullable=False),
        sa.Column('channel', sa.String(30), nullable=False),
        sa.Column('recipient', sa.String(320), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('retry_count', sa.Integer(), nullable=False),
        sa.Column('error', sa.String(100)),
        sa.Column('payload', sa.JSON().with_variant(JSONB(), 'postgresql'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('event_id', 'channel', 'recipient', name='uq_notifications_event_channel_recipient'),
        sa.CheckConstraint("status IN ('pending','sent','failed','suppressed')", name='notification_status'))
    op.create_index('ix_notifications_due', 'notifications', ['status', 'next_attempt_at'])
    op.create_index('ix_notifications_cooldown', 'notifications', ['target_id', 'camera_id', 'created_at'])


def downgrade():
    op.drop_index('ix_notifications_cooldown', table_name='notifications')
    op.drop_index('ix_notifications_due', table_name='notifications')
    op.drop_table('notifications')
