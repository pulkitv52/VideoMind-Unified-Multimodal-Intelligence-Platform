"""Native evidence for format-validated immutable standalone images."""

import hashlib
import json
from alembic import op

revision = "0017_native_images"
down_revision = "0016_published_revision"
CONFIG = {
    "version": "native-image-v1",
    "input": "validated-immutable-original",
    "orientation": "decoded-pixels-before-exif-rotation",
    "ocr": False,
    "max_pixels": 16000000,
}
PROFILE = hashlib.sha256(json.dumps(CONFIG, sort_keys=True).encode()).hexdigest()


def upgrade():
    sql = SQL.replace("PROFILE_VALUE", PROFILE).replace(
        "CONFIG_VALUE", json.dumps(CONFIG, sort_keys=True)
    )
    op.get_bind().connection.driver_connection.execute(sql, prepare=False)


def downgrade():
    raise RuntimeError("Preserve image evidence and citations")


SQL = r"""
CREATE INDEX embedding_input_cache ON app.embeddings(workspace_id,profile_id,(input_manifest->>'input_hash'));
ALTER TABLE app.document_pages ALTER COLUMN text_object_id DROP NOT NULL;
ALTER TABLE app.document_pages ADD CONSTRAINT page_text_or_native_image CHECK(text_object_id IS NOT NULL OR (manifest->>'kind'='image' AND image_object_id IS NOT NULL));
CREATE FUNCTION app.prepare_native_image() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE original uuid;mime text;run_id uuid;set_id uuid;seg uuid;anchor uuid;iw integer;ih integer;
BEGIN
 IF NEW.kind<>'validate' OR NEW.status<>'stored' OR NEW.processing_run_id IS NULL THEN RETURN NEW; END IF;
 IF app.actor_id() IS DISTINCT FROM NEW.requested_by OR NOT app.source_access(NEW.workspace_id,NEW.source_id,true)
 OR NOT EXISTS(SELECT FROM auth.principals WHERE id=NEW.requested_by AND NOT disabled) THEN RETURN NEW; END IF;
 PERFORM pg_catalog.pg_advisory_xact_lock_shared(814207312);
 PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(NEW.workspace_id::text,1));
 PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(NEW.workspace_id::text,501));
 SELECT o.id,o.mime_type INTO original,mime FROM app.asset_revisions r JOIN app.objects o ON (o.workspace_id,o.source_id,o.id)=(r.workspace_id,r.source_id,r.original_object_id)
 WHERE r.workspace_id=NEW.workspace_id AND r.source_id=NEW.source_id AND r.id=NEW.revision_id;
 IF mime NOT IN ('image/png','image/jpeg') THEN RETURN NEW; END IF;
 iw:=(NEW.manifest->'metadata'->>'width')::integer;ih:=(NEW.manifest->'metadata'->>'height')::integer;
 IF iw IS NULL OR ih IS NULL OR iw<=0 OR ih<=0 OR iw::bigint*ih>16000000 THEN RETURN NEW; END IF;
 run_id:=gen_random_uuid();set_id:=gen_random_uuid();seg:=gen_random_uuid();anchor:=gen_random_uuid();
 INSERT INTO app.processing_runs(workspace_id,source_id,id,revision_id,profile_hash,status,manifest)
 VALUES(NEW.workspace_id,NEW.source_id,run_id,NEW.revision_id,'PROFILE_VALUE','ready','{"kind":"image","native_only":true}') ON CONFLICT DO NOTHING;
 IF NOT FOUND THEN RETURN NEW; END IF;
 INSERT INTO app.stage_runs(workspace_id,source_id,processing_run_id,stage,configuration_hash,status,manifest)
 VALUES(NEW.workspace_id,NEW.source_id,run_id,'prepare_image','PROFILE_VALUE','stored','{"native_only":true}');
 INSERT INTO app.segment_sets(workspace_id,source_id,id,revision_id,processing_run_id,segmenter_profile,status,manifest)
 VALUES(NEW.workspace_id,NEW.source_id,set_id,NEW.revision_id,run_id,'PROFILE_VALUE','building',jsonb_build_object('kind','image','profile','PROFILE_VALUE','configuration','CONFIG_VALUE'::jsonb,'page_count',1,'search_inputs_ready',true,'searchable',false,'warnings','[]'::jsonb));
 INSERT INTO app.document_pages(workspace_id,source_id,segment_set_id,revision_id,page,image_object_id,width,height,manifest)
 VALUES(NEW.workspace_id,NEW.source_id,set_id,NEW.revision_id,1,original,iw,ih,'{"kind":"image","ocr":false,"lines":[]}');
 INSERT INTO app.segments(workspace_id,source_id,id,segment_set_id,revision_id,representation,ordinal,producer,derived_object_id)
 VALUES(NEW.workspace_id,NEW.source_id,seg,set_id,NEW.revision_id,'image',0,'native-image-v1',original);
 INSERT INTO app.evidence_anchors(workspace_id,source_id,id,revision_id,original_object_id,locator_kind,page,transform)
 VALUES(NEW.workspace_id,NEW.source_id,anchor,NEW.revision_id,original,'page',1,jsonb_build_object('kind','image','box',jsonb_build_array(0,0,1,1),'original_width',iw,'original_height',ih,'orientation','decoded-pixels-before-exif-rotation','profile','PROFILE_VALUE'));
 INSERT INTO app.segment_evidence(workspace_id,source_id,segment_id,anchor_id,revision_id,relation,producer)
 VALUES(NEW.workspace_id,NEW.source_id,seg,anchor,NEW.revision_id,'depicts','native-image-v1');
 INSERT INTO app.citation_records(workspace_id,source_id,segment_id,anchor_id) VALUES(NEW.workspace_id,NEW.source_id,seg,anchor);
 UPDATE app.segment_sets SET status='ready' WHERE workspace_id=NEW.workspace_id AND source_id=NEW.source_id AND id=set_id;
 RETURN NEW;
END$$;
REVOKE ALL ON FUNCTION app.prepare_native_image() FROM PUBLIC;
CREATE TRIGGER prepare_native_image AFTER INSERT OR UPDATE OF status ON app.ingestion_jobs FOR EACH ROW EXECUTE FUNCTION app.prepare_native_image();
DO $$DECLARE j record;previous text;BEGIN
 previous:=current_setting('videomind.actor_id',true);
 FOR j IN SELECT workspace_id,source_id,id,requested_by FROM app.ingestion_jobs WHERE kind='validate' AND status='stored' AND processing_run_id IS NOT NULL LOOP
  PERFORM set_config('videomind.actor_id',j.requested_by::text,true);
  UPDATE app.ingestion_jobs SET status=status WHERE workspace_id=j.workspace_id AND source_id=j.source_id AND id=j.id;
 END LOOP;
 PERFORM set_config('videomind.actor_id',coalesce(previous,''),true);
END$$;
"""
