"""YC dashboard/metrics helpers; source measurements remain in local JSONL files."""

from datetime import UTC, datetime
import json
import math
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request

from cloud.ops import read, save, yc


def percentile(values, q):
    data=sorted(values)
    if not data:
        return None
    i=(len(data)-1)*q
    low=math.floor(i)
    return data[low]+(data[min(low+1,len(data)-1)]-data[low])*(i-low)


class Monitoring:
    def __init__(self, run):
        self.run=Path(run)
        self.plan,self.state=read(self.run)
        self.token=''
        self.renew_at=0

    def request(self,path,body=None,method=None):
        if time.time()>=self.renew_at:
            p=subprocess.run(['yc','--profile',self.plan['profile'],'iam','create-token'],capture_output=True,text=True,check=True)
            self.token=p.stdout.strip()
            self.renew_at=time.time()+1800
        request=urllib.request.Request('https://monitoring.api.cloud.yandex.net'+path,data=None if body is None else json.dumps(body).encode(),headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json'},method=method)
        try:
            with urllib.request.urlopen(request,timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError('Monitoring HTTP '+str(error.code)+': '+error.read().decode()[:1600]) from None

    def write(self,points):
        if not points:
            return
        result=self.request('/monitoring/v2/data/write?folderId='+self.plan['folder_id']+'&service=custom',{'metrics':points},'POST')
        if result.get('errorMessage'):
            raise RuntimeError(str(result))
        with (self.run/'monitoring-writes.jsonl').open('a') as stream:
            stream.write(json.dumps({'at':datetime.now(UTC).isoformat(),'points':len(points),'result':result})+'\n')
        return result

    def points(self,file,profile):
        rows=[json.loads(line) for line in Path(file).read_text().splitlines()]
        output=[]
        for row in rows:
            labels={'run_id':self.state['run_id'],'variant':row['variant'],'phase':profile,
                    'fault':row['fault'],'rtt_ms':str(row['rtt_ms']),'cache':str(row['cache']),
                    'gzip':str(row['gzip']).lower()}
            when=datetime.fromtimestamp(row['ended_at'],UTC).isoformat().replace('+00:00','Z')
            values={'h1_delivery_ms':row['delivery_ms'],'h1_wire_bytes':row['wire_bytes'],
                'h1_requests':row['requests'],'h1_correct':int(row['correct']),
                'h1_submit_attempts':row['submit_attempts'],'h1_errors':int(not row['correct'])}
            output.extend({'name':'firefly_'+name,'labels':labels,'value':value,'ts':when} for name,value in values.items())
        return output

    def create_dashboard(self):
        folder=self.plan['folder_id']
        run_id=self.state['run_id']
        if (self.run/'dashboard.json').exists():
            return json.loads((self.run/'dashboard.json').read_text())
        widgets=[{'position':{'x':0,'y':0,'w':24,'h':2},'text':{'text':'# Firefly · H1: надёжное завершение тренировки\nТри варианта: split/full, split/compact, unified/compact. Время до принятия финальной квитанции, байты HTTP с повторами. Каждая точка — одна тренировка; отказы и сети разделяются по меткам. Стоимость estimated — расчёт по времени, actual — предварительная детализация Billing. Run: '+run_id}}]
        def custom(name,**labels):
            return '"firefly_'+name+'"{'+','.join(f'{k}="{v}"' for k,v in {'folderId':folder,'service':'custom','run_id':run_id,**labels}.items())+'}'
        native='"cpu_usage"{folderId="'+folder+'",service="compute",resource_id="ff-thesis-*-h1-20261004"}'
        specs=[
            ('Время подтверждённого завершения, мс', [custom('h1_delivery_ms',phase='main',fault='clean',rtt_ms='250',cache='16384',gzip='true')], 'ms'),
            ('Переданные HTTP байты с повторами', [custom('h1_wire_bytes',phase='main',fault='clean',rtt_ms='250',cache='16384',gzip='true')], 'bytes'),
            ('CPU виртуальных машин, %',[native],'percent'),
            ('Память гостевой ОС',[custom('host_memory_used_bytes')],'bytes'),
            ('Корректное завершение: 1=да',[custom('h1_correct',phase='main')],'count'),
            ('Время завершения: все пять видов отказа',[custom('h1_delivery_ms',phase='main',fault='*restart*'),custom('h1_delivery_ms',phase='main',fault='*crash*'),custom('h1_delivery_ms',phase='main',fault='*ack*')],'ms'),
            ('Число HTTP попыток на тренировку',[custom('h1_requests',phase='main')],'count'),
            ('Число попыток финального submit',[custom('h1_submit_attempts',phase='main')],'count'),
            ('CPU контейнеров, накопленные секунды',[custom('container_cpu_seconds')],'seconds'),
            ('Память контейнеров',[custom('container_memory_bytes')],'bytes'),
            ('Ошибки корректности: 0=нет',[custom('h1_errors',phase='main')],'count'),
            ('Расходы: estimate и предварительный Billing',[custom('estimated_total_rub'),custom('billing_cost_before_credits_rub')],'RUB'),
        ]
        for i,(title,queries,unit) in enumerate(specs):
            chart={'id':'firefly-'+str(i),'title':title,'displayLegend':True,'queries':{'targets':[{'name':chr(65+j),'query':q,'textMode':True} for j,q in enumerate(queries)],'downsampling':{'disabled':True}},'visualizationSettings':{'type':'VISUALIZATION_TYPE_LINE','yaxisSettings':{'left':{'title':unit,'min':'0'}}}}
            widgets.append({'position':{'x':(i%2)*12,'y':2+(i//2)*7,'w':12,'h':7},'chart':chart})
        body={'folderId':folder,'name':'firefly-h1-durable-20261004','title':'Firefly · H1 durable · YC 04.10.2026','description':'Durable completion protocol comparison. '+run_id,'labels':{'project':'firefly-thesis','experiment':run_id},'widgets':widgets}
        save(self.run/'dashboard-request.json',body)
        # Dashboard v3 is exposed over gRPC; metrics use the documented v2 REST API.
        # The SDK is installed into a task-specific directory, not global Python.
        sdk=Path.home()/'.local/share/firefly-thesis/yc-sdk/site'
        if sdk.exists() and str(sdk) not in sys.path:
            sys.path.insert(0,str(sdk))
        import grpc
        from google.protobuf.json_format import ParseDict,MessageToDict
        from yandex.cloud.monitoring.v3 import dashboard_service_pb2 as messages
        from yandex.cloud.monitoring.v3 import dashboard_service_pb2_grpc as rpc
        token=subprocess.check_output(['yc','--profile',self.plan['profile'],'iam','create-token'],text=True).strip()
        credentials=grpc.composite_channel_credentials(grpc.ssl_channel_credentials(),grpc.access_token_call_credentials(token))
        with grpc.secure_channel('monitoring.api.cloud.yandex.net:443',credentials) as channel:
            operation=rpc.DashboardServiceStub(channel).Create(ParseDict(body,messages.CreateDashboardRequest()),timeout=30)
            result=MessageToDict(operation)
        save(self.run/'dashboard-operation.json',result)
        if result.get('done') is False:
            for _ in range(30):
                time.sleep(1)
                result=yc(self.plan,'operation','get',result['id'])
                if result.get('done'): break
        if result.get('error'):
            raise RuntimeError(str(result['error']))
        dashboard=result.get('response',result)
        identifier=dashboard.get('id') or result.get('metadata',{}).get('dashboardId')
        if not identifier:
            raise RuntimeError('Dashboard identifier absent in response')
        record={'id':identifier,'url':'https://monitoring.yandex.cloud/projects/'+folder+'/dashboards/'+identifier,'response':dashboard}
        save(self.run/'dashboard.json',record)
        return record
