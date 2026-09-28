"""initial_schema"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('cameras',
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('source_type', sa.String(length=50), nullable=False),
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('location', sa.Text(), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_cameras'))
    )
    op.create_table('targets',
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('target_type', sa.String(length=50), nullable=False),
    sa.Column('embedding', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('reference_metadata', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('image_path', sa.Text(), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_targets'))
    )
    op.create_table('detection_events',
    sa.Column('camera_id', sa.Uuid(), nullable=False),
    sa.Column('event_type', sa.String(length=50), nullable=False),
    sa.Column('frame_id', sa.Integer(), nullable=False),
    sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
    sa.Column('track_id', sa.Integer(), nullable=True),
    sa.Column('class_name', sa.String(length=100), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('bbox', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('snapshot_path', sa.Text(), nullable=True),
    sa.Column('metadata', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['camera_id'], ['cameras.id'], name=op.f('fk_detection_events_camera_id_cameras'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_detection_events'))
    )
    with op.batch_alter_table('detection_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_detection_events_camera_id'), ['camera_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_detection_events_event_type'), ['event_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_detection_events_timestamp'), ['timestamp'], unique=False)
        batch_op.create_index(batch_op.f('ix_detection_events_track_id'), ['track_id'], unique=False)

    op.create_table('face_events',
    sa.Column('detection_event_id', sa.Uuid(), nullable=False),
    sa.Column('target_id', sa.Uuid(), nullable=True),
    sa.Column('track_id', sa.Integer(), nullable=True),
    sa.Column('similarity', sa.Float(), nullable=True),
    sa.Column('decision', sa.String(length=50), nullable=False),
    sa.Column('face_crop_path', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['detection_event_id'], ['detection_events.id'], name=op.f('fk_face_events_detection_event_id_detection_events'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['target_id'], ['targets.id'], name=op.f('fk_face_events_target_id_targets'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_face_events'))
    )
    with op.batch_alter_table('face_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_face_events_detection_event_id'), ['detection_event_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_face_events_target_id'), ['target_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_face_events_track_id'), ['track_id'], unique=False)

    op.create_table('vehicle_events',
    sa.Column('detection_event_id', sa.Uuid(), nullable=False),
    sa.Column('vehicle_class', sa.String(length=100), nullable=False),
    sa.Column('track_id', sa.Integer(), nullable=False),
    sa.Column('zone_id', sa.String(length=100), nullable=True),
    sa.Column('first_seen', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['detection_event_id'], ['detection_events.id'], name=op.f('fk_vehicle_events_detection_event_id_detection_events'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_vehicle_events'))
    )
    with op.batch_alter_table('vehicle_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_vehicle_events_detection_event_id'), ['detection_event_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_vehicle_events_track_id'), ['track_id'], unique=False)

    op.create_table('plate_events',
    sa.Column('vehicle_event_id', sa.Uuid(), nullable=False),
    sa.Column('plate_text', sa.String(length=100), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('plate_bbox', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('plate_crop_path', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['vehicle_event_id'], ['vehicle_events.id'], name=op.f('fk_plate_events_vehicle_event_id_vehicle_events'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_plate_events'))
    )
    with op.batch_alter_table('plate_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_plate_events_plate_text'), ['plate_text'], unique=False)
        batch_op.create_index(batch_op.f('ix_plate_events_vehicle_event_id'), ['vehicle_event_id'], unique=False)



def downgrade():
    with op.batch_alter_table('plate_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_plate_events_vehicle_event_id'))
        batch_op.drop_index(batch_op.f('ix_plate_events_plate_text'))

    op.drop_table('plate_events')
    with op.batch_alter_table('vehicle_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_vehicle_events_track_id'))
        batch_op.drop_index(batch_op.f('ix_vehicle_events_detection_event_id'))

    op.drop_table('vehicle_events')
    with op.batch_alter_table('face_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_face_events_track_id'))
        batch_op.drop_index(batch_op.f('ix_face_events_target_id'))
        batch_op.drop_index(batch_op.f('ix_face_events_detection_event_id'))

    op.drop_table('face_events')
    with op.batch_alter_table('detection_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_detection_events_track_id'))
        batch_op.drop_index(batch_op.f('ix_detection_events_timestamp'))
        batch_op.drop_index(batch_op.f('ix_detection_events_event_type'))
        batch_op.drop_index(batch_op.f('ix_detection_events_camera_id'))

    op.drop_table('detection_events')
    op.drop_table('targets')
    op.drop_table('cameras')
