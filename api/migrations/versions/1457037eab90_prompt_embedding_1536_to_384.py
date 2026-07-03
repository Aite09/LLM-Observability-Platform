"""prompt_embedding 1536 to 384

Destructive: drop/recreate discards existing 1536-dim embeddings (downgrade
cannot restore them). Regenerate via the embedding worker after upgrade.

Revision ID: 1457037eab90
Revises: 8bb1b8aa8a55
Create Date: 2026-07-03 15:10:03.606559

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = '1457037eab90'
down_revision: Union[str, None] = '8bb1b8aa8a55'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE on vector dims is not supported — drop/recreate the column.
    op.drop_column("llm_logs", "prompt_embedding")
    op.add_column("llm_logs", sa.Column("prompt_embedding", Vector(dim=384), nullable=True))


def downgrade() -> None:
    op.drop_column("llm_logs", "prompt_embedding")
    op.add_column("llm_logs", sa.Column("prompt_embedding", Vector(dim=1536), nullable=True))
