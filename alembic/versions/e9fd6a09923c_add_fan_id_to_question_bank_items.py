# alembic/versions/e9fd6a09923c_add_fan_id_to_question_bank_items.py

"""Add fan_id to question_bank_items

Revision ID: e9fd6a09923c
Revises: bfc4174ec60b
Create Date: ...
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'e9fd6a09923c'
down_revision = 'bfc4174ec60b'
branch_labels = None
depends_on = None

def upgrade() -> None:
    with op.batch_alter_table('question_bank_items', schema=None) as batch_op:
        # Eski fan ustunini o'chirish
        batch_op.drop_column('fan')
        
        # Yangi fan_id ustunini qo'shish
        batch_op.add_column(sa.Column('fan_id', sa.String(), nullable=True))
        
        # ForeignKey constraint
        batch_op.create_foreign_key(
            'fk_question_bank_items_fan_id',
            'fans',
            ['fan_id'],
            ['id']
        )

def downgrade() -> None:
    with op.batch_alter_table('question_bank_items', schema=None) as batch_op:
        batch_op.drop_constraint('fk_question_bank_items_fan_id', type_='foreignkey')
        batch_op.drop_column('fan_id')
        batch_op.add_column(sa.Column('fan', sa.String(), nullable=False))