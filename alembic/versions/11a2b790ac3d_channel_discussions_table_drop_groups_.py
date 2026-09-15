"""channel_discussions table, drop groups.discussion_group_id

Revision ID: 11a2b790ac3d
Revises: 051a997d9823
Create Date: 2026-09-15 17:34:27.968110
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.db.types import GUID

revision: str = '11a2b790ac3d'
down_revision: str | Sequence[str] | None = '051a997d9823'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'channel_discussions',
        sa.Column('channel_id', GUID(), nullable=False),
        sa.Column('discussion_group_id', GUID(), nullable=False),
        sa.Column('id', GUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['channel_id'], ['groups.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['discussion_group_id'], ['groups.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('channel_id', 'discussion_group_id', name='uq_channel_discussion'),
    )
    op.create_index(op.f('ix_channel_discussions_channel_id'), 'channel_discussions', ['channel_id'], unique=False)
    op.create_index(op.f('ix_channel_discussions_discussion_group_id'), 'channel_discussions', ['discussion_group_id'], unique=True)

    # migre les liaisons existantes (1-vers-1) vers la nouvelle table
    # 1-vers-N avant de supprimer la colonne — perte de données sinon.
    op.execute(
        """
        INSERT INTO channel_discussions (id, channel_id, discussion_group_id, created_at, updated_at)
        SELECT gen_random_uuid(), id, discussion_group_id, now(), now()
        FROM groups
        WHERE discussion_group_id IS NOT NULL
        """
    )

    op.drop_index('ix_groups_discussion_group_id', table_name='groups')
    op.drop_constraint('fk_groups_discussion_group_id', 'groups', type_='foreignkey')
    op.drop_column('groups', 'discussion_group_id')


def downgrade() -> None:
    op.add_column('groups', sa.Column('discussion_group_id', sa.UUID(), autoincrement=False, nullable=True))
    op.create_foreign_key('fk_groups_discussion_group_id', 'groups', 'groups', ['discussion_group_id'], ['id'], ondelete='SET NULL')
    op.create_index('ix_groups_discussion_group_id', 'groups', ['discussion_group_id'], unique=False)

    # ne restaure qu'UNE liaison par chaîne (perte de données si plusieurs
    # canaux avaient été liés depuis l'upgrade — le modèle 1-vers-1 ne peut
    # pas tous les représenter).
    op.execute(
        """
        UPDATE groups g
        SET discussion_group_id = cd.discussion_group_id
        FROM (
            SELECT DISTINCT ON (channel_id) channel_id, discussion_group_id
            FROM channel_discussions
            ORDER BY channel_id, created_at ASC
        ) cd
        WHERE g.id = cd.channel_id
        """
    )

    op.drop_index(op.f('ix_channel_discussions_discussion_group_id'), table_name='channel_discussions')
    op.drop_index(op.f('ix_channel_discussions_channel_id'), table_name='channel_discussions')
    op.drop_table('channel_discussions')
