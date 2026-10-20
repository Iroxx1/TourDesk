"""venue_listings

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-20 12:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('venue_listings',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('venue_id', sa.Integer(), nullable=False),
    sa.Column('source_id', sa.Integer(), nullable=False),
    sa.Column('listing_key', sa.String(length=255), nullable=False),
    sa.Column('event_date', sa.Date(), nullable=False),
    sa.Column('start_time', sa.Time(), nullable=True),
    sa.Column('title', sa.String(length=500), nullable=True),
    sa.Column('performers', postgresql.ARRAY(sa.Text()), nullable=False),
    sa.Column('artists', postgresql.ARRAY(sa.Text()), nullable=False),
    sa.Column('category', sa.String(length=80), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('url', sa.String(length=1000), nullable=True),
    sa.Column('ticket_url', sa.String(length=1000), nullable=True),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['venue_id'], ['venues.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source_id', 'listing_key')
    )
    op.create_index('ix_venue_listings_venue_date', 'venue_listings', ['venue_id', 'event_date'], unique=False)
    op.create_index(op.f('ix_venue_listings_source_id'), 'venue_listings', ['source_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_venue_listings_source_id'), table_name='venue_listings')
    op.drop_index('ix_venue_listings_venue_date', table_name='venue_listings')
    op.drop_table('venue_listings')
