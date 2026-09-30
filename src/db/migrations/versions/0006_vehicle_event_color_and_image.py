"""add vehicle_color and vehicle_image_path to vehicle_events

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-30 12:30:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vehicle_events", schema=None) as batch_op:
        batch_op.add_column(sa.Column("vehicle_color", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("vehicle_image_path", sa.Text(), nullable=True))
        batch_op.alter_column("detection_event_id", existing_type=sa.Uuid(), nullable=True)


def downgrade():
    with op.batch_alter_table("vehicle_events", schema=None) as batch_op:
        batch_op.alter_column("detection_event_id", existing_type=sa.Uuid(), nullable=False)
        batch_op.drop_column("vehicle_image_path")
        batch_op.drop_column("vehicle_color")
