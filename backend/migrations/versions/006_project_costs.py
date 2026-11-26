"""Direct project expenses, stored exactly in integer cents."""
from alembic import op
import sqlalchemy as sa

revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('project_costs',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('project_id', sa.String(), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('code', sa.String(), nullable=False, unique=True),
        sa.Column('deleted', sa.Boolean(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.Column('expense_item', sa.String(), nullable=False),
        sa.Column('amount_cents', sa.BigInteger(), nullable=False),
        sa.UniqueConstraint('id', 'project_id'),
        sa.CheckConstraint('amount_cents >= 0 AND amount_cents <= 9999999999999999', name='ck_cost_amount'),
        sa.CheckConstraint("expense_item IN ('省际交通费','市内交通费','住宿费','业务招待费','其他')", name='ck_cost_expense_item'))
    op.create_index('ix_project_costs_project_id', 'project_costs', ['project_id'])
    op.create_index('ix_project_costs_expense_item', 'project_costs', ['expense_item'])


def downgrade():
    raise RuntimeError('请恢复升级前完整备份及对应代码，避免丢失项目费用记录。')
