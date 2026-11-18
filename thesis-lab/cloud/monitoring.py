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
        file=Path(file)
        rows=[json.loads(line) for line in Path(file).read_text().splitlines()]
        details={}
        if file.name=='mixed-series.jsonl':
            for kind in ('writes','reads','queue'):
                grouped={}
                for line in (file.parent/('mixed-'+kind+'.jsonl')).read_text().splitlines():
                    sample=json.loads(line)
                    key=(sample['rep'],sample['variant'],sample['write_rate'],sample['crash'])
                    grouped.setdefault(key,[]).append(sample)
                details[kind]=grouped
        output=[]
        for row in rows:
            is_read=file.name=='read-series.jsonl'
            phase='smoke' if 'smoke' in file.parts else ('reads' if is_read else 'mixed')
            labels={'run_id':self.state['run_id'],'profile':profile,'variant':row['variant'],'phase':phase}
            if is_read:
                labels.update(concurrency=str(row['concurrency']),historical=str(bool(row['filters'])).lower())
                values={'read_p95_ms':percentile(row['latencies_ms'],.95),'read_p50_ms':percentile(row['latencies_ms'],.5),'read_errors':row['errors'],'read_rps':row['throughput'],'backend_cpu_seconds_per_block':row['backend_cpu_seconds']}
            else:
                labels.update(write_rate=str(row['write_rate']),crash=str(row['crash']).lower())
                key=(row['rep'],row['variant'],row['write_rate'],row['crash'])
                writes,reads,queue=(details[kind][key] for kind in ('writes','reads','queue'))
                values={'mixed_write_errors':row['write_errors'],'mixed_read_errors':row['read_errors'],'wal_bytes_per_update':float(row['sql_delta']['walBytes'])/max(1,row['writes']),
                        'mixed_read_p95_ms':percentile([r['http_ms'] for r in reads if r['status']==200],.95),
                        'mixed_write_p95_ms':percentile([r['http_ms'] for r in writes if r['status']==200],.95),
                        'freshness_p95_ms':percentile([r['freshness_ms'] for r in writes if r.get('freshness_ms') is not None],.95),
                        'queue_max_pending':max((r['pending'] for r in queue),default=0),
                        'mixed_not_visible':row['not_visible_before_deadline']}
            when=datetime.fromtimestamp(row['recorded_at'],UTC).isoformat().replace('+00:00','Z')
            output.extend({'name':'firefly_'+key,'labels':labels,'value':value,'ts':when} for key,value in values.items() if value is not None)
        return output

    def create_dashboard(self):
        folder=self.plan['folder_id']
        run_id=self.state['run_id']
        if (self.run/'dashboard.json').exists():
            return json.loads((self.run/'dashboard.json').read_text())
        widgets=[{'position':{'x':0,'y':0,'w':24,'h':2},'text':{'text':'# Firefly · облачная репликация H3\nТри существующих варианта аналитики, отдельный генератор нагрузки. p95 — значение отдельного блока; итоговые интервалы рассчитываются по повторам. Стоимость estimated — расчёт по времени, actual — предварительная детализация Billing. Run: '+run_id}}]
        def custom(name,**labels):
            return '"firefly_'+name+'"{'+','.join(f'{k}="{v}"' for k,v in {'folderId':folder,'service':'custom','run_id':run_id,**labels}.items())+'}'
        native='"cpu_usage"{folderId="'+folder+'",service="compute",resource_id="ff-thesis-*"}'
        specs=[
            ('CPU виртуальных машин, %', [native], 'percent'),
            ('Использование RAM в гостевой ОС, байт',[custom('host_memory_used_bytes')],'bytes'),
            ('Аналитика: p95, текущий срез, 8 клиентов, мс',[custom('read_p95_ms',phase='reads',variant=v,concurrency='8',historical='false') for v in ('original','optimized','projection')],'ms'),
            ('Аналитика: p95, текущий срез, 1 клиент, мс',[custom('read_p95_ms',phase='reads',variant=v,concurrency='1',historical='false') for v in ('original','optimized','projection')],'ms'),
            ('CPU контейнеров, накопленные секунды',[custom('container_cpu_seconds',role='server')],'seconds'),
            ('Память контейнеров, байт',[custom('container_memory_bytes',role='server')],'bytes'),
            ('Запись на системный SSD, байт/с',[custom('host_disk_write_bytes_per_second',role='server')],'bytes/s'),
            ('WAL на изменение: смешанная нагрузка, байт',[custom('wal_bytes_per_update')],'bytes'),
            ('Ошибки запросов',[custom('read_errors'),custom('mixed_write_errors'),custom('mixed_read_errors')],'count'),
            ('Расходы, ₽: estimate и Billing до гранта',[custom('estimated_total_rub'),custom('billing_cost_before_credits_rub')],'RUB'),
            ('Ожидание диска и steal CPU, %',[custom('host_iowait_percent'),custom('host_steal_percent')],'percent'),
        ]
        for i,(title,queries,unit) in enumerate(specs):
            chart={'id':'firefly-'+str(i),'title':title,'displayLegend':True,'queries':{'targets':[{'name':chr(65+j),'query':q,'textMode':True} for j,q in enumerate(queries)],'downsampling':{'disabled':True}},'visualizationSettings':{'type':'VISUALIZATION_TYPE_LINE','yaxisSettings':{'left':{'title':unit,'min':'0'}}}}
            if i in (2,3):
                chart['seriesOverrides']=[{'targetIndex':str(j),'settings':{'color':color,'name':name}} for j,(name,color) in enumerate((('original','#64748b'),('optimized','#2563eb'),('projection','#ea580c')))]
            widgets.append({'position':{'x':(i%2)*12,'y':2+(i//2)*7,'w':12,'h':7},'chart':chart})
        body={'folderId':folder,'name':'firefly-h3-20261003','title':'Firefly · H3 · YC 03.10.2026','description':'CPU baseline replication. '+run_id,'labels':{'project':'firefly-thesis','experiment':run_id},'widgets':widgets}
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
