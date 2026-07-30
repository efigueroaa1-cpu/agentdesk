"""checkpoint_corrida: estados parciales de corrida batch (Soberania de Datos)

Revision ID: b5d2f8a1c0e4
Revises: a7f3c9d1e825
Create Date: 2026-07-30 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b5d2f8a1c0e4'
down_revision: Union[str, Sequence[str], None] = 'a7f3c9d1e825'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'checkpoint_corrida',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('corrida_id', sa.String(length=120), nullable=False),
        sa.Column('agente_id', sa.String(length=120), nullable=False),
        sa.Column('estado', sa.String(length=20), nullable=False),
        sa.Column('resultado_json', sa.Text(), nullable=False),
        sa.Column('ts', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('corrida_id', 'agente_id',
                            name='uq_checkpoint_corrida_agente'),
    )
    op.create_index(op.f('ix_checkpoint_corrida_corrida_id'),
                    'checkpoint_corrida', ['corrida_id'], unique=False)
    op.create_index(op.f('ix_checkpoint_corrida_agente_id'),
                    'checkpoint_corrida', ['agente_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_checkpoint_corrida_agente_id'),
                  table_name='checkpoint_corrida')
    op.drop_index(op.f('ix_checkpoint_corrida_corrida_id'),
                  table_name='checkpoint_corrida')
    op.drop_table('checkpoint_corrida')
