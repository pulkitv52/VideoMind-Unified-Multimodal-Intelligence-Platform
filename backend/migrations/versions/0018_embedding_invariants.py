"""Keep generation identities immutable and image-only null page text explicit."""

from alembic import op

revision = "0018_embedding_invariants"
down_revision = "0017_native_images"


def upgrade():
    op.execute("""
    ALTER TABLE app.document_pages DROP CONSTRAINT page_text_or_native_image;
    ALTER TABLE app.document_pages ADD CONSTRAINT page_text_or_native_image CHECK(text_object_id IS NOT NULL OR coalesce(manifest->>'kind'='image' AND image_object_id IS NOT NULL,false));
    CREATE FUNCTION app.generation_identity_unchanged() RETURNS trigger LANGUAGE plpgsql SET search_path='' AS $$
    BEGIN
      IF NEW.profile_id IS DISTINCT FROM OLD.profile_id OR NEW.requested_by IS DISTINCT FROM OLD.requested_by THEN
        RAISE EXCEPTION 'generation profile and producer identity are immutable';
      END IF;
      RETURN NEW;
    END$$;
    REVOKE ALL ON FUNCTION app.generation_identity_unchanged() FROM PUBLIC;
    CREATE TRIGGER generation_identity_unchanged BEFORE UPDATE ON app.index_generations FOR EACH ROW EXECUTE FUNCTION app.generation_identity_unchanged();
    """)


def downgrade():
    raise RuntimeError("Preserve immutable generation identity")
