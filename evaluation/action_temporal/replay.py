"""Authorized frozen-generation replay, retaining pre-cutoff visual candidates."""

import json
import subprocess
from evaluation.quality.recovery import command
from evaluation.action_temporal.protocol import digest

PROBE = """
import json,sys
from uuid import UUID
from videomind.config import Settings
from videomind.infrastructure.database import database,transaction
from videomind.embeddings import generations
from videomind.embeddings.client import Client
from videomind.embeddings.indexer import heavy
from videomind.retrieval import repository
from videomind.retrieval.config import configuration
from videomind.retrieval.contracts import SearchRequest
x=json.load(sys.stdin);engine=database(Settings().database_url.get_secret_value());w=UUID(x['workspace_id']);actor=UUID(x['actor']);output=[]
for query in x['queries']:
 with transaction(engine,actor) as conn:pinned=generations.pin(conn,w)
 if str(pinned['id'])!=x['generation_id'] or pinned['fingerprint']!=x['profile']:raise ValueError('Frozen index changed')
 with heavy(engine):vector=Client().encode(pinned['fingerprint'],'text',query['text'],query=True,configuration=pinned['configuration'])['parts'][0]['vector']
 branches_out={}
 for name,mode,filters in [('native_video','dense',{'modalities':['video'],'representations':['video']}),('derived_text','derived_dense',{})]:
  body=SearchRequest(workspace_id=w,query=query['text'],mode=mode,filters=filters);policy,_=configuration(body)
  with transaction(engine,actor) as conn:branches,details=repository.candidates(conn,w,pinned,body,vector,policy)
  lookup={d['id']:d for d in details};ranked=[]
  for candidate in branches['dense']:
   d=lookup.get(candidate['id'])
   if d is None:continue
   anchors=d['citations'];a=anchors[0]
   ranked.append({'asset_id':str(d['asset_id']),'revision_id':str(d['revision_id']),'segment_id':str(d['id']),'title':d['title'],'representation':d['representation'],'score':candidate['score'],'interval':[a['start_ms'],a['end_ms']] if a['locator_kind']=='temporal' else None,'citation_ids':[str(c['id']) for c in anchors]})
  branches_out[name]=ranked
 output.append({'query_id':query['id'],'family':query['family'],'candidates':branches_out})
engine.dispose();print(json.dumps(output))
"""


def replay(root, client, protocol):
    actor = client.get("/api/auth/me")
    actor.raise_for_status()
    result = subprocess.run(
        command(root, "exec", "-T", "api", "python", "-c", PROBE),
        input=json.dumps(
            {
                k: protocol[k]
                for k in ("workspace_id", "generation_id", "profile", "queries")
            }
            | {"actor": actor.json()["id"]}
        ).encode(),
        capture_output=True,
        check=True,
        timeout=900,
    )
    rows = json.loads(result.stdout)
    for row, query in zip(rows, protocol["queries"], strict=True):
        response = client.post(
            f"/api/workspaces/{protocol['workspace_id']}/search",
            json={"workspace_id": protocol["workspace_id"], "query": query["text"]},
        )
        response.raise_for_status()
        data = response.json()
        if (
            data["profile"] != protocol["profile"]
            or data["generation_id"] != protocol["generation_id"]
        ):
            raise ValueError("Index changed")
        row["all_types_hybrid"] = data
        print(f"replayed {query['id']}", flush=True)
    report = {
        "protocol_sha256": protocol["sha256"],
        "scope": "Authorized whole-corpus native/derived candidates and current all-types hybrid; raw candidates retain scores below 0.70",
        "profile": protocol["profile"],
        "generation_id": protocol["generation_id"],
        "rows": rows,
    }
    report["sha256"] = digest(report)
    path = root / "evaluation/reports/action-temporal-v1-baseline.json"
    if (
        path.exists()
        and json.loads(path.read_text())["protocol_sha256"] != protocol["sha256"]
    ):
        raise ValueError("Baseline version mismatch")
    path.write_text(json.dumps(report, indent=2))
    return report
