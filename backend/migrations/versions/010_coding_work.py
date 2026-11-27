"""Project coding work, with exact positive integer minutes."""
from alembic import op
import sqlalchemy as sa

revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('coding_work',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('project_id', sa.String(), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('code', sa.String(), nullable=False, unique=True),
        sa.Column('deleted', sa.Boolean(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.Column('work_date', sa.String(), nullable=False),
        sa.Column('module_id', sa.String(), nullable=False),
        sa.Column('feature', sa.String(), nullable=False),
        sa.Column('duration_minutes', sa.Integer(), nullable=False),
        sa.UniqueConstraint('id', 'project_id'),
        sa.ForeignKeyConstraint(['module_id', 'project_id'], ['project_modules.id', 'project_modules.project_id']),
        sa.CheckConstraint('duration_minutes = CAST(duration_minutes AS INTEGER) AND duration_minutes >= 1 AND duration_minutes <= 2147483647', name='ck_coding_duration'))
    for field in ('project_id', 'work_date'):
        op.create_index('ix_coding_work_' + field, 'coding_work', [field])


def downgrade():
    raise RuntimeError('请恢复升级前完整备份及对应代码，避免丢失代码编写记录。')
