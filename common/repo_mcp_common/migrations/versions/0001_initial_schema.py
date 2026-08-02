"""Initial configuration schema.

The initial revision creates the schema from the model metadata rather than
transcribing every table by hand. Revision one *is* the models; from here on
each change is an explicit, reviewable diff, which is the property
docs/adr/0006-configuration-in-the-database.md actually asks for.

Revision ID: 0001
Revises:
"""

from __future__ import annotations

from alembic import op

from repo_mcp_common.models import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
