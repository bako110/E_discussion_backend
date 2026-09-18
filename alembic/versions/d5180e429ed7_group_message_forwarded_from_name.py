"""add forwarded_from_name to group_messages and messages

Revision ID: d5180e429ed7
Revises: ff0dbab03255
Create Date: 2026-09-18 00:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'd5180e429ed7'
down_revision: str | Sequence[str] | None = 'ff0dbab03255'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # nom de l'auteur ORIGINAL d'un message transféré, dénormalisé au moment
    # du transfert — l'origine peut être un message de groupe OU 1-1, aucune
    # des deux FK forwarded_from_id existantes ne permet de la résoudre de
    # façon fiable côté serveur (voir commentaires sur les deux modèles).
    op.add_column(
        'group_messages', sa.Column('forwarded_from_name', sa.String(length=160), nullable=True)
    )
    op.add_column(
        'messages', sa.Column('forwarded_from_name', sa.String(length=160), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('messages', 'forwarded_from_name')
    op.drop_column('group_messages', 'forwarded_from_name')
