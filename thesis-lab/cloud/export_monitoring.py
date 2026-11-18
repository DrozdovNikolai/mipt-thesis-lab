"""Keep the actual Monitoring responses alongside the original guest measurements."""

from datetime import UTC, datetime
from pathlib import Path
import sys

from cloud.monitoring import Monitoring
from cloud.ops import save


def export(run):
    monitoring = Monitoring(run)
    now = datetime.now(UTC)
    output = run / ('monitoring-export-'+now.strftime('%Y%m%dT%H%M%SZ'))
    output.mkdir(exist_ok=False)
    common = {'fromTime': monitoring.state['created_at'], 'toTime': now.isoformat(),
              'downsampling': {'disabled': True}}
    requests = {
        'custom': '"firefly_*"{service="custom",run_id="'+monitoring.state['run_id']+'"}',
        'compute': '{service="compute",resource_id="ff-thesis-*"}',
    }
    summary = {}
    for name, query in requests.items():
        body = {**common, 'query': query}
        result = monitoring.request('/monitoring/v2/data/read?folderId='+monitoring.plan['folder_id'], body, 'POST')
        save(output/(name+'-request.json'), body)
        save(output/(name+'-response.json'), result)
        summary[name] = {'series': len(result.get('metrics', [])),
                         'truncated': result.get('truncated', False)}
    save(output/'manifest.json', {'exported_at': now.isoformat(), 'series': summary,
         'note': 'Monitoring may ingest with delay. Guest JSONL files are the original samples, not reconstructed from this export.'})
    print(output, summary)


if __name__ == '__main__':
    export(Path(sys.argv[1]).resolve())
