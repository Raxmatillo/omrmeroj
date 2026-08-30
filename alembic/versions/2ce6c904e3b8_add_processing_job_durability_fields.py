"""add processing job durability fields

Revision ID: 2ce6c904e3b8
Revises: b3f7a2c4d8e1
Create Date: 2026-08-28 15:44:56.036588

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2ce6c904e3b8'
down_revision: Union[str, Sequence[str], None] = 'b3f7a2c4d8e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # service_requests avvalgi migratsiyada borligi uchun olib tashlandi
    # faqat processing_jobs yangilanadi:
    with op.batch_alter_table('processing_jobs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('payload_json', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('result_json', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    with op.batch_alter_table('processing_jobs', schema=None) as batch_op:
        batch_op.drop_column('attempts')
        batch_op.drop_column('result_json')
        batch_op.drop_column('payload_json')