"""Validate the declared cloud matrix and produce figures without changing raw data."""

from collections import Counter, defaultdict
from datetime import UTC, datetime
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import sys

from cloud.monitoring import percentile
from cloud.run import PROFILES

VARIANTS=('original','optimized','projection')
COLORS={'original':'#64748b','optimized':'#2563eb','projection':'#ea580c'}


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
    all_reads=[]
    for profile in PROFILES:
        name=profile['id']
        directory=root/'reads'/name
        checks=rows(directory/'read-checks.jsonl')
        http=rows(directory/'read-http.jsonl')
        series=rows(directory/'read-series.jsonl')
        assert len(checks)==24 and all(r['passed'] for r in checks),name
        assert len(http)==2400 and len(series)==120,name
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
                        'backend_cpu_ms_per_request':1000*sum(r['backend_cpu_seconds'] for r in selected)/sum(r['requests'] for r in selected),
                        'sql_execution_ms_per_request':sum(r['sql_delta']['executionMs'] for r in selected)/sum(r['requests'] for r in selected)}
                groups[key]=per_variant
                comparisons[key]=paired_ci(per_variant['projection']['p95_by_rep'],per_variant['optimized']['p95_by_rep'])
        summary['profiles'][name]={'http_requests':len(http),'read_checks':len(checks),'errors':errors,'groups':groups,'projection_over_optimized':comparisons}
        all_reads.extend(http)
    assert len(all_reads)==14400
    mixed=root/'mixed/history-100k'
    mixed_checks=rows(mixed/'read-checks.jsonl')
    assert len(mixed_checks)==24 and all(r['passed'] for r in mixed_checks)
    cases=rows(mixed/'mixed-series.jsonl')
    writes=rows(mixed/'mixed-writes.jsonl')
    mixed_reads=rows(mixed/'mixed-reads.jsonl')
    queue_samples=rows(mixed/'mixed-queue.jsonl')
    assert len(cases)==20 and len(writes)==2700 and len(mixed_reads)==2400
    expected=Counter([(rep,rate,v,False) for rep in range(3) for rate in (1,8) for v in VARIANTS]+[(0,rate,'projection',True) for rate in (1,8)])
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
    summary['mixed']['fault_cases']=[{'write_rate':r['write_rate'],'worker_before':r['worker_before'],'worker_after':r['worker_after'],'converged':r['converged'],'not_visible_before_deadline':r['not_visible_before_deadline']} for r in cases if r['crash']]
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
                'scheduled_to_ack_p95_ms':percentile([r['scheduled_to_ack_ms'] for r in selected_writes if r['status']==200],.95),
                'freshness_p95_ms':percentile([r['freshness_ms'] for r in selected_writes if r.get('freshness_ms') is not None],.95),
            }
    summary['passed']=summary['complete_marker_present'] and all(p['errors']==0 for p in summary['profiles'].values()) and all(summary['mixed'][k]==0 for k in ('write_errors','read_errors','not_visible'))
    summary['measurement_notes']={
        'cpu':'Backend process CPU delta includes the resource probe; it is not VM billing or database CPU.',
        'sql':'pg_stat_statements execution time is elapsed SQL execution time, not pure CPU time.',
        'confidence_intervals':'Pointwise paired bootstrap intervals, not adjusted for comparisons across profiles.',
        'mixed':'Three repetitions; pooled successful request percentiles are descriptive, not confidence intervals.',
    }
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
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
        values=[summary['profiles'][p['id']]['projection_over_optimized']['current-'+str(concurrency)] for p in PROFILES]
        means=[r['ratio'] for r in values]
        lower=[max(0,r['ratio']-r['ci95'][0]) for r in values]
        upper=[max(0,r['ci95'][1]-r['ratio']) for r in values]
        ax.errorbar(means,[i+offset for i in range(len(PROFILES))],xerr=[lower,upper],fmt='o',capsize=4,color=color,label=f'{concurrency} клиент(ов)')
    ax.axvline(1,color='#475569',linestyle='--',linewidth=1)
    ax.set_yticks(range(len(PROFILES)),[labels[p['id']] for p in PROFILES]); ax.invert_yaxis(); ax.set_xscale('log')
    ax.set_xlabel('projection / optimized по p95; <1 — быстрее, >1 — медленнее')
    ax.set_title('Текущий срез: парные отношения, точечные bootstrap 95% ДИ'); ax.legend()
    for suffix in ('png','svg'): fig.savefig(out/('paired-ratios.'+suffix))
    plt.close(fig)
    fig,axs=plt.subplots(1,3,figsize=(12,4),layout='constrained')
    for ax,metric,title in zip(axs,('read_p95_ms','freshness_p95_ms','wal_bytes_per_update'),('Чтение, p95, мс','Наблюдаемая свежесть, p95, мс','WAL на изменение, байт')):
        values=[summary['mixed']['groups'][v+'-8'][metric] for v in VARIANTS]
        bars=ax.bar(VARIANTS,values,color=[COLORS[v] for v in VARIANTS]); ax.set_title(title); ax.tick_params(axis='x',rotation=20)
        ax.bar_label(bars,labels=[f'{v:,.1f}' for v in values],padding=3,fontsize=8)
        ax.margins(y=.18)
    fig.suptitle('Смешанная нагрузка: 8 изменений/с + 4 чтения/с, без инъекции сбоев')
    for suffix in ('png','svg'): fig.savefig(out/('mixed-tradeoffs.'+suffix))
    plt.close(fig)
    fig,axs=plt.subplots(2,2,figsize=(11,6),layout='constrained',sharex='col')
    for column,rate in enumerate((1,8)):
        case=next(r for r in cases if r['crash'] and r['write_rate']==rate)
        samples=sorted([r for r in queue_samples if r['crash'] and r['write_rate']==rate],key=lambda r:r['offset_s'])
        changes=sorted([r for r in writes if r['crash'] and r['write_rate']==rate],key=lambda r:r['offset_s'])
        old_pid=case['worker_before']['workerPid']
        new_pid_at=next((r['offset_s'] for r in samples if r.get('workerPid') not in (None,old_pid)),None)
        axs[0,column].plot([r['offset_s'] for r in samples],[r['pending'] for r in samples],color='#2563eb',label='Задач в очереди')
        axs[1,column].scatter([r['offset_s'] for r in changes],[r['freshness_ms'] for r in changes],color='#ea580c',s=10)
        for axis in axs[:,column]:
            axis.axvline(case['duration_s']/3,color='#dc2626',linestyle='--',label='Запрошено падение')
            if new_pid_at is not None: axis.axvline(new_pid_at,color='#16a34a',linestyle=':',label='Наблюдён новый PID')
            axis.set_ylim(bottom=0)
        axs[0,column].set_title(f'{rate} изменений/с + 4 чтения/с'); axs[0,column].set_ylabel('Очередь, задач'); axs[0,column].legend(fontsize=8)
        axs[1,column].set_ylabel('Свежесть изменения, мс'); axs[1,column].set_xlabel('Секунды от начала сценария')
    fig.suptitle('Восстановление проекции после падения обработчика')
    for suffix in ('png','svg'): fig.savefig(out/('recovery.'+suffix))
    plt.close(fig)
    lines=['# Первая облачная серия Firefly — H3 baseline','',f"Проверка матрицы: {'пройдена' if summary['passed'] else 'есть ошибки'}. 14 400 измеряемых запросов чтения; 20 сценариев смешанной нагрузки, 2700 изменений и 2400 чтений. Прогрев, проверки корректности и наблюдатели свежести учитываются отдельно.",'','Это репликация существующих вариантов. Новая проекция по затронутым оценкам и гипотеза Kubernetes/GPU пока не проверены.','','| Профиль | original, мс | optimized, мс | projection, мс | projection / optimized, 95% CI |','|---|---:|---:|---:|---|']
    for name,profile in summary['profiles'].items():
        group=profile['groups']['current-1']; ratio=profile['projection_over_optimized']['current-1']
        values=[group[v]['median_block_p95_ms'] for v in VARIANTS]
        lines.append(f"| {name} | {values[0]:.1f} | {values[1]:.1f} | {values[2]:.1f} | {ratio['ratio']:.3f} [{ratio['ci95'][0]:.3f}; {ratio['ci95'][1]:.3f}] |")
    lines += ['','В таблице — медиана p95 десяти блоков для текущего среза и одного клиента. Отношение — геометрическое среднее парных отношений с bootstrap 95% CI, 10 000 выборок. Значение <1 означает меньший p95 у projection. Десять повторов ограничивают точность оценки; профили не объединяются. Интервалы точечные, без поправки на множественные сравнения.','','![Зависимость времени чтения от истории](read-scaling.png)','','![Парные отношения с доверительными интервалами](paired-ratios.png)','','![Компромисс чтения, свежести и объёма записи](mixed-tradeoffs.png)','','Сырые данные, ошибки транспорта, исходники и условия запуска сохранены отдельно. Синтетическая корректировка одной оценки не эквивалентна полной отправке тренировки. Меньшая загрузка CPU при одинаковых постоянно работающих ВМ сама по себе не доказывает экономию денег.']
    lines += ['','Смешанная нагрузка без сбоев: три повтора на комбинацию. В таблице описательные p95 объединённых запросов; это не доверительные интервалы.','','| Вариант | Изменений/с | Чтение p95, мс | Запись p95, мс | Свежесть p95, мс | WAL/изменение, байт |','|---|---:|---:|---:|---:|---:|']
    for rate in (1,8):
        for variant in VARIANTS:
            value=summary['mixed']['groups'][variant+'-'+str(rate)]
            lines.append(f"| {variant} | {rate} | {value['read_p95_ms']:.1f} | {value['write_p95_ms']:.1f} | {value['freshness_p95_ms']:.1f} | {value['wal_bytes_per_update']:.1f} |")
    lines += ['','![Очередь и свежесть при падении обработчика](recovery.png)','','Для каждого сценария со сбоем проверены увеличение счётчика падений, смена PID, освобождение очереди и повторная видимость принятых изменений. Между опросами очереди — пауза 250 мс; линия нового PID показывает момент его наблюдения, а не точное время запуска процесса.']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({'passed':summary['passed'],'read_requests':len(all_reads),'mixed':{k:v for k,v in summary['mixed'].items() if k!='groups'},'output':str(out)},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main(Path(sys.argv[1]))
