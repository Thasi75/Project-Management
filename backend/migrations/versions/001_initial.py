"""Initial V1.1 confirmed domain schema."""
from alembic import op
from pathlib import Path

revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Frozen SQL prevents future model edits from silently changing this historical migration.
    sql = Path(__file__).with_name('001_schema.sql').read_text('utf-8')
    for statement in sql.split(';'):
        if statement.strip():
            op.get_bind().exec_driver_sql(statement)


def downgrade():
    tables = ['generation_jobs','brief_versions','briefs','idempotency_keys','entity_revisions','attachment_links',
              'attachments','change_task_links','participants','risks','work_logs','tasks','project_scope_versions',
              'requirement_changes','project_modules','project_members','projects','people']
    for table in tables:
        op.drop_table(table)
