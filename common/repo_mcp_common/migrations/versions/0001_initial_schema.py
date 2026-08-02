"""Initial configuration schema.

Transcribed explicitly rather than generated from the model metadata. The
first version of this revision called `Base.metadata.create_all`, which was
neat until the second revision added a table — revision one then created it
too, and revision two failed on a table that already existed. A migration has
to describe the schema *at its own point in history*, not the schema as the
code currently imagines it.

Revision ID: 0001
Revises:
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'admin_users',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('username', sa.String(64), nullable=False),
        sa.Column('password_hash', sa.Text(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('must_change_password', sa.Boolean(), nullable=False),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index('ix_admin_users_username', 'admin_users', ['username'], unique=True)
    op.create_table(
        'secrets',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('name', sa.String(128), nullable=False),
        sa.Column('ciphertext', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index('ix_secrets_name', 'secrets', ['name'], unique=True)
    op.create_table(
        'tenants',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('name', sa.String(64), nullable=False),
        sa.Column('tool_profile', sa.String(16), nullable=False),
        sa.Column('structural_only', sa.Boolean(), nullable=False),
        sa.Column('denied_tools', sa.JSON(), nullable=False),
        sa.Column('litellm_key_secret', sa.String(128), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index('ix_tenants_name', 'tenants', ['name'], unique=True)
    op.create_table(
        'tenant_ldap_groups',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column(
            'tenant_id',
            sa.Integer(),
            sa.ForeignKey('tenants.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('group_name', sa.String(128), nullable=False),
        sa.UniqueConstraint('group_name', name='uq_tenant_ldap_group'),
    )
    op.create_index(
        'ix_tenant_ldap_groups_group_name',
        'tenant_ldap_groups',
        ['group_name'],
        unique=False,
    )
    op.create_table(
        'tenant_projects',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column(
            'tenant_id',
            sa.Integer(),
            sa.ForeignKey('tenants.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('pattern', sa.String(256), nullable=False),
        sa.UniqueConstraint('tenant_id', 'pattern', name='uq_tenant_project'),
    )
    op.create_table(
        'role_assignments',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('role', sa.String(32), nullable=False),
        sa.Column('group_name', sa.String(128), nullable=False),
        sa.UniqueConstraint('role', 'group_name', name='uq_role_group'),
    )
    op.create_index(
        'ix_role_assignments_group_name',
        'role_assignments',
        ['group_name'],
        unique=False,
    )
    op.create_index('ix_role_assignments_role', 'role_assignments', ['role'], unique=False)
    op.create_table(
        'connectors',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('name', sa.String(64), nullable=False),
        sa.Column('provider', sa.String(32), nullable=False),
        sa.Column(
            'tenant_id',
            sa.Integer(),
            sa.ForeignKey('tenants.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('settings', sa.JSON(), nullable=False),
        sa.Column('token_secret', sa.String(128), nullable=True),
        sa.Column('include', sa.JSON(), nullable=False),
        sa.Column('exclude', sa.JSON(), nullable=False),
        sa.Column('mode', sa.String(32), nullable=False),
        sa.Column('persistence', sa.Boolean(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index('ix_connectors_name', 'connectors', ['name'], unique=True)
    op.create_table(
        'settings',
        sa.Column('key', sa.String(128), nullable=False, primary_key=True),
        sa.Column('value', sa.JSON(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_table(
        'config_generation',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('generation', sa.Integer(), nullable=False),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_table(
        'admin_audit',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('actor', sa.String(128), nullable=False),
        sa.Column('action', sa.String(64), nullable=False),
        sa.Column('target', sa.String(256), nullable=True),
        sa.Column('detail', sa.JSON(), nullable=True),
    )
    op.create_index('ix_admin_audit_at', 'admin_audit', ['at'], unique=False)

def downgrade() -> None:
    op.drop_table('admin_audit')
    op.drop_table('config_generation')
    op.drop_table('settings')
    op.drop_table('connectors')
    op.drop_table('role_assignments')
    op.drop_table('tenant_projects')
    op.drop_table('tenant_ldap_groups')
    op.drop_table('tenants')
    op.drop_table('secrets')
    op.drop_table('admin_users')
