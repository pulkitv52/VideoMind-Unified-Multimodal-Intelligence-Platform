"""Validate cross-branch references at commit during workspace cascades."""

from alembic import op

revision = "0002_deferred_references"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    DO $$DECLARE item record; BEGIN
      FOR item IN
        SELECT n.nspname, c.relname, f.conname
        FROM pg_constraint f JOIN pg_class c ON c.oid=f.conrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='app' AND f.contype='f'
          AND f.confdeltype='a' AND NOT f.condeferrable
      LOOP
        EXECUTE format('ALTER TABLE %I.%I ALTER CONSTRAINT %I DEFERRABLE INITIALLY DEFERRED', item.nspname,item.relname,item.conname);
      END LOOP;
    END$$;
    """)


def downgrade():
    op.execute("""
    DO $$DECLARE item record; BEGIN
      FOR item IN
        SELECT n.nspname, c.relname, f.conname
        FROM pg_constraint f JOIN pg_class c ON c.oid=f.conrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='app' AND f.contype='f' AND f.confdeltype='a'
          AND f.conname<>'current_revision_same_asset'
      LOOP
        EXECUTE format('ALTER TABLE %I.%I ALTER CONSTRAINT %I NOT DEFERRABLE', item.nspname,item.relname,item.conname);
      END LOOP;
    END$$;
    """)
