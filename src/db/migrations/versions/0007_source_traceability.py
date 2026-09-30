"""source traceability relationships for events

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-30 14:30:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    # 1. detection_events: make camera_id nullable for file/vod sources
    with op.batch_alter_table("detection_events", schema=None) as batch_op:
        batch_op.alter_column("camera_id", existing_type=sa.Uuid(), nullable=True)

    # 2. vehicle_events: add video_source_id FK
    with op.batch_alter_table("vehicle_events", schema=None) as batch_op:
        batch_op.add_column(sa.Column("video_source_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f("fk_vehicle_events_video_source_id_video_sources"),
            "video_sources",
            ["video_source_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            batch_op.f("ix_vehicle_events_video_source_id"),
            ["video_source_id"],
            unique=False,
        )

    # 3. face_events: add video_source_id, frame_id, make detection_event_id nullable
    with op.batch_alter_table("face_events", schema=None) as batch_op:
        batch_op.add_column(sa.Column("video_source_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("frame_id", sa.Integer(), nullable=True))
        batch_op.alter_column("detection_event_id", existing_type=sa.Uuid(), nullable=True)
        batch_op.create_foreign_key(
            batch_op.f("fk_face_events_video_source_id_video_sources"),
            "video_sources",
            ["video_source_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            batch_op.f("ix_face_events_video_source_id"),
            ["video_source_id"],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table("face_events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_face_events_video_source_id"))
        batch_op.drop_constraint(
            batch_op.f("fk_face_events_video_source_id_video_sources"),
            type_="foreignkey",
        )
        batch_op.alter_column("detection_event_id", existing_type=sa.Uuid(), nullable=False)
        batch_op.drop_column("frame_id")
        batch_op.drop_column("video_source_id")

    with op.batch_alter_table("vehicle_events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_vehicle_events_video_source_id"))
        batch_op.drop_constraint(
            batch_op.f("fk_vehicle_events_video_source_id_video_sources"),
            type_="foreignkey",
        )
        batch_op.drop_column("video_source_id")

    with op.batch_alter_table("detection_events", schema=None) as batch_op:
        batch_op.alter_column("camera_id", existing_type=sa.Uuid(), nullable=False)
