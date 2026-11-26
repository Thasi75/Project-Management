"""Project-scoped requirements research; existing records remain unchanged."""
from alembic import op
import sqlalchemy as sa

revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('requirement_research',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('project_id', sa.String(), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('code', sa.String(), nullable=False, unique=True),
        sa.Column('deleted', sa.Boolean(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('research_date', sa.String(), nullable=False),
        sa.Column('module_id', sa.String(), nullable=False),
        sa.Column('source_id', sa.String(), nullable=False),
        sa.Column('recorder_id', sa.String(), nullable=False),
        sa.Column('importance', sa.String(), nullable=False),
        sa.Column('responded', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.UniqueConstraint('id', 'project_id'),
        sa.ForeignKeyConstraint(['module_id', 'project_id'], ['project_modules.id', 'project_modules.project_id']),
        sa.ForeignKeyConstraint(['source_id', 'project_id'], ['project_members.person_id', 'project_members.project_id']),
        sa.ForeignKeyConstraint(['recorder_id', 'project_id'], ['project_members.person_id', 'project_members.project_id']),
        sa.CheckConstraint('sequence >= 1 AND sequence <= 2147483647', name='ck_research_sequence'),
        sa.CheckConstraint("importance IN ('高','中','低')", name='ck_research_importance'),
        sa.CheckConstraint("responded IN ('是','否')", name='ck_research_responded'),
        sa.CheckConstraint("status IN ('设计','开发','上线')", name='ck_research_status'))
    for field in ('project_id', 'research_date', 'status', 'sequence'):
        op.create_index('ix_requirement_research_' + field, 'requirement_research', [field])


def downgrade():
    raise RuntimeError('请恢复升级前完整备份及对应代码，避免丢失需求调研记录。')
