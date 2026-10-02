"""Optional declared vehicle color; plate-only matching remains unchanged."""
from alembic import op
import sqlalchemy as sa

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('vehicle_watchlists', sa.Column('vehicle_color', sa.String(20), nullable=True))


def downgrade():
    op.drop_column('vehicle_watchlists', 'vehicle_color')
