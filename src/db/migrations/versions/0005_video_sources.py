"""add video_sources and video_source_id foreign keys

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-30 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "video_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="ready"),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("duration_sec", sa.Float(), nullable=True),
        sa.Column("fps", sa.Float(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column(
            "metadata",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_video_sources")),
    )
    with op.batch_alter_table("video_sources", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_video_sources_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_video_sources_status"), ["status"], unique=False)

    with op.batch_alter_table("detection_events", schema=None) as batch_op:
        batch_op.add_column(sa.Column("video_source_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f("fk_detection_events_video_source_id_video_sources"),
            "video_sources",
            ["video_source_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(batch_op.f("ix_detection_events_video_source_id"), ["video_source_id"], unique=False)

    with op.batch_alter_table("vehicle_passages", schema=None) as batch_op:
        batch_op.add_column(sa.Column("video_source_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f("fk_vehicle_passages_video_source_id_video_sources"),
            "video_sources",
            ["video_source_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(batch_op.f("ix_vehicle_passages_video_source_id"), ["video_source_id"], unique=False)

    with op.batch_alter_table("business_events", schema=None) as batch_op:
        batch_op.add_column(sa.Column("video_source_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f("fk_business_events_video_source_id_video_sources"),
            "video_sources",
            ["video_source_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(batch_op.f("ix_business_events_video_source_id"), ["video_source_id"], unique=False)


def downgrade():
    with op.batch_alter_table("business_events", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("fk_business_events_video_source_id_video_sources"), type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_business_events_video_source_id"))
        batch_op.drop_column("video_source_id")

    with op.batch_alter_table("vehicle_passages", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("fk_vehicle_passages_video_source_id_video_sources"), type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_vehicle_passages_video_source_id"))
        batch_op.drop_column("video_source_id")

    with op.batch_alter_table("detection_events", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("fk_detection_events_video_source_id_video_sources"), type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_detection_events_video_source_id"))
        batch_op.drop_column("video_source_id")

    with op.batch_alter_table("video_sources", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_video_sources_status"))
        batch_op.drop_index(batch_op.f("ix_video_sources_created_at"))

    op.drop_table("video_sources")
