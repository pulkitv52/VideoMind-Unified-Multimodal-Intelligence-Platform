"""Operator-only actual-route timing. Emits statement categories, never content."""

import json
import subprocess
from evaluation.quality.recovery import command

PROBE = """
import hashlib,json,sys,time
from types import SimpleNamespace
from uuid import UUID
from sqlalchemy import event
from sqlalchemy.engine import make_url
from videomind.config import Settings
from videomind.infrastructure.database import database
from videomind.retrieval.routes import search
from videomind.retrieval.contracts import SearchRequest
x=json.load(sys.stdin);out=[]
for jit in ('on','off','on'):
 url=make_url(Settings().database_url.get_secret_value()).update_query_dict({'options':'-c jit='+jit});engine=database(url);calls=[]
 @event.listens_for(engine,'before_cursor_execute')
 def before(conn,cursor,statement,parameters,context,executemany):context.evaluation_started=time.perf_counter()
 @event.listens_for(engine,'after_cursor_execute')
 def after(conn,cursor,statement,parameters,context,executemany):
  category=next((name for marker,name in [('jsonb_to_recordset','context_batch'),('abs(ordinal','context_ids'),('jsonb_agg(x','hydrate'),('ts_rank_cd','lexical'),('<=>','dense'),('strpos','identifier'),('count(DISTINCT asset_id)','facets'),('unpublished_assets','progress')] if marker in statement),'other')
  calls.append({'category':category,'ms':(time.perf_counter()-context.evaluation_started)*1000})
 request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=engine)))
 result=search(UUID(x['workspace_id']),SearchRequest(workspace_id=x['workspace_id'],query='procedure.txt'),request,UUID(x['actor']))
 signature=[{k:v for k,v in item.items() if k not in ('branches','dense_score','lexical_score','fusion_score')} for item in result.model_dump(mode='json')['results']]
 summary={name:{'count':sum(c['category']==name for c in calls),'ms':sum(c['ms'] for c in calls if c['category']==name)} for name in {c['category'] for c in calls}}
 out.append({'jit':jit,'timings_ms':result.timings_ms,'statement_categories':summary,'result_signature':hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest()})
 engine.dispose()
print(json.dumps(out))
"""


def run(root, client, manifest):
    actor = client.get("/api/auth/me")
    actor.raise_for_status()
    result = subprocess.run(
        command(root, "exec", "-T", "api", "python", "-c", PROBE),
        input=json.dumps(
            {"workspace_id": manifest["workspace_id"], "actor": actor.json()["id"]}
        ).encode(),
        capture_output=True,
        check=True,
    )
    data = json.loads(result.stdout)
    (root / "evaluation/reports/phase7-latency-diagnosis.json").write_text(
        json.dumps(data, indent=2)
    )
    return data
