"""Answer cache and per-project index epoch.

Revision ID: 0002
Revises: 0001

Two tables. `project_index_state` records when a project's graph last changed;
`answer_cache` stores LLM answers keyed on that epoch, so a reindex retires
every stale answer in one step. See docs/adr/0009-answer-cache.md.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_index_state",
        sa.Column("tenant", sa.String(64), primary_key=True),
        sa.Column("project", sa.String(200), primary_key=True),
        sa.Column("epoch", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_commit", sa.String(64), nullable=True),
        sa.Column(
            "last_indexed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "answer_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant", sa.String(64), nullable=False),
        sa.Column("project", sa.String(200), nullable=False),
        sa.Column("tool", sa.String(64), nullable=False),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("question_hash", sa.String(64), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("answer_model", sa.String(128), nullable=False),
        sa.Column("embedding_model", sa.String(128), nullable=True),
        sa.Column("embedding", sa.LargeBinary(), nullable=True),
        sa.Column("embedding_dim", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_hit_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "tenant", "project", "tool", "epoch", "question_hash", name="uq_answer_cache_exact"
        ),
    )
    op.create_index("ix_answer_cache_created_at", "answer_cache", ["created_at"])
    # The candidate set for a semantic lookup, and the unit of invalidation.
    op.create_index(
        "ix_answer_cache_candidates", "answer_cache", ["tenant", "project", "tool", "epoch"]
    )


def downgrade() -> None:
    op.drop_index("ix_answer_cache_candidates", table_name="answer_cache")
    op.drop_index("ix_answer_cache_created_at", table_name="answer_cache")
    op.drop_table("answer_cache")
    op.drop_table("project_index_state")
