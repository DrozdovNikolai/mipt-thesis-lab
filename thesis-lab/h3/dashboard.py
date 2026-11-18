"""Update this run's dashboard header/labels without touching the earlier dashboard."""
from datetime import datetime, UTC
import json
from pathlib import Path
import subprocess
import sys
from cloud.ops import read, save


def update(run, phase):
    plan,state=read(run)
    record=json.loads((run/'dashboard.json').read_text())
    body=json.loads((run/'dashboard-request.json').read_text())
    body.pop('folderId');body['dashboardId']=record['id']
    body['title']='Firefly · H3 incremental · '+phase
    status='Четыре варианта аналитики; отдельный генератор; свежесть, WAL, CPU и память. '
    if phase=='завершён':
        summary=json.loads((run/'analysis/summary.json').read_text())
        status+=f"19 200 чтений; 84 смешанных сценария. Критерии H3 выполнены: {summary['h3_criteria_met']}. ВМ и диски удалены. "
    else:
        completed=list((run/'artifacts/loadgen/reads').glob('*/complete.json'))
        status+=f'Завершено профилей чтения: {len(completed)}/6. Итогового вывода по всем критериям пока нет. '
    status+='Стоимость estimate относится к этому запуску; Billing — накопленные начисления каталога, включая предыдущую серию, с задержкой. '
    status+='Период просмотра начинается 03.10.2026 в 21:40 МСК. Run: '+state['run_id']
    body['widgets'][0]['text']['text']='# H3 · проекция по затронутым оценкам\n'+status
    body['widgets'][0]['position']['h']=5
    for widget in body['widgets'][1:]:
        widget['position']['y']=int(widget['position']['y'])+3
    for w in body['widgets']:
        chart=w.get('chart',{})
        if chart.get('id')=='firefly-0':
            chart['queries']['targets'][0]['query']=chart['queries']['targets'][0]['query'].replace('ff-thesis-*','ff-thesis-*-h3i-20261003')
        if chart.get('id')=='firefly-12':
            chart['title']='₽: оценка нового запуска и Billing всего каталога'
            chart['seriesOverrides']=[
                {'targetIndex':'0','settings':{'name':'Оценка нового запуска','color':'#2563eb'}},
                {'targetIndex':'1','settings':{'name':'Billing каталога: оба запуска','color':'#ea580c'}}]
    sys.path.insert(0,str(Path.home()/'.local/share/firefly-thesis/yc-sdk/site'))
    import grpc
    from google.protobuf.json_format import ParseDict,MessageToDict
    from yandex.cloud.monitoring.v3 import dashboard_service_pb2 as messages, dashboard_service_pb2_grpc as rpc
    token=subprocess.check_output(['yc','--profile',plan['profile'],'iam','create-token'],text=True).strip()
    credentials=grpc.composite_channel_credentials(grpc.ssl_channel_credentials(),grpc.access_token_call_credentials(token))
    when=datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
    save(run/('dashboard-update-'+when+'-request.json'),body)
    with grpc.secure_channel('monitoring.api.cloud.yandex.net:443',credentials) as channel:
        result=MessageToDict(rpc.DashboardServiceStub(channel).Update(ParseDict(body,messages.UpdateDashboardRequest()),timeout=30))
    save(run/('dashboard-update-'+when+'-result.json'),result)
    assert not result.get('error'),result.get('error')
    print(record['url'])


if __name__=='__main__':update(Path(sys.argv[1]).resolve(),sys.argv[2])
