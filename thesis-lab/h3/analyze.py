"""Validate the declared cloud matrix and produce figures without changing raw data."""

from collections import Counter, defaultdict
import csv
from datetime import UTC, datetime
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import sys

from cloud.monitoring import percentile
from h3.run import PROFILES

VARIANTS=('original','optimized','projection','incremental')
COLORS={'original':'#64748b','optimized':'#2563eb','projection':'#ea580c','incremental':'#16a34a'}


def rows(path):
    return [json.loads(s) for s in path.read_text().splitlines()]


def paired_ci(candidate,baseline,seed=20361003):
    ratios=[candidate[k]/baseline[k] for k in sorted(candidate) if k in baseline]
    logs=[math.log(x) for x in ratios]
    rng=random.Random(seed)
    sample=[math.exp(statistics.mean(rng.choices(logs,k=len(logs)))) for _ in range(10000)]
    return {'ratio':math.exp(statistics.mean(logs)),'ci95':[percentile(sample,.025),percentile(sample,.975)],'pairs':len(logs),'ratio_by_rep':ratios}


def main(run):
    run=run.resolve()
    root=run/'artifacts/loadgen'
    out=run/'analysis'
    out.mkdir(exist_ok=False)
    summary={'analyzed_at':datetime.now(UTC).isoformat(),'complete_marker_present':(run/'main-complete.json').exists(),'profiles':{},'errors':[]}
    plan_hash=hashlib.sha256((run/'H3_PLAN.md').read_bytes()).hexdigest()
    assert plan_hash==json.loads((run/'main-started.json').read_text())['plan_sha256']
    summary['plan_sha256']=plan_hash
    summary['runtime_source_audit']={}
    for role in ('server','loadgen'):
        before=json.loads((run/(role+'-runtime-files-before-main.json')).read_text())
        after=json.loads((run/(role+'-runtime-files-after-main.json')).read_text())
        assert not before['mismatches'] and not after['mismatches']
        assert before['files']==after['files']
        summary['runtime_source_audit'][role]={'files':len(before['files']),'unchanged':True}
    all_reads=[]
    for profile in PROFILES:
        name=profile['id']
        directory=root/'reads'/name
        checks=rows(directory/'read-checks.jsonl')
        http=rows(directory/'read-http.jsonl')
        series=rows(directory/'read-series.jsonl')
        assert len(checks)==32 and all(r['passed'] for r in checks),name
        assert len(http)==3200 and len(series)==160,name
        expected=Counter((rep,v,concurrency,historical) for rep in range(10) for v in VARIANTS for concurrency in (1,8) for historical in (False,True))
        actual=Counter((r['rep'],r['variant'],r['concurrency'],bool(r['filters'])) for r in series)
        assert actual==expected,name
        http_expected=Counter((*key,index) for key in expected for index in range(20))
        http_actual=Counter((r['rep'],r['variant'],r['concurrency'],bool(r['filters']),r['request']) for r in http)
        assert http_actual==http_expected,(name,'missing or duplicate measured request')
        assert all(r['requests']==20 for r in series)
        assert all(r['status']!=200 or r['correct'] for r in http)
        for variant in VARIANTS:
            instances={r['backend_instance'] for r in series if r['variant']==variant}
            assert len(instances)==10,(name,variant,'backend did not restart between repetitions')
        errors=sum(not r['correct'] for r in http)
        groups={}
        comparisons={}
        for historical in (False,True):
            for concurrency in (1,8):
                key=('historical' if historical else 'current')+'-'+str(concurrency)
                per_variant={}
                for variant in VARIANTS:
                    selected=[r for r in series if r['variant']==variant and r['concurrency']==concurrency and bool(r['filters'])==historical]
                    p95={r['rep']:percentile(r['latencies_ms'],.95) for r in selected}
                    assert all(value is not None for value in p95.values()),(name,key,variant)
                    per_variant[variant]={'median_block_p95_ms':statistics.median(p95.values()),'p95_by_rep':p95,'requests':sum(r['requests'] for r in selected),'errors':sum(r['errors'] for r in selected),
                        'median_block_p50_ms':statistics.median(percentile(r['latencies_ms'],.5) for r in selected),
                        'backend_cpu_ms_per_request':1000*sum(r['backend_cpu_seconds'] for r in selected)/sum(r['requests'] for r in selected),
                        'sql_execution_ms_per_request':sum(r['sql_delta']['executionMs'] for r in selected)/sum(r['requests'] for r in selected)}
                groups[key]=per_variant
                comparisons[key]=paired_ci(per_variant['incremental']['p95_by_rep'],per_variant['optimized']['p95_by_rep'])
        summary['profiles'][name]={'http_requests':len(http),'read_checks':len(checks),'errors':errors,'groups':groups,'incremental_over_optimized':comparisons}
        all_reads.extend(http)
    assert len(all_reads)==19200
    mixed=root/'mixed/history-100k'
    mixed_checks=rows(mixed/'read-checks.jsonl')
    assert len(mixed_checks)==32 and all(r['passed'] for r in mixed_checks)
    cases=rows(mixed/'mixed-series.jsonl')
    writes=rows(mixed/'mixed-writes.jsonl')
    mixed_reads=rows(mixed/'mixed-reads.jsonl')
    queue_samples=rows(mixed/'mixed-queue.jsonl')
    assert len(cases)==84 and len(writes)==11340 and len(mixed_reads)==10080
    expected=Counter([(rep,rate,v,False) for rep in range(10) for rate in (1,8) for v in VARIANTS]+[(0,rate,v,True) for rate in (1,8) for v in ('projection','incremental')])
    actual=Counter((r['rep'],r['write_rate'],r['variant'],r['crash']) for r in cases)
    assert actual==expected
    assert all(r['converged'] for r in cases)
    for case in cases:
        key=tuple(case[k] for k in ('rep','write_rate','variant','crash'))
        select=lambda r:tuple(r[k] for k in ('rep','write_rate','variant','crash'))==key
        cw=[r for r in writes if select(r)]; cr=[r for r in mixed_reads if select(r)]
        assert Counter(r['index'] for r in cw)==Counter(range(int(case['duration_s']*case['write_rate'])))
        assert Counter(r['index'] for r in cr)==Counter(range(int(case['duration_s']*case['read_rate'])))
        assert sum(r['status']!=200 for r in cw)==case['write_errors']
        assert sum(r['status']!=200 for r in cr)==case['read_errors']
        assert sum(not r['visible'] for r in cw)==case['not_visible_before_deadline']
    for case in (r for r in cases if r['crash']):
        assert case['worker_after']['crashes']==case['worker_before']['crashes']+1
        assert case['worker_after']['workerPid']!=case['worker_before']['workerPid']
        assert case['worker_after']['crashRequested'] is False
    summary['mixed']={'cases':len(cases),'writes':len(writes),'reads':len(mixed_reads),'write_errors':sum(r['write_errors'] for r in cases),'read_errors':sum(r['read_errors'] for r in cases),'not_visible':sum(r['not_visible_before_deadline'] for r in cases),'groups':{}}
    summary['mixed']['observer_requests']=sum(r['observer_requests'] for r in cases)
    summary['mixed']['fault_cases']=[{'variant':r['variant'],'write_rate':r['write_rate'],'worker_before':r['worker_before'],'worker_after':r['worker_after'],'converged':r['converged'],'not_visible_before_deadline':r['not_visible_before_deadline']} for r in cases if r['crash']]
    summary['mixed']['process_exit_evidence']=[]
    for variant,prefix in (('projection',''),('incremental','incremental-')):
        server_mixed=run/'artifacts/server/mixed/history-100k'
        deaths=rows(server_mixed/(prefix+'worker-crashes.jsonl'))
        processes=rows(server_mixed/(prefix+'worker-processes.jsonl'))
        for case in (r for r in cases if r['variant']==variant and r['crash']):
            pid=case['worker_before']['workerPid']
            matching_deaths=[r for r in deaths if r['pid']==pid]
            matching_exits=[r for r in processes if r['pid']==pid and r['exit_code']==77]
            assert len(matching_deaths)==len(matching_exits)==1
            death=matching_deaths[0]; process=matching_exits[0]
            assert death['before_commit'] and death['pending_before']>0
            assert process['restart_delay_s']==5 and process['end']>=process['start']
            summary['mixed']['process_exit_evidence'].append({'variant':variant,'write_rate':case['write_rate'],'crash':death,'exit':process})
    for variant in VARIANTS:
        for rate in (1,8):
            selected=[r for r in cases if r['variant']==variant and r['write_rate']==rate and not r['crash']]
            selected_writes=[r for r in writes if r['variant']==variant and r['write_rate']==rate and not r['crash']]
            selected_reads=[r for r in mixed_reads if r['variant']==variant and r['write_rate']==rate and not r['crash']]
            summary['mixed']['groups'][variant+'-'+str(rate)]={
                'wal_bytes':sum(float(r['sql_delta']['walBytes']) for r in selected),
                'wal_bytes_per_update':sum(float(r['sql_delta']['walBytes']) for r in selected)/sum(r['writes'] for r in selected),
                'writes':sum(r['writes'] for r in selected),
                'write_p95_ms':percentile([r['http_ms'] for r in selected_writes if r['status']==200],.95),
                'read_p95_ms':percentile([r['http_ms'] for r in selected_reads if r['status']==200],.95),
                'write_p50_ms':percentile([r['http_ms'] for r in selected_writes if r['status']==200],.5),
                'read_p50_ms':percentile([r['http_ms'] for r in selected_reads if r['status']==200],.5),
                'scheduled_to_ack_p95_ms':percentile([r['scheduled_to_ack_ms'] for r in selected_writes if r['status']==200],.95),
                'scheduled_to_response_p95_ms':percentile([r['scheduled_to_response_ms'] for r in selected_reads if r['status']==200],.95),
                'write_driver_wait_p95_ms':percentile([r['driver_wait_ms'] for r in selected_writes],.95),
                'read_driver_wait_p95_ms':percentile([r['driver_wait_ms'] for r in selected_reads],.95),
                'freshness_p95_ms':percentile([r['freshness_ms'] for r in selected_writes if r.get('freshness_ms') is not None],.95),
            }
    summary['passed']=summary['complete_marker_present'] and all(p['errors']==0 for p in summary['profiles'].values()) and all(summary['mixed'][k]==0 for k in ('write_errors','read_errors','not_visible'))
    summary['measurement_notes']={
        'cpu':'Backend process CPU delta includes the resource probe; it is not VM billing or database CPU.',
        'sql':'pg_stat_statements execution time is elapsed SQL execution time, not pure CPU time.',
        'confidence_intervals':'Pointwise paired bootstrap intervals, not adjusted for comparisons across profiles.',
        'mixed':'Ten repetitions; pooled successful request percentiles are descriptive. Paired CIs use per-repetition summaries.',
    }
    summary['mixed']['paired']={}
    freshness_by_rep={}
    for rate in (1,8):
        def case_values(variant,metric):
            selected=[r for r in cases if r['variant']==variant and r['write_rate']==rate and not r['crash']]
            return {r['rep']:float(r['sql_delta'][metric])/r['writes'] for r in selected}
        summary['mixed']['paired'][str(rate)]={metric:paired_ci(case_values('incremental',metric),case_values('projection',metric)) for metric in ('walBytes','executionMs')}
        def write_p95(variant):
            return {rep:percentile([r['http_ms'] for r in writes if r['variant']==variant and r['write_rate']==rate and r['rep']==rep and not r['crash'] and r['status']==200],.95) for rep in range(10)}
        summary['mixed']['paired'][str(rate)]['write_p95_ms']=paired_ci(write_p95('incremental'),write_p95('projection'))
        freshness_by_rep[str(rate)]={rep:percentile([r['freshness_ms'] for r in writes if r['variant']=='incremental' and r['write_rate']==rate and r['rep']==rep and not r['crash'] and r.get('freshness_ms') is not None],.95) for rep in range(10)}
    summary['freshness_by_rep']=freshness_by_rep
    recovery_max={str(rate):max(r['freshness_ms'] for r in writes if r['variant']=='incremental' and r['write_rate']==rate and r['crash'] and r.get('freshness_ms') is not None) for rate in (1,8)}
    validation=json.loads((run/'artifacts/server/smoke/reads/incremental-validation-complete.json').read_text())
    coalescing=rows(run/'artifacts/server/mixed/history-100k/coalescing.jsonl')
    assert Counter((r['rep'],r['variant']) for r in coalescing)==Counter((rep,v) for rep in range(10) for v in ('projection','incremental'))
    assert all(r['correct'] and r['accepted_updates']==20 and r['pending_before_drain']==1 for r in coalescing)
    summary['coalescing']={'cases':len(coalescing),'updates':sum(r['accepted_updates'] for r in coalescing),'wal_per_update':{v:sum(r['sql_delta']['wal_bytes'] for r in coalescing if r['variant']==v)/200 for v in ('projection','incremental')}}
    summary['validation']=validation
    summary['post_workload_parity']=json.loads((run/'storage-after-workload.json').read_text())['post_workload_parity']
    summary['recovery_max_freshness_ms']=recovery_max
    summary['criteria']={
        'correctness_and_no_errors':summary['passed'] and validation['passed'] and summary['post_workload_parity']['passed'],
        'read_p95_upper_ci_below_1':summary['profiles']['history-100k']['incremental_over_optimized']['current-1']['ci95'][1]<1,
        'maintenance_wal_upper_ci_below_1':summary['mixed']['paired']['8']['walBytes']['ci95'][1]<1,
        'freshness_each_healthy_rep_at_most_1000ms':all(v is not None and v<=1000 for group in freshness_by_rep.values() for v in group.values()),
        'recovery_freshness_at_most_15000ms':all(v<=15000 for v in recovery_max.values()),
    }
    summary['h3_criteria_met']=all(summary['criteria'].values())
    summary['storage']={}
    for profile in PROFILES:
        values={}
        for variant in VARIANTS:
            record=json.loads((run/'artifacts/server/reads'/profile['id']/('storage-'+variant+'.json')).read_text())
            values[variant]={'all_table_and_index_bytes':sum(t['bytes'] for t in record['tables']),'projection_bytes':sum(t['bytes'] for t in record['tables'] if t['relname'].startswith('commander_')),'install_ms':record['install_ms']}
        summary['storage'][profile['id']]=values
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    comparison_rows=[]
    for profile,data in summary['profiles'].items():
        for cell,group in data['groups'].items():
            ratio=data['incremental_over_optimized'][cell]
            comparison_rows.append({'profile':profile,'cell':cell,
                **{v+'_median_block_p95_ms':group[v]['median_block_p95_ms'] for v in VARIANTS},
                **{v+'_median_block_p50_ms':group[v]['median_block_p50_ms'] for v in VARIANTS},
                'ratio':ratio['ratio'],'ci95_lower':ratio['ci95'][0],'ci95_upper':ratio['ci95'][1],'paired_repetitions':ratio['pairs']})
    with (out/'read-comparisons.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(comparison_rows[0]));writer.writeheader();writer.writerows(comparison_rows)
    case_rows=[]
    for case in cases:
        key=tuple(case[k] for k in ('rep','write_rate','variant','crash'))
        cw=[r for r in writes if tuple(r[k] for k in ('rep','write_rate','variant','crash'))==key]
        cr=[r for r in mixed_reads if tuple(r[k] for k in ('rep','write_rate','variant','crash'))==key]
        case_rows.append({k:case[k] for k in ('rep','write_rate','variant','crash','writes','reads','write_errors','read_errors','not_visible_before_deadline')})
        case_rows[-1].update(wal_bytes_per_update=float(case['sql_delta']['walBytes'])/case['writes'],
            freshness_p95_ms=percentile([r['freshness_ms'] for r in cw if r.get('freshness_ms') is not None],.95),
            read_p95_ms=percentile([r['http_ms'] for r in cr if r['status']==200],.95),
            write_p95_ms=percentile([r['http_ms'] for r in cw if r['status']==200],.95))
        case_rows[-1].update(
            read_p50_ms=percentile([r['http_ms'] for r in cr if r['status']==200],.5),
            write_p50_ms=percentile([r['http_ms'] for r in cw if r['status']==200],.5),
            read_scheduled_to_response_p95_ms=percentile([r['scheduled_to_response_ms'] for r in cr if r['status']==200],.95),
            write_scheduled_to_ack_p95_ms=percentile([r['scheduled_to_ack_ms'] for r in cw if r['status']==200],.95),
            observer_requests=case['observer_requests'])
    with (out/'mixed-cases.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(case_rows[0]));writer.writeheader();writer.writerows(case_rows)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.family':'DejaVu Sans','figure.dpi':150,'axes.spines.top':False,'axes.spines.right':False,'axes.grid':True,'grid.alpha':.2,'axes.axisbelow':True})
    fig,axs=plt.subplots(1,2,figsize=(11,4),layout='constrained')
    for ax,concurrency in zip(axs,(1,8)):
        for variant in VARIANTS:
            values=[summary['profiles'][p]['groups']['current-'+str(concurrency)][variant]['median_block_p95_ms'] for p in ('history-1k','history-10k','history-100k')]
            ax.plot([1000,10000,100000],values,marker='o',label=variant,color=COLORS[variant],linewidth=2)
        ax.set_xscale('log'); ax.set_xlabel('Тренировок в истории'); ax.set_ylabel('Медиана p95 по 10 блокам, мс'); ax.set_title(f'Текущий срез · {concurrency} клиент(ов)'); ax.legend()
    fig.suptitle('Firefly: аналитика на двух ВМ Yandex Cloud')
    for suffix in ('png','svg'): fig.savefig(out/('read-scaling.'+suffix))
    plt.close(fig)
    fig,ax=plt.subplots(figsize=(10,5),layout='constrained')
    labels={'history-1k':'1k тренировок / 1000 пилотов','history-10k':'10k / 1000','history-100k':'100k / 1000','pilots-100':'100k / 100','skew-80-10':'100k / 1000, перекос 80/10','neighbors-4':'100k / 1000, 4 соседние авиакомпании'}
    for concurrency,offset,color in ((1,-.13,'#2563eb'),(8,.13,'#ea580c')):
        values=[summary['profiles'][p['id']]['incremental_over_optimized']['current-'+str(concurrency)] for p in PROFILES]
        means=[r['ratio'] for r in values]
        lower=[max(0,r['ratio']-r['ci95'][0]) for r in values]
        upper=[max(0,r['ci95'][1]-r['ratio']) for r in values]
        ax.errorbar(means,[i+offset for i in range(len(PROFILES))],xerr=[lower,upper],fmt='o',capsize=4,color=color,label=f'{concurrency} клиент(ов)')
    ax.axvline(1,color='#475569',linestyle='--',linewidth=1)
    ax.set_yticks(range(len(PROFILES)),[labels[p['id']] for p in PROFILES]); ax.invert_yaxis(); ax.set_xscale('log')
    ax.set_xlabel('incremental / optimized по p95; <1 — быстрее, >1 — медленнее')
    ax.set_title('Текущий срез: парные отношения, точечные bootstrap 95% ДИ'); ax.legend()
    for suffix in ('png','svg'): fig.savefig(out/('paired-ratios.'+suffix))
    plt.close(fig)
    fig,axs=plt.subplots(1,3,figsize=(12,4),layout='constrained')
    for ax,metric,title in zip(axs,('read_p95_ms','freshness_p95_ms','wal_bytes_per_update'),('Чтение, p95, мс','Наблюдаемая свежесть, p95, мс','WAL на изменение, байт')):
        values=[summary['mixed']['groups'][v+'-8'][metric] for v in VARIANTS]
        bars=ax.bar(VARIANTS,values,color=[COLORS[v] for v in VARIANTS]); ax.set_title(title); ax.tick_params(axis='x',rotation=20)
        if metric=='wal_bytes_per_update':
            ax.set_yscale('log')
            ax.set_ylabel('Логарифмическая шкала')
        ax.bar_label(bars,labels=[f'{v:,.1f}' for v in values],padding=3,fontsize=8)
        ax.margins(y=.18)
    fig.suptitle('Смешанная нагрузка: 8 изменений/с + 4 чтения/с, без инъекции сбоев')
    for suffix in ('png','svg'): fig.savefig(out/('mixed-tradeoffs.'+suffix))
    plt.close(fig)
    fig,axs=plt.subplots(2,2,figsize=(11,6),layout='constrained',sharex='col')
    for column,variant in enumerate(('projection','incremental')):
        rate=8
        case=next(r for r in cases if r['crash'] and r['write_rate']==rate and r['variant']==variant)
        samples=sorted([r for r in queue_samples if r['crash'] and r['write_rate']==rate and r['variant']==variant],key=lambda r:r['offset_s'])
        changes=sorted([r for r in writes if r['crash'] and r['write_rate']==rate and r['variant']==variant],key=lambda r:r['offset_s'])
        old_pid=case['worker_before']['workerPid']
        new_pid_at=next((r['offset_s'] for r in samples if r.get('workerPid') not in (None,old_pid)),None)
        axs[0,column].plot([r['offset_s'] for r in samples],[r['pending'] for r in samples],color='#2563eb',label='Задач в очереди')
        axs[1,column].scatter([r['offset_s'] for r in changes],[r['freshness_ms'] for r in changes],color='#ea580c',s=10)
        for axis in axs[:,column]:
            axis.axvline(case['duration_s']/3,color='#dc2626',linestyle='--',label='Запрошено падение')
            if new_pid_at is not None: axis.axvline(new_pid_at,color='#16a34a',linestyle=':',label='Наблюдён новый PID')
            axis.set_ylim(bottom=0)
        axs[0,column].set_title(f'{variant}: {rate} изменений/с + 4 чтения/с'); axs[0,column].set_ylabel('Очередь, задач'); axs[0,column].legend(fontsize=8)
        axs[1,column].set_ylabel('Свежесть изменения, мс'); axs[1,column].set_xlabel('Секунды от начала сценария')
    fig.suptitle('Восстановление проекции после падения обработчика')
    for suffix in ('png','svg'): fig.savefig(out/('recovery.'+suffix))
    plt.close(fig)
    lines=['# H3: проекция по затронутым оценкам','',
        f"Проверка полноты данных: {summary['passed']}. Совместные критерии H3 выполнены: {summary['h3_criteria_met']}.",
        '', '19 200 чтений, 84 смешанных сценария, 11 340 исправлений и 10 080 чтений; отдельно 20 burst-сценариев / 400 исправлений. Прогрев и наблюдатели свежести — дополнительная нагрузка.', '',
        '| Критерий, заданный до основной серии | Выполнен |','|---|---|']
    lines += [f"| {k} | {v} |" for k,v in summary['criteria'].items()]
    lines += ['', '| Профиль | original | optimized | projection | incremental | incremental / optimized, 95% CI |','|---|---:|---:|---:|---:|---|']
    for name,profile in summary['profiles'].items():
        group=profile['groups']['current-1']; ratio=profile['incremental_over_optimized']['current-1']
        values=[group[v]['median_block_p95_ms'] for v in VARIANTS]
        lines.append(f"| {name} | {values[0]:.1f} | {values[1]:.1f} | {values[2]:.1f} | {values[3]:.1f} | {ratio['ratio']:.3f} [{ratio['ci95'][0]:.3f}; {ratio['ci95'][1]:.3f}] |")
    lines += ['', 'Медиана p95 десяти блоков, мс, текущий срез, конкурентность 1. Парные геометрические отношения; bootstrap 10 000. Остальные срезы и конкурентность — в summary.json.',
        '', '![Рост истории](read-scaling.png)', '', '![Парные отношения](paired-ratios.png)', '',
        '| Вариант | Изменений/с | Чтение p95, мс | Запись p95, мс | Свежесть p95, мс | WAL/изменение, байт |','|---|---:|---:|---:|---:|---:|']
    for rate in (1,8):
        for variant in VARIANTS:
            value=summary['mixed']['groups'][variant+'-'+str(rate)]
            lines.append(f"| {variant} | {rate} | {value['read_p95_ms']:.1f} | {value['write_p95_ms']:.1f} | {value['freshness_p95_ms']:.1f} | {value['wal_bytes_per_update']:.1f} |")
    lines += ['', 'p95 в смешанной таблице объединяет успешные запросы и служит описательной статистикой. Критерий свежести проверяется отдельно в каждом повторе.', '', '![Чтение, свежесть, WAL](mixed-tradeoffs.png)', '',
        '| Изменений/с | WAL incremental / projection, 95% CI | SQL execution incremental / projection, 95% CI | p95 записи incremental / projection, 95% CI |','|---|---|---|---|']
    for rate in ('1','8'):
        wal=summary['mixed']['paired'][rate]['walBytes']; sql=summary['mixed']['paired'][rate]['executionMs']
        write=summary['mixed']['paired'][rate]['write_p95_ms']
        lines.append(f"| {rate} | {wal['ratio']:.4f} [{wal['ci95'][0]:.4f}; {wal['ci95'][1]:.4f}] | {sql['ratio']:.3f} [{sql['ci95'][0]:.3f}; {sql['ci95'][1]:.3f}] | {write['ratio']:.3f} [{write['ci95'][0]:.3f}; {write['ci95'][1]:.3f}] |")
    lines += ['', 'p50 чтения, задержки от запланированного поступления и число запросов наблюдателей доступны в CSV и summary.json. Они сохранены как описательные показатели; критерии H3 не менялись после старта.', '']
    lines += ['', '![Восстановление при 8 изменениях/с](recovery.png)', '',
        f"Максимальная свежесть кандидата при сбоях: {recovery_max}. Проверены смена PID, счётчик падения, пустая очередь и повторная видимость принятых изменений.", '',
        f"Функциональные проверки: {validation['cases']} сценариев, {validation['query_pairs']} пар аналитических ответов; дополнительно сравниваются все факты и оценки, включая не последние.", '',
        f"Burst при остановленных worker: {summary['coalescing']}. Это проверка объединения изменений, не штатной свежести.", '',
        'WAL — сумма pg_stat_statements.wal_bytes; не полные физические записи SSD. Время SQL включает ожидание и не является CPU БД. Фиксированная стоимость аренды не уменьшается от меньшего CPU.', '',
        'Ограничения: один день, одна пара ВМ, синтетические данные, 10 повторов; исторический срез 2020-01-02. Bootstrap интервалы дополнительных сравнений точечные. CPU БД и память — по телеметрии, без точной атрибуции отдельных запросов. Проверена выбранная аналитическая ручка; это не автоматический вывод о всей системе Firefly.']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({'passed':summary['passed'],'read_requests':len(all_reads),'mixed':{k:v for k,v in summary['mixed'].items() if k!='groups'},'output':str(out)},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main(Path(sys.argv[1]))
