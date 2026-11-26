"""Expense occurrence date and Token expense category."""
from alembic import op
import sqlalchemy as sa

revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade():
    # The table has no incoming foreign keys. Rebuild to extend the category
    # constraint while preserving every original field and integer-cent amount.
    with op.batch_alter_table('project_costs') as batch:
        batch.add_column(sa.Column('expense_date', sa.String(), nullable=True))
        batch.drop_constraint('ck_cost_expense_item', type_='check')
        batch.create_check_constraint('ck_cost_expense_item',
            "expense_item IN ('省际交通费','市内交通费','住宿费','业务招待费','Token','其他')")
        batch.create_index('ix_project_costs_expense_date', ['expense_date'])
    # Unknown legacy occurrence dates stay NULL; never substitute creation time.


def downgrade():
    raise RuntimeError('请恢复升级前完整备份及对应代码，避免丢失费用日期或 Token 费用。')
