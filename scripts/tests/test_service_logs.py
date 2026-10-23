"""Security and rotation boundaries for persisted local activity."""

import importlib.util
import json
from pathlib import Path
from uuid import uuid4

spec = importlib.util.spec_from_file_location(
    "service_logs", Path(__file__).resolve().parents[1] / "service_logs.py"
)
logs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(logs)


def test_persists_correlation_without_source_content_or_credentials():
    trace = str(uuid4())
    event = logs.safe_event(
        "worker-1 | prefix "
        + json.dumps(
            {
                "event": "task_finished",
                "trace_id": trace,
                "state": "SUCCESS",
                "filename": "private.pdf",
                "password": "secret",
                "url": "https://private?token=secret",
            }
        )
    )
    assert event == {"event": "task_finished", "trace_id": trace, "state": "SUCCESS"}
    assert logs.safe_event("Traceback: private.pdf secret") is None
    assert logs.safe_event('{"event":"private contents","trace_id":"secret"}') is None


def test_rejects_arbitrary_strings_and_nonfinite_numbers_in_known_fields():
    assert logs.safe_event(
        json.dumps(
            {
                "event": "request",
                "request_id": "secret",
                "method": "private.pdf",
                "status": "secret",
                "duration_ms": float("nan"),
                "state": "private contents",
            }
        )
    ) == {"event": "request"}
    assert logs.safe_event("[not json") is None
    assert logs.safe_event('{"event":') is None
    assert logs.safe_event('{"event":[]}') is None
    assert logs.safe_event('{"event":"request","method":[],"state":{}}') == {
        "event": "request"
    }


def test_frontend_event_contains_only_safe_fields():
    assert logs.safe_event(
        '{"event":"web_request","method":"GET","status":200,"bytes_sent":42,"uri":"/private"}'
    ) == {
        "event": "web_request",
        "method": "GET",
        "status": 200,
        "bytes_sent": 42,
    }


def test_rotation_keeps_a_bounded_number_of_files(tmp_path, monkeypatch):
    monkeypatch.setattr(logs, "ROOT", tmp_path)
    writers = logs.loggers()
    handler = writers["api"].handlers[0]
    handler.maxBytes = 150
    for i in range(50):
        writers["api"].info(
            json.dumps({"event": "request", "status": 200, "sequence": i})
        )
    assert len(list((tmp_path / "logs/backend").glob("api.log*"))) == 4
    assert len(list((tmp_path / "logs/frontend").glob("frontend.log"))) == 1
    assert (tmp_path / "logs/backend").stat().st_mode & 0o777 == 0o700
    for writer in writers.values():
        for item in list(writer.handlers):
            item.close()
            writer.removeHandler(item)
