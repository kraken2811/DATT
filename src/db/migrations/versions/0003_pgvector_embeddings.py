"""Add pgvector extension and target_embeddings table for 512D ArcFace embeddings."""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    op.create_table(
        "target_embeddings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("embedding", Vector(512), nullable=False),
        sa.Column("model_name", sa.String(255), nullable=False),
        sa.Column("model_version", sa.String(255), nullable=True),
        sa.Column("source_image_path", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_target_embeddings"),
        sa.ForeignKeyConstraint(
            ["target_id"],
            ["targets.id"],
            name="fk_target_embeddings_target_id_targets",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_target_embeddings_target_id", "target_embeddings", ["target_id"])


def downgrade():
    op.drop_index("ix_target_embeddings_target_id", table_name="target_embeddings")
    op.drop_table("target_embeddings")
