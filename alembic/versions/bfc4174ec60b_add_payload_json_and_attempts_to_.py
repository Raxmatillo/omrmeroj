"""add attempts to processing_jobs

Revision ID: bfc4174ec60b
Revises: d2076c33b8a3
Create Date: 2026-09-01 12:47:25.087942

DIQQAT: bu fayl QO'LDA TUZATILDI -- avtomatik yaratilgan asl versiyada
`fans` jadvalini qaytadan yaratish va `question_bank_items.fan_id`ni
qo'shish ham bor edi, lekin tekshiruv shuni ko'rsatdiki:
  - `fans` jadvali VA `processing_jobs.payload_json` ALLAQACHON mavjud
    (boshqa yo'l bilan yaratilgan, alembic tarixida qayd etilmagan).
  - `question_bank_items.fan_id` esa ALOHIDA (ma'lumot ko'chirishni
    talab qiladigan) ish -- shu sababli bu migratsiyadan CHIQARIB
    TASHLANDI, uni alohida hal qilasiz.

Shu fayl endi FAQAT haqiqatan yo'q bo'lgan bitta narsani qo'shadi:
`processing_jobs.attempts`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bfc4174ec60b'
down_revision: Union[str, Sequence[str], None] = 'd2076c33b8a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('processing_jobs', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('attempts', sa.Integer(), nullable=False, server_default='0')
        )


def downgrade() -> None:
    with op.batch_alter_table('processing_jobs', schema=None) as batch_op:
        batch_op.drop_column('attempts')