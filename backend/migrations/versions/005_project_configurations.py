"""Project-scoped configuration records used as report sources."""
from alembic import op
import sqlalchemy as sa

revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('project_configurations',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('project_id', sa.String(), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('code', sa.String(), nullable=False, unique=True),
        sa.Column('deleted', sa.Boolean(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.Column('config_date', sa.String(), nullable=False),
        sa.UniqueConstraint('id', 'project_id'))
    op.create_index('ix_project_configurations_project_id', 'project_configurations', ['project_id'])
    op.create_index('ix_project_configurations_config_date', 'project_configurations', ['config_date'])


def downgrade():
    raise RuntimeError('请恢复升级前完整备份及对应代码，避免丢失项目配置记录。')
