"""Remove citation identities when their evidence is deleted."""

from alembic import op

revision = "0003_citation_cleanup"
down_revision = "0002_deferred_references"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    DO $$DECLARE item record; BEGIN
      FOR item IN SELECT conname FROM pg_constraint
        WHERE conrelid='app.citation_records'::regclass AND contype='f'
      LOOP
        EXECUTE format('ALTER TABLE app.citation_records DROP CONSTRAINT %I',item.conname);
      END LOOP;
    END$$;
    ALTER TABLE app.citation_records ADD CONSTRAINT citation_evidence_fk
      FOREIGN KEY (workspace_id,source_id,segment_id,anchor_id)
      REFERENCES app.segment_evidence ON DELETE CASCADE;
    """)


def downgrade():
    op.execute("""
    ALTER TABLE app.citation_records DROP CONSTRAINT citation_evidence_fk;
    ALTER TABLE app.citation_records ADD CONSTRAINT citation_evidence_fk
      FOREIGN KEY (workspace_id,source_id,segment_id,anchor_id)
      REFERENCES app.segment_evidence DEFERRABLE INITIALLY DEFERRED;
    """)
