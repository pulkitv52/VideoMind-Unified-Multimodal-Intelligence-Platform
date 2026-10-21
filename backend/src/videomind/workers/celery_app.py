from celery import Celery
import logging
from videomind.infrastructure import telemetry  # Register correlation signals.
from videomind.config import get_settings

app = Celery("videomind", broker=get_settings().redis_url.get_secret_value())
app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    broker_transport_options={
        "visibility_timeout": 3600,
        "priority_steps": [0, 3, 6, 9],
        "queue_order_strategy": "priority",
        "socket_connect_timeout": 2,
        "socket_timeout": 3,
    },
    task_soft_time_limit=3000,
    task_time_limit=3300,
    task_ignore_result=True,
    worker_hijack_root_logger=False,
)

telemetry.LOGGER.setLevel(logging.INFO)
if not telemetry.LOGGER.handlers:
    telemetry.LOGGER.addHandler(logging.StreamHandler())
telemetry.LOGGER.propagate = False


@app.task(name="videomind.intake", acks_late=True, reject_on_worker_lost=True)
def intake(workspace_id, source_id, job_id):
    from videomind.ingestion.worker import execute

    execute(workspace_id, source_id, job_id)
