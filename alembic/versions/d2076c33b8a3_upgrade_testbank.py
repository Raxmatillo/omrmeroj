"""upgrade testbank

Revision ID: d2076c33b8a3
Revises: ef8e52db2f99
Create Date: 2026-08-31 08:25:46.019210

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2076c33b8a3'
down_revision: Union[str, Sequence[str], None] = 'ef8e52db2f99'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
