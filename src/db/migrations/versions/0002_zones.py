"""Add camera zones without changing existing event identifiers."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "zones",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("camera_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("polygon", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_zones"),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], name="fk_zones_camera_id_cameras", ondelete="RESTRICT"),
    )
    op.create_index("ix_zones_camera_id", "zones", ["camera_id"])


def downgrade():
    op.drop_index("ix_zones_camera_id", table_name="zones")
    op.drop_table("zones")
