# Local service logs

Service activity is written to these files while the local log collector runs:

```text
logs/
  backend/
    api.log
    worker.log
    dispatcher.log
    indexer.log
    embedding.log
  frontend/
    frontend.log
```

`python3 scripts/dev.py up` starts one background collector automatically;
`python3 scripts/dev.py down` stops it. To enable collection on an already
running stack, run `python3 scripts/service_logs.py start`. You can stop only the
collector with `python3 scripts/service_logs.py stop`. It must be started again
after a host reboot, normally by starting VideoMind. It reconnects if its Docker
log stream ends. Files contain events observed since the collector started;
reconnecting may repeat the last event. Empty service files mean that service
has not emitted a supported structured event.

Each service has a 5 MiB current file and up to three rotated backups (20 MiB per
service, 120 MiB total). Generated files and backups are ignored by Git and
excluded from Docker build contexts. Log directories are private to the local
user. Existing Docker console logs remain available separately.

Follow the main activity from the project root:

```bash
tail -F logs/backend/api.log logs/backend/worker.log logs/frontend/frontend.log
```

Backend files record existing structured HTTP request and Celery task events,
including request/trace IDs, status and timing where provided. Frontend files
record Nginx web requests (method, status, bytes sent). Browser JavaScript errors
remain in the browser's F12 Console; this does not send browser telemetry to the
server. Job-specific failure codes and processing progress remain in Library.
The collector does not turn a Celery SUCCESS event into a claim that the
underlying ingestion job succeeded; consult the job status for that outcome.

Only known structured event types and allowlisted numeric/UUID/enum fields are
persisted. URLs, source paths, filenames, query text, headers, credentials,
exception messages, stack traces and arbitrary process output are not copied.
Raw service output remains available with `docker compose --env-file .env -f
infra/compose/compose.yaml logs --tail=100 SERVICE` when deeper diagnosis is
needed. Nginx warning/error output is in that Docker stream, not the activity file.
