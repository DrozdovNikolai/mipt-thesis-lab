"""Image smoke checks on a separate synthetic PostgreSQL and Docker network."""
import argparse
import hashlib
import json
import random
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import httpx
from PIL import Image
from pypdf import PdfReader

parser = argparse.ArgumentParser()
parser.add_argument('--base-url', default='http://release-api:8000')
parser.add_argument('--phase', choices=['initial', 'restarted', 'degraded', 'custom'], required=True)
args = parser.parse_args()
base = args.base_url
prefix = '/v2' if args.phase == 'custom' else '/api'
checks = []


def verify(condition, name):
    assert condition, name
    checks.append(name)


with httpx.Client(base_url=base, timeout=20) as client:
    health = client.get(prefix + '/health')
    verify(health.status_code == 200 and health.json() == {'status': 'ok', 'environment': 'prod'}, 'live')
    ready = client.get(prefix + '/health/ready')
    expected = 'degraded' if args.phase == 'degraded' else 'ready'
    verify(ready.status_code == 200 and ready.json()['status'] == expected, 'ready-body')
    if args.phase != 'degraded':
        verify(all(row['status'] == 'healthy' for row in ready.json()['components'].values()), 'components')
    if args.phase in ['initial', 'custom']:
        for path in ['/docs', '/redoc']:
            verify(client.get(path).status_code == 404, 'prod-no-ui-' + path)
        schema = client.get('/openapi.json')
        verify(schema.status_code == 200, 'openapi')
        paths = schema.json()['paths']
        verify(sum(method in {'get', 'post', 'put', 'delete', 'patch', 'options', 'head'}
                   for item in paths.values() for method in item) == 218, '218-operations')
        verify(not any(path.startswith(prefix + '/ai') or path.startswith(prefix + '/speech')
                       for path in paths), 'no-ai-speech-schema')
        for path in ['/ai/scenario-jobs', '/speech/sessions']:
            verify(client.get(prefix + path).status_code == 404, 'removed-' + path)
        metrics = client.get('/metrics')
        verify(metrics.status_code == 200 and 'go_goroutines' in metrics.text, 'native-metrics')
    if args.phase in ['initial', 'restarted']:
        login = client.post(prefix + '/auth/login', json={'login': 'admin', 'password': 'admin123'})
        verify(login.status_code == 200, 'login')
        token = login.json()['accessToken']
        headers = {'Authorization': 'Bearer ' + token}
        report = client.get(prefix + '/training/assessments/50/report.pdf', headers=headers)
        verify(report.status_code == 200 and report.content.startswith(b'%PDF-'), 'stored-pdf')
        reader = PdfReader(BytesIO(report.content))
        verify(len(reader.pages) == 1 and 'Overall Assessment' in reader.pages[0].extract_text(), 'pdf-content')
        state_path = Path('/results/release-photo-state.json')
        if args.phase == 'initial':
            output = BytesIO()
            # Exceed ParseMultipartForm's 1 MiB memory threshold so the image
            # verifies the runtime's temporary storage, as well as media writes.
            pixels = random.Random(55).randbytes(750 * 600 * 3)
            Image.frombytes('RGB', (750, 600), pixels).save(output, format='PNG')
            verify(len(output.getvalue()) > 1048576, 'multipart-spills-to-disk')
            upload = client.post(prefix + '/users/me/photo/upload', headers=headers,
                                 files={'file': ('release-photo.png', output.getvalue(), 'image/png')})
            verify(upload.status_code == 200, 'photo-upload')
            state = {'path': urlparse(upload.json()['photoUrl']).path,
                     'sha256': hashlib.sha256(output.getvalue()).hexdigest()}
            state_path.write_text(json.dumps(state, indent=2) + '\n')
        else:
            state = json.loads(state_path.read_text())
        photo = client.get(state['path'], headers=headers)
        verify(photo.status_code == 200 and hashlib.sha256(photo.content).hexdigest() == state['sha256'], 'photo-bytes')

report = {'status': 'passed', 'phase': args.phase, 'count': len(checks), 'checks': checks,
          'scope': 'Image/config/probe and short actual API smoke on a dedicated synthetic database; no full contract, client, load, S3 or target Sentry acceptance.'}
Path('/results/release-smoke-' + args.phase + '.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'status': 'passed', 'phase': args.phase, 'count': len(checks)}))
