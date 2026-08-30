"""test bank

Revision ID: ef8e52db2f99
Revises: 94472c55d2d9
Create Date: 2026-08-30 22:41:43.959294

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ef8e52db2f99'
down_revision: Union[str, Sequence[str], None] = '94472c55d2d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # exam_students
    with op.batch_alter_table('exam_students', schema=None) as batch_op:
        batch_op.alter_column(
            'variant_id',
            existing_type=sa.VARCHAR(),
            nullable=True
        )

    # exams
    with op.batch_alter_table('exams', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('toplam_id', sa.String(), nullable=True)
        )

        batch_op.alter_column(
            'test_set_id',
            existing_type=sa.VARCHAR(),
            nullable=True
        )

        batch_op.create_foreign_key(
            'fk_exams_toplam_id_toplamlar',
            'toplamlar',
            ['toplam_id'],
            ['id']
        )

    # question_attempts
    with op.batch_alter_table('question_attempts', schema=None) as batch_op:
        batch_op.alter_column(
            'question_id',
            existing_type=sa.VARCHAR(),
            nullable=True
        )

        batch_op.create_index(
            'ix_question_attempts_bank_item_id',
            ['bank_item_id'],
            unique=False
        )

        batch_op.create_foreign_key(
            'fk_question_attempts_bank_item_id_question_bank_items',
            'question_bank_items',
            ['bank_item_id'],
            ['id']
        )


def downgrade() -> None:
    """Downgrade schema."""

    # question_attempts
    with op.batch_alter_table('question_attempts', schema=None) as batch_op:
        batch_op.drop_constraint(
            'fk_question_attempts_bank_item_id_question_bank_items',
            type_='foreignkey'
        )

        batch_op.drop_index(
            'ix_question_attempts_bank_item_id'
        )

        batch_op.alter_column(
            'question_id',
            existing_type=sa.VARCHAR(),
            nullable=False
        )

    # exams
    with op.batch_alter_table('exams', schema=None) as batch_op:
        batch_op.drop_constraint(
            'fk_exams_toplam_id_toplamlar',
            type_='foreignkey'
        )

        batch_op.alter_column(
            'test_set_id',
            existing_type=sa.VARCHAR(),
            nullable=False
        )

        batch_op.drop_column('toplam_id')

    # exam_students
    with op.batch_alter_table('exam_students', schema=None) as batch_op:
        batch_op.alter_column(
            'variant_id',
            existing_type=sa.VARCHAR(),
            nullable=False
        )