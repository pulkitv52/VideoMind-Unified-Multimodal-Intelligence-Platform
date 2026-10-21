"""Immutable initial schema snapshot; later changes get new revisions."""

from pathlib import Path
from alembic import op

revision = "0001_foundation"
down_revision = None


def upgrade():
    sql = (Path(__file__).parents[1] / "sql/0001_foundation.sql").read_text()
    op.get_bind().connection.driver_connection.execute(sql, prepare=False)


def downgrade():
    op.execute("DROP SCHEMA app CASCADE")
    op.execute("DROP SCHEMA auth CASCADE")
