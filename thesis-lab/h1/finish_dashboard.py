"""Record the experiment interval on its own dashboard, preserving all queries."""
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo


def main(run):
    plan = json.loads((run / 'plan.json').read_text())
    record = json.loads((run / 'dashboard.json').read_text())
    analysis = json.loads((run / 'analysis/summary.json').read_text())
    assert analysis['criteria_met'] and analysis['cases'] == 768
    start = json.loads((run / 'main-started.json').read_text())['at']
    end = json.loads((run / 'main-complete.json').read_text())['at']
    local = lambda t: datetime.fromisoformat(t).astimezone(ZoneInfo('Europe/Moscow')).strftime('%d.%m.%Y %H:%M:%S')
    sys.path.insert(0, str(Path.home() / '.local/share/firefly-thesis/yc-sdk/site'))
    import grpc
    from google.protobuf.json_format import MessageToDict, ParseDict
    from yandex.cloud.monitoring.v3 import dashboard_service_pb2 as p, dashboard_service_pb2_grpc as rpc
    token = subprocess.check_output(['yc', '--profile', plan['profile'], 'iam', 'create-token'], text=True).strip()
    credentials = grpc.composite_channel_credentials(grpc.ssl_channel_credentials(), grpc.access_token_call_credentials(token))
    with grpc.secure_channel('monitoring.api.cloud.yandex.net:443', credentials) as channel:
        api = rpc.DashboardServiceStub(channel)
        current = MessageToDict(api.Get(p.GetDashboardRequest(dashboard_id=record['id']), timeout=30))
        assert current['folderId'] == plan['folder_id'] and current['labels']['experiment'] == run.name
        allowed = {f.json_name for f in p.UpdateDashboardRequest.DESCRIPTOR.fields}
        body = {k: v for k, v in current.items() if k in allowed}
        body['dashboardId'] = record['id']
        banner = next(w for w in body['widgets'] if 'text' in w)
        # Protobuf JSON serializes int64 positions as strings.
        old_height = int(banner['position']['h'])
        banner['position']['h'] = 4
        banner['text']['text'] = ('# Firefly · H1: серия завершена\n\n'
            '768/768 корректных завершений, восемь технических блоков. Три протокола доставки; пять видов отказа.\n\n'
            'Для просмотра основной серии выберите интервал **' + local(start) + ' — ' + local(end) + ' МСК**.\n\n'
            'CPU — нативная метрика YC; RAM и контейнеры — гостевой агент. Рубли: отдельная оценка запуска '
            'и предварительный Billing всего каталога до гранта. Run: ' + run.name)
        for widget in body['widgets']:
            if 'chart' in widget:
                widget['position']['y'] = int(widget['position']['y']) + 4 - old_height
        (run / 'dashboard-completion-request.json').write_text(json.dumps(body, indent=2))
        operation = MessageToDict(api.Update(ParseDict(body, p.UpdateDashboardRequest()), timeout=30))
        (run / 'dashboard-completion-operation.json').write_text(json.dumps(operation, indent=2))
        assert not operation.get('error')
        final = MessageToDict(api.Get(p.GetDashboardRequest(dashboard_id=record['id']), timeout=30))
        assert '768/768' in next(w['text']['text'] for w in final['widgets'] if 'text' in w)
        (run / 'dashboard-completed.json').write_text(json.dumps(final, indent=2))
    print(record['url'])


if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve())
