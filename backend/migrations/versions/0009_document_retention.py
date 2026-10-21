"""Reclaim unreferenced document derivatives after asset retention."""

from alembic import op

revision = "0009_document_retention"
down_revision = "0008_documents"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE OR REPLACE FUNCTION app.retire_intake() RETURNS jsonb
      LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
    DECLARE sources_removed integer; assets_removed integer; objects_removed integer;
    BEGIN
      -- Caller holds the exclusive storage lock. A fixed one-hour retention
      -- floor cannot be shortened through the runtime function arguments.
      DELETE FROM app.sources WHERE (workspace_id,id) IN
        (SELECT workspace_id,id FROM app.sources WHERE deleted AND deleted_at<now()-interval '1 hour' LIMIT 32);
      GET DIAGNOSTICS sources_removed=ROW_COUNT;
      DELETE FROM app.assets a WHERE (workspace_id,source_id,id) IN
        (SELECT a.workspace_id,a.source_id,a.id FROM app.assets a WHERE a.deleted AND a.deleted_at<now()-interval '1 hour'
         AND NOT EXISTS(SELECT FROM app.generation_assets g WHERE (g.workspace_id,g.source_id,g.asset_id)=(a.workspace_id,a.source_id,a.id)) LIMIT 128);
      GET DIAGNOSTICS assets_removed=ROW_COUNT;
      DELETE FROM app.objects o WHERE (workspace_id,source_id,id) IN
        (SELECT o.workspace_id,o.source_id,o.id FROM app.objects o WHERE o.role='derivative' AND o.created_at<now()-interval '1 hour'
         AND NOT EXISTS(SELECT FROM app.document_pages p WHERE p.workspace_id=o.workspace_id AND p.source_id=o.source_id AND o.id IN (p.text_object_id,p.image_object_id,p.rendering_object_id))
         AND NOT EXISTS(SELECT FROM app.segments g WHERE (g.workspace_id,g.source_id,g.derived_object_id)=(o.workspace_id,o.source_id,o.id))
         AND NOT EXISTS(SELECT FROM app.evidence_anchors e WHERE e.workspace_id=o.workspace_id AND e.source_id=o.source_id AND o.id IN (e.original_object_id,e.text_artifact_id))
         AND NOT EXISTS(SELECT FROM app.segment_sets ss WHERE ss.workspace_id=o.workspace_id AND ss.source_id=o.source_id AND ss.manifest->>'structure_object_id'=o.id::text)
         AND NOT EXISTS(SELECT FROM app.objects d WHERE (d.workspace_id,d.source_id,d.derived_from_id)=(o.workspace_id,o.source_id,o.id)) LIMIT 128);
      DELETE FROM app.objects o WHERE (workspace_id,source_id,id) IN
        (SELECT o.workspace_id,o.source_id,o.id FROM app.objects o
         WHERE o.role='original' AND o.created_at<now()-interval '1 hour'
         AND NOT EXISTS(SELECT FROM app.asset_revisions r WHERE (r.workspace_id,r.source_id,r.original_object_id)=(o.workspace_id,o.source_id,o.id))
         AND NOT EXISTS(SELECT FROM app.evidence_anchors e WHERE e.workspace_id=o.workspace_id AND e.source_id=o.source_id AND (e.original_object_id=o.id OR e.text_artifact_id=o.id))
         AND NOT EXISTS(SELECT FROM app.objects d WHERE (d.workspace_id,d.source_id,d.derived_from_id)=(o.workspace_id,o.source_id,o.id)) LIMIT 128);
      GET DIAGNOSTICS objects_removed=ROW_COUNT;
      RETURN jsonb_build_object('sources',sources_removed,'assets',assets_removed,'object_rows',objects_removed);
    END$$;
    """)

    # Recover development-era document receipts that predated the extraction worker.
    # Successful extraction is defined by a complete, ready segment set.
    op.execute(
        """UPDATE app.ingestion_jobs j SET status='queued',attempt=0,error_code=NULL,
      lease_token=NULL,lease_expires_at=NULL,available_at=now(),manifest='{}'
      WHERE kind='document' AND NOT EXISTS(SELECT FROM app.segment_sets ss
        WHERE (ss.workspace_id,ss.source_id,ss.processing_run_id)=(j.workspace_id,j.source_id,j.processing_run_id) AND ss.status='ready')
      AND EXISTS(SELECT FROM app.sources s WHERE (s.workspace_id,s.id)=(j.workspace_id,j.source_id) AND NOT s.deleted)"""
    )


def downgrade():
    raise RuntimeError("Retention change requires a forward migration")
