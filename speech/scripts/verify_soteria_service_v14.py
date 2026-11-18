"""Read-only integration checks on the actual SOTERIA packet, using a test session."""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from scripts.review_dataset import create_app
from north55_speech.core import file_hash

packet=Path('/packet')
before={str(p.relative_to(packet)):file_hash(p) for p in packet.rglob('*') if p.is_file()}
app=create_app(packet,Path('/audio'),'k'*32,'s'*32)
with TestClient(app) as client:
    assert client.get('/api/packet').status_code==401
    login=client.post('/login',data={'key':'k'*32,'annotator':'Read-only integration check'},follow_redirects=False)
    assert login.status_code==303
    listing=client.get('/api/packet')
    assert listing.status_code==200
    items=listing.json()['items']
    crews=set()
    for item in items:
        response=client.get('/api/item/'+item['id'])
        assert response.status_code==200
        value=response.json()
        assert value['revision']==0 and value['sample']['transcript_status']=='missing'
        assert value['sample']['reference_text'] is None and not value['sample']['scope_verified']
        assert value['machine_draft_available'] and value['machine_draft_prefill']
        if item['source'] not in crews:
            audio=client.get('/api/audio/'+item['id'])
            assert audio.status_code==200 and audio.content[:4]==b'RIFF'
            crews.add(item['source'])
    assert len(crews)==4
after={str(p.relative_to(packet)):file_hash(p) for p in packet.rglob('*') if p.is_file()}
assert before==after,'Read-only checks changed packet files'
print(json.dumps({'status':'PASS','items':len(items),'source_audio_HTTP_checks':len(crews),
                  'all_drafts_available':True,'packet_files_unchanged':len(before),
                  'annotations_or_draft_exposures_created':0}))
