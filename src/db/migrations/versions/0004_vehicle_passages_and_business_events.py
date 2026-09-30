"""add vehicle_passages and business_events

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-30 09:10:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "vehicle_passages",
        sa.Column("camera_id", sa.String(length=255), nullable=False),
        sa.Column("zone_id", sa.String(length=100), nullable=True),
        sa.Column("track_id", sa.Integer(), nullable=False),
        sa.Column("session_key", sa.String(length=255), nullable=False),
        sa.Column("vehicle_type", sa.String(length=100), nullable=False),
        sa.Column("vehicle_color", sa.String(length=50), nullable=True),
        sa.Column("vehicle_type_confidence", sa.Float(), nullable=True),
        sa.Column("vehicle_color_confidence", sa.Float(), nullable=True),
        sa.Column("plate_text", sa.String(length=100), nullable=True),
        sa.Column("plate_status", sa.String(length=50), nullable=True),
        sa.Column("plate_confidence", sa.Float(), nullable=True),
        sa.Column("direction", sa.String(length=50), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("best_vehicle_image_path", sa.Text(), nullable=True),
        sa.Column("best_plate_image_path", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vehicle_passages")),
    )
    with op.batch_alter_table("vehicle_passages", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_vehicle_passages_camera_id"), ["camera_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_vehicle_passages_first_seen_at"), ["first_seen_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_vehicle_passages_plate_text"), ["plate_text"], unique=False)
        batch_op.create_index(batch_op.f("ix_vehicle_passages_session_key"), ["session_key"], unique=True)
        batch_op.create_index(batch_op.f("ix_vehicle_passages_track_id"), ["track_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_vehicle_passages_zone_id"), ["zone_id"], unique=False)
        batch_op.create_index("ix_vehicle_passages_cam_first_seen", ["camera_id", "first_seen_at"], unique=False)
        batch_op.create_index("ix_vehicle_passages_type_first_seen", ["vehicle_type", "first_seen_at"], unique=False)
        batch_op.create_index("ix_vehicle_passages_zone_first_seen", ["zone_id", "first_seen_at"], unique=False)

    op.create_table(
        "business_events",
        sa.Column("passage_id", sa.Uuid(), nullable=True),
        sa.Column("camera_id", sa.String(length=255), nullable=False),
        sa.Column("zone_id", sa.String(length=100), nullable=True),
        sa.Column("track_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("vehicle_type", sa.String(length=100), nullable=True),
        sa.Column("plate_text", sa.String(length=100), nullable=True),
        sa.Column("direction", sa.String(length=50), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("metadata", sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["passage_id"], ["vehicle_passages.id"], name=op.f("fk_business_events_passage_id_vehicle_passages"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_business_events")),
    )
    with op.batch_alter_table("business_events", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_business_events_camera_id"), ["camera_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_business_events_event_time"), ["event_time"], unique=False)
        batch_op.create_index(batch_op.f("ix_business_events_event_type"), ["event_type"], unique=False)
        batch_op.create_index(batch_op.f("ix_business_events_idempotency_key"), ["idempotency_key"], unique=True)
        batch_op.create_index(batch_op.f("ix_business_events_passage_id"), ["passage_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_business_events_plate_text"), ["plate_text"], unique=False)
        batch_op.create_index(batch_op.f("ix_business_events_track_id"), ["track_id"], unique=False)
        batch_op.create_index("ix_business_events_cam_time", ["camera_id", "event_time"], unique=False)


def downgrade():
    op.drop_table("business_events")
    op.drop_table("vehicle_passages")
