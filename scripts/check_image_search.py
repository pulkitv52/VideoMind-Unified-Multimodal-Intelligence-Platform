"""CPU real-model image-query smoke; known corpus inputs, not a gold benchmark."""

import base64
import hashlib
import json
from pathlib import Path
import sys
import time

import av
import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from evaluation.quality.corpus import freeze


def main():
    corpus=json.loads((ROOT/'evaluation/manifests/phase7-corpus.json').read_text())
    samples=[('known-cat',ROOT/'.local/datasets/public-starter/chelsea.png',{'modalities':['image']},'chelsea.png')]
    protocol=json.loads((ROOT/'evaluation/manifests/action-temporal-v1.json').read_text())
    asset=next(a for a in protocol['assets'] if a['asset_key']=='caviar-Rest_FallOnFloor')
    path=ROOT/asset['path']
    assert hashlib.sha256(path.read_bytes()).hexdigest()==asset['sha256']
    frame_path=ROOT/'.local/image-query-caviar.png'
    with av.open(str(path)) as container:
        for frame in container.decode(video=0):
            if frame.pts*frame.time_base>=30:
                frame.to_image().save(frame_path);break
    samples.append(('known-video-frame',frame_path,{'modalities':['video'],'asset_ids':[asset['asset_id']]},asset['title']))
    with httpx.Client(base_url='http://localhost:8080',timeout=180) as client:
        client.post('/api/auth/login',json=json.loads((ROOT/'.local/owner.json').read_text())).raise_for_status()
        before=freeze(client,ROOT);assert before['sha256']==corpus['sha256']
        workspace=corpus['workspace_id'];results=[]
        for name,path,filters,title in samples:
            started=time.perf_counter()
            response=client.post(f'/api/workspaces/{workspace}/search/image',json={'workspace_id':workspace,'image_base64':base64.b64encode(path.read_bytes()).decode(),'filters':filters})
            response.raise_for_status();data=response.json()
            assert data['configuration']['query_kind']=='image'
            assert any(h['title']==title for h in data['results']),f'{name} expected match missing'
            for hit in data['results']:
                assert set(hit['branches'])=={'dense'}
                for citation in hit['citations']:
                    client.get(f"/api/workspaces/{workspace}/sources/{hit['asset']['source_id']}/citations/{citation['id']}").raise_for_status()
            results.append({'case':name,'input_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'milliseconds':round((time.perf_counter()-started)*1000,2),'results':[{'title':h['title'],'score':h['dense_score'],'citations':[c['id'] for c in h['citations']]} for h in data['results']]})
        after=freeze(client,ROOT);assert before['sha256']==after['sha256']
    report={'scope':'Two known-input CPU smoke cases, not independent relevance or latency evaluation','originals_preserved':46,'corpus_unchanged':True,'profile':data['profile'],'generation':str(data['generation_id']),'query_images_persisted_as_assets':False,'cases':results}
    (ROOT/'evaluation/reports/image-query-smoke.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':main()
