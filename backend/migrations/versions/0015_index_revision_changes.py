"""Fence new revisions before their inputs become ready."""

from alembic import op

revision = "0015_index_revision_changes"
down_revision = "0014_index_change_fix"


def upgrade():
    op.execute(
        "CREATE TRIGGER index_revision_change AFTER INSERT ON app.asset_revisions FOR EACH ROW EXECUTE FUNCTION app.index_change()"
    )
    op.execute("UPDATE app.workspace_search_state SET content_epoch=content_epoch+1")


def downgrade():
    raise RuntimeError("Keep revision change tracking")
