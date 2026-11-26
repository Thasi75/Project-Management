"""Give every project membership an independent personnel profile, preserving IDs."""
from alembic import op
import sqlalchemy as sa

revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None

PROFILE_COLUMNS = ('name', 'team', 'notes', 'enabled', 'version', 'created_at', 'updated_at')


def upgrade():
    for name in PROFILE_COLUMNS:
        kind = sa.Boolean() if name == 'enabled' else sa.Integer() if name == 'version' else sa.String()
        default = '1' if name in ('enabled', 'version') else ''
        op.add_column('project_members', sa.Column(name, kind, nullable=False, server_default=default))
    # Copy by membership, not by name: shared identities get independent editable profiles.
    assignments = ', '.join(f'{name}=(SELECT {name} FROM people WHERE id=project_members.person_id)' for name in PROFILE_COLUMNS)
    op.get_bind().exec_driver_sql('UPDATE project_members SET ' + assignments)


def downgrade():
    for name in reversed(PROFILE_COLUMNS):
        op.drop_column('project_members', name)
