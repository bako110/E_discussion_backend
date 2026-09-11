"""otppurpose : ajoute la valeur 'account_delete' (confirmation OTP avant
suppression definitive du compte)

Revision ID: b3d4e5f6a7b8
Revises: a2c3d4e5f6a7
Create Date: 2026-09-11

    alembic upgrade head
"""
from __future__ import annotations

from alembic import op

revision = "b3d4e5f6a7b8"
down_revision = "a2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE ne peut pas s'executer dans le bloc
    # transactionnel standard d'Alembic sur Postgres < 12 (et reste risque
    # au-dela si la meme transaction tente ensuite d'UTILISER la valeur) —
    # `autocommit_block()` sort explicitement de la transaction pour cette
    # seule commande.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE otppurpose ADD VALUE IF NOT EXISTS 'account_delete'")


def downgrade() -> None:
    # Postgres ne supporte pas DROP VALUE sur un enum — pas de downgrade
    # propre sans recreer tout le type. No-op assume (comme les autres
    # migrations d'enum de ce projet).
    pass
