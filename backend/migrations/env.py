import os
from alembic import context
from sqlalchemy import create_engine

url = os.environ["VM_MIGRATION_DATABASE_URL"]
engine = create_engine(url, hide_parameters=True)
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
