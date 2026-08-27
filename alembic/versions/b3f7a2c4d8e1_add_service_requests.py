"""add service requests

Revision ID: b3f7a2c4d8e1
Revises: 84e45aeb93c9
Create Date: 2026-08-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3f7a2c4d8e1'
down_revision: Union[str, Sequence[str], None] = '3893f7961221'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'service_requests',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('telegram_id', sa.String(), nullable=False),
        sa.Column('username', sa.String(), nullable=True),
        sa.Column('full_name', sa.String(), nullable=True),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('status', sa.Enum('pending', 'in_progress', 'done', 'cancelled',
                                     name='servicerequeststatus'), nullable=False),
        sa.Column('payment_status', sa.Enum('unpaid', 'paid', name='paymentstatus'), nullable=False),
        sa.Column('admin_note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_service_requests_telegram_id'), 'service_requests', ['telegram_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_service_requests_telegram_id'), table_name='service_requests')
    op.drop_table('service_requests')
