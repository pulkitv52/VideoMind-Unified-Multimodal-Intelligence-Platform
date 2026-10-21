"""Published pointers are outputs, not desired-input change events."""

from alembic import op

revision = "0016_published_revision"
down_revision = "0015_index_revision_changes"


def upgrade():
    op.execute("DROP TRIGGER index_asset_change ON app.assets")
    op.execute(
        "CREATE TRIGGER index_asset_change AFTER INSERT OR UPDATE OF latest_revision_id,deleted ON app.assets FOR EACH ROW EXECUTE FUNCTION app.index_change()"
    )


def downgrade():
    raise RuntimeError("Keep published-pointer semantics")
