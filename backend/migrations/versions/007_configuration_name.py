"""Separate configuration item names from their owning project."""
from alembic import op
import sqlalchemy as sa

revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('project_configurations', sa.Column('config_name', sa.String(), nullable=False, server_default=''))
    # Preserve the name previously displayed, including archived/removed records.
    # Leave original fields, versions, revisions and saved brief snapshots untouched.
    op.execute('''UPDATE project_configurations
                  SET config_name = (SELECT name FROM projects
                                     WHERE projects.id = project_configurations.project_id)''')


def downgrade():
    raise RuntimeError('请恢复升级前完整备份及对应代码，避免丢失手工登记的配置项目名称。')
