"""Content-free correlation across HTTP requests and Celery messages."""

from contextvars import ContextVar
import json
import logging
from uuid import UUID, uuid4

from celery.signals import before_task_publish, task_postrun, task_prerun

trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)
LOGGER = logging.getLogger("videomind")


def correlation_id(value=None):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError):
        return str(uuid4())


@before_task_publish.connect
def publish_trace(headers=None, **kwargs):
    if headers is not None:
        headers["trace_id"] = correlation_id(trace_id.get() or headers.get("trace_id"))


@task_prerun.connect
def begin_task(task=None, **kwargs):
    headers = task.request.headers or {}
    value = correlation_id(headers.get("trace_id"))
    task.request.videomind_trace_token = trace_id.set(value)
    LOGGER.info(json.dumps({"event": "task_started", "trace_id": value}))


@task_postrun.connect
def end_task(task=None, state=None, **kwargs):
    LOGGER.info(
        json.dumps(
            {"event": "task_finished", "trace_id": trace_id.get(), "state": state}
        )
    )
    token = getattr(task.request, "videomind_trace_token", None)
    if token is not None:
        trace_id.reset(token)
