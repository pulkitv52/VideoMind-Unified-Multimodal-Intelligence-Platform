"""Bound file/job pagination and enforce one validation job per revision."""

from alembic import op

revision = "0007_intake_indexes"
down_revision = "0006_intake_completion"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
      CREATE INDEX assets_page ON app.assets(workspace_id,source_id,title,id) WHERE NOT deleted;
      CREATE INDEX jobs_page ON app.ingestion_jobs(workspace_id,source_id,created_at DESC,id DESC);
      CREATE UNIQUE INDEX revision_validation_job ON app.ingestion_jobs(workspace_id,source_id,revision_id) WHERE revision_id IS NOT NULL;
    """)


def downgrade():
    op.execute("DROP INDEX app.assets_page,app.jobs_page,app.revision_validation_job")
