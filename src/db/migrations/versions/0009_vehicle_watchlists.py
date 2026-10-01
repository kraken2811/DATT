"""Persistent vehicle watchlist and PlateEvent lookup results."""
from alembic import op
import sqlalchemy as sa
import re

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('plate_events', sa.Column('normalized_plate', sa.String(100)))
    # Preserve old PlateEvent history; normalization does not change OCR text.
    bind = op.get_bind()
    events = sa.table('plate_events', sa.column('id', sa.Uuid()), sa.column('plate_text', sa.String()), sa.column('normalized_plate', sa.String()))
    if bind.dialect.name == 'postgresql':
        bind.execute(sa.text("UPDATE plate_events SET normalized_plate=upper(regexp_replace(coalesce(plate_text,''),'[^A-Za-z0-9]','','g'))"))
    else:
        last = None
        while True:
            query = sa.select(events.c.id, events.c.plate_text).order_by(events.c.id).limit(1000)
            if last is not None: query = query.where(events.c.id > last)
            rows = bind.execute(query).fetchall()
            if not rows: break
            for row in rows:
                bind.execute(events.update().where(events.c.id == row.id).values(normalized_plate=re.sub(r'[^A-Za-z0-9]', '', row.plate_text or '').upper()))
            last = rows[-1].id
    op.create_index('ix_plate_events_normalized_plate', 'plate_events', ['normalized_plate'])
    op.create_table('vehicle_watchlists',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('plate_number', sa.String(100), nullable=False),
        sa.Column('vehicle_type', sa.String(100), nullable=False),
        sa.Column('display_name', sa.String(255), nullable=False),
        sa.Column('owner_info', sa.Text(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('plate_number', name='uq_vehicle_watchlists_plate_number'),
        sa.CheckConstraint("status IN ('active','disabled')", name='vehicle_watchlist_status'))
    op.create_table('vehicle_watchlist_results',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('plate_event_id', sa.Uuid(), sa.ForeignKey('plate_events.id', ondelete='CASCADE'), nullable=False),
        sa.Column('watchlist_id', sa.Uuid(), sa.ForeignKey('vehicle_watchlists.id', ondelete='SET NULL')),
        sa.Column('normalized_plate', sa.String(100), nullable=False),
        sa.Column('decision', sa.String(20), nullable=False),
        sa.Column('display_name', sa.String(255)),
        sa.Column('camera_id', sa.String(255)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('plate_event_id', name='uq_vehicle_watchlist_results_plate_event_id'),
        sa.CheckConstraint("decision IN ('MATCH','NO_MATCH')", name='vehicle_watchlist_decision'))
    op.create_index('ix_vehicle_watchlist_results_watchlist_id', 'vehicle_watchlist_results', ['watchlist_id'])
    op.create_index('ix_vehicle_watchlist_results_normalized_plate', 'vehicle_watchlist_results', ['normalized_plate'])


def downgrade():
    op.drop_index('ix_plate_events_normalized_plate', table_name='plate_events')
    op.drop_column('plate_events', 'normalized_plate')
    op.drop_table('vehicle_watchlist_results')
    op.drop_table('vehicle_watchlists')
