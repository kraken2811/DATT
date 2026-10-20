"""System settings table for configurable runtime parameters.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-20
"""
from alembic import op
import sqlalchemy as sa

revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'system_settings',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('crowd_threshold', sa.Integer(), nullable=False, server_default='50'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table('system_settings')
