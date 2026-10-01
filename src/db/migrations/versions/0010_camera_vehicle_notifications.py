"""Camera management metadata and shared vehicle notification outbox."""
from alembic import op
import sqlalchemy as sa
revision='0010'
down_revision='0009'
branch_labels=None
depends_on=None


def upgrade():
    with op.batch_alter_table('cameras') as b:
        b.add_column(sa.Column('registry_key',sa.String(255)))
        b.add_column(sa.Column('description',sa.Text()))
        b.add_column(sa.Column('thumbnail_path',sa.Text()))
        b.add_column(sa.Column('last_active',sa.DateTime(timezone=True)))
        b.add_column(sa.Column('active_token',sa.String(64)))
        b.add_column(sa.Column('active_until',sa.DateTime(timezone=True)))
        b.add_column(sa.Column('video_source_id',sa.Uuid()))
        b.create_unique_constraint('uq_cameras_registry_key',['registry_key'])
        b.create_foreign_key('fk_cameras_video_source_id_video_sources','video_sources',['video_source_id'],['id'],ondelete='RESTRICT')
    op.add_column('face_events',sa.Column('camera_id',sa.String(255)))
    op.create_index('ix_face_events_camera_id','face_events',['camera_id'])
    with op.batch_alter_table('notifications') as b:
        b.alter_column('event_id',existing_type=sa.Uuid(),nullable=True)
        b.add_column(sa.Column('plate_event_id',sa.Uuid()))
        b.add_column(sa.Column('vehicle_watchlist_id',sa.Uuid()))
        b.create_foreign_key('fk_notifications_plate_event_id_plate_events','plate_events',['plate_event_id'],['id'],ondelete='CASCADE')
        b.create_foreign_key('fk_notifications_vehicle_watchlist_id_vehicle_watchlists','vehicle_watchlists',['vehicle_watchlist_id'],['id'],ondelete='SET NULL')
        b.create_unique_constraint('uq_notifications_plate_channel_recipient',['plate_event_id','channel','recipient'])
        b.create_check_constraint('notification_event_kind','(event_id IS NOT NULL AND plate_event_id IS NULL) OR (event_id IS NULL AND plate_event_id IS NOT NULL)')
        b.create_index('ix_notifications_vehicle_cooldown',['vehicle_watchlist_id','camera_id','created_at'])


def downgrade():
    raise RuntimeError('Data-preserving downgrade requires archiving vehicle notifications first')
