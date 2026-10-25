"""timestamps with time zone

sqlmodel >= 0.0.48 maps `datetime` fields to UTCDateTime (timestamptz) and
binds aware UTC values. Against the original `timestamp without time zone`
columns, Postgres casts each aware value to the session TimeZone's wall
clock and drops the offset; reading it back, sqlmodel labels it UTC — so on
a server whose TimeZone isn't UTC every timestamp shifts by the offset.

The plain `::timestamptz` cast reads the existing naive values in the
session TimeZone, which exactly reverses how they were written (the app and
`alembic upgrade` connect the same way). On a UTC server it's a no-op.

SQLite has no timezone-aware type (values are stored as UTC text), so this
migration only touches Postgres.

Revision ID: 9b4c1e7f2a60
Revises: 2e6f46083799
Create Date: 2026-10-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9b4c1e7f2a60'
down_revision: Union[str, Sequence[str], None] = '2e6f46083799'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = [
    ('user', 'created_at', False),
    ('chore', 'created_at', False),
    ('chore', 'updated_at', False),
    ('claim', 'submitted_at', False),
    ('claim', 'resolved_at', True),
    ('transaction', 'created_at', False),
]


def upgrade() -> None:
    """Upgrade schema."""
    if op.get_bind().dialect.name != 'postgresql':
        return
    for table, column, nullable in COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.DateTime(timezone=True),
            existing_type=sa.DateTime(),
            existing_nullable=nullable,
            postgresql_using=f'"{column}"::timestamptz',
        )


def downgrade() -> None:
    """Downgrade schema."""
    if op.get_bind().dialect.name != 'postgresql':
        return
    for table, column, nullable in COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.DateTime(),
            existing_type=sa.DateTime(timezone=True),
            existing_nullable=nullable,
            postgresql_using=f'"{column}"::timestamp',
        )
