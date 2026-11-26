"""Project communication with one linked work log; work-log modules become optional."""
from alembic import op
import sqlalchemy as sa

revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade():
    # No existing table references work_logs; rebuild before creating the new foreign key.
    with op.batch_alter_table('work_logs') as batch:
        batch.alter_column('module_id', existing_type=sa.String(), nullable=True)
    op.create_table('communications',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('project_id', sa.String(), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('code', sa.String(), nullable=False, unique=True),
        sa.Column('deleted', sa.Boolean(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.Column('occurred_at', sa.String(), nullable=False),
        sa.Column('host_id', sa.String(), nullable=False),
        sa.Column('recorder_id', sa.String(), nullable=False),
        sa.Column('log_id', sa.String(), nullable=False, unique=True),
        sa.UniqueConstraint('id', 'project_id'),
        sa.ForeignKeyConstraint(['host_id', 'project_id'], ['project_members.person_id', 'project_members.project_id']),
        sa.ForeignKeyConstraint(['recorder_id', 'project_id'], ['project_members.person_id', 'project_members.project_id']),
        sa.ForeignKeyConstraint(['log_id', 'project_id'], ['work_logs.id', 'work_logs.project_id']))
    op.create_index('ix_communications_project_id', 'communications', ['project_id'])
    op.create_index('ix_communications_occurred_at', 'communications', ['occurred_at'])


def downgrade():
    raise RuntimeError('请恢复升级前的完整备份及代码，避免丢失沟通关联或将未指定模块的日志错误归类。')
