from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


def database(url: str) -> Engine:
    return create_engine(
        url,
        pool_size=3,
        max_overflow=1,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 3},
        hide_parameters=True,
    )


@contextmanager
def transaction(engine: Engine, actor_id: UUID | None = None):
    with engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('videomind.actor_id', :actor, true)"),
            {"actor": str(actor_id) if actor_id else ""},
        )
        yield connection
