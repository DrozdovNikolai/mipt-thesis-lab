"""Verify preregistered matrix and pair technical repetitions; never mutate raw data."""
from collections import defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import sys

VARIANTS=('split_full','split_compact','unified_compact')

def quantile(values,q):
    x=sorted(values);n=(len(x)-1)*q;i=int(n)
    return x[i]+(x[min(i+1,len(x)-1)]-x[i])*(n-i)

def ratio_ci(candidate,baseline):
    assert candidate.keys()==baseline.keys()
    ratios=[math.log(candidate[k]/baseline[k]) for k in sorted(candidate)]
    rng=random.Random(20261004)
    draws=[math.exp(statistics.mean(rng.choices(ratios,k=len(ratios)))) for _ in range(10000)]
    return {'ratio':math.exp(statistics.mean(ratios)),'ci95':[quantile(draws,.025),quantile(draws,.975)],
            'blocks':len(ratios),'method':'paired bootstrap of geometric ratios across technical blocks'}

def cp_lower(success,n,alpha=.025):
    if success==0:return 0.0
    if success==n:return alpha**(1/n)
    low,high=0.0,1.0
    for _ in range(70):
        p=(low+high)/2
        tail=sum(math.exp(math.lgamma(n+1)-math.lgamma(k+1)-math.lgamma(n-k+1)+k*math.log(p)+(n-k)*math.log1p(-p)) for k in range(success,n+1))
        if tail<alpha:low=p
        else:high=p
    return (low+high)/2

def load(run):
    rows=[]
    expected=[]
    for rep in range(8):
        base=run/'artifacts/loadgen/main'/f'r{rep}'
        completed=json.loads((base/'complete.json').read_text())
        own=[json.loads(line) for line in (base/'cases.jsonl').read_text().splitlines()]
        matrix=json.loads((base/'matrix.json').read_text())
        assert len(own)==len(matrix)==completed['cases']==96
        for actual,wanted in zip(own,matrix):
            assert all(actual[k]==v for k,v in wanted.items())
            assert actual['rep']==rep
            verification=json.loads((base/(actual['case_id']+'-verification.json')).read_text())
            fixture=json.loads((base/(actual['case_id']+'-fixture.json')).read_text())
            from h1.verify import compare
            issues=compare(verification['actual'],fixture['expected'])
            assert not actual['correct'] or not issues
            assert actual['wire_bytes']==sum(x['request_bytes']+x.get('response_bytes',0) for x in verification['traffic'])
            assert actual['requests']==len(verification['traffic'])
        rows.extend(own);expected.extend(matrix)
    assert len(rows)==768 and len({r['training_id'] for r in rows})==768
    keys=('rep','cache','rtt_ms','kib_s','gzip','fault','variant')
    assert len({tuple(r[k] for k in keys) for r in rows})==768
    plan_hash=hashlib.sha256((run/'H1_PLAN.md').read_bytes()).hexdigest()
    for rep in range(8):
        start=json.loads((run/f'artifacts/loadgen/main/r{rep}/start.json').read_text())
        assert start['plan_sha256']==plan_hash and not start['smoke']
    for role in ('server','loadgen'):
        before=json.loads((run/(role+'-runtime-files-before-main.json')).read_text())
        after=json.loads((run/(role+'-runtime-files-after-main.json')).read_text())
        assert not before['mismatches'] and not after['mismatches'] and before['files']==after['files']
    return rows

def main(run):
    rows=load(run);out=run/'analysis';out.mkdir(exist_ok=False)
    aggregate=json.loads((run/'aggregate-domain-counts.json').read_text())
    assert all(aggregate[k] for k in ('two_grades_per_training','seven_events_per_training','six_reports_per_training'))
    group=defaultdict(list)
    for r in rows:group[(r['cache'],r['rtt_ms'],r['gzip'],r['fault'],r['variant'])].append(r)
    cells=[]
    for key,items in sorted(group.items()):
        cells.append(dict(zip(('cache','rtt_ms','gzip','fault','variant'),key),n=len(items),
            correct=sum(r['correct'] for r in items),delivery_p50_ms=quantile([r['delivery_ms'] for r in items],.5),
            delivery_p95_ms=quantile([r['delivery_ms'] for r in items],.95),
            bytes_mean=statistics.mean(r['wire_bytes'] for r in items),requests_mean=statistics.mean(r['requests'] for r in items)))
    comparisons=[]
    for cache,rtt,gzip,fault in sorted({k[:4] for k in group}):
        for baseline in VARIANTS[:2]:
            for metric in ('delivery_ms','wire_bytes'):
                cand={r['rep']:r[metric] for r in group[(cache,rtt,gzip,fault,'unified_compact')]}
                base={r['rep']:r[metric] for r in group[(cache,rtt,gzip,fault,baseline)]}
                comparisons.append({'cache':cache,'rtt_ms':rtt,'gzip':gzip,'fault':fault,
                    'baseline':baseline,'metric':metric,**ratio_ci(cand,base)})
    success={v:sum(r['correct'] for r in rows if r['variant']==v) for v in VARIANTS}
    assert all(sum(r['variant']==v for r in rows)==256 for v in VARIANTS)
    diff_lower=cp_lower(success['unified_compact'],256)-(1-cp_lower(256-success['split_full'],256))
    primary=[r for r in comparisons if r['cache']==16384 and r['rtt_ms']==250 and r['gzip'] and r['fault']=='clean' and r['baseline']=='split_full']
    assert len(primary)==2
    criteria={'primary_time_reduced':next(r for r in primary if r['metric']=='delivery_ms')['ci95'][1]<1,
        'primary_bytes_reduced':next(r for r in primary if r['metric']=='wire_bytes')['ci95'][1]<1,
        'completion_noninferiority_2pp_conditional':diff_lower>-.02,
        'zero_correctness_failures':all(r['correct'] for r in rows),
        'all_faults_injected':all(r['fault_injected'] for r in rows)}
    summary={'matrix_verified':True,'criteria':criteria,'criteria_met':all(criteria.values()),
        'cases':len(rows),'successes':success,'per_variant':256,
        'completion_difference_lower95':diff_lower,
        'completion_ci_note':'Conservative Clopper-Pearson/Bonferroni bound conditional on independent Bernoulli trials. Technical cases share hosts and deterministic fault schedules; not a production reliability guarantee.',
        'primary':primary,'cells':cells,'comparisons':comparisons}
    (out/'summary.json').write_text(json.dumps(summary,indent=2))
    with (out/'cells.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=cells[0].keys());writer.writeheader();writer.writerows(cells)
    plots(out,cells,comparisons)
    print(json.dumps({k:summary[k] for k in ('cases','criteria','criteria_met','successes','primary')},indent=2))

def plots(out,cells,comparisons):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    colors=dict(zip(VARIANTS,('#64748b','#2563eb','#16a34a')))
    plt.rcParams.update({'font.family':'DejaVu Sans','figure.dpi':150,'axes.spines.top':False,'axes.spines.right':False,'axes.grid':True,'grid.alpha':.2})
    for metric,label,name,scale in [('delivery_p50_ms','Медиана времени до квитанции, с','delivery',1000),('bytes_mean','Средние байты HTTP на тренировку, KiB','traffic',1024)]:
        fig,axs=plt.subplots(1,2,figsize=(11,4),layout='constrained',sharey=True)
        for ax,cache in zip(axs,(1024,16384)):
            for v in VARIANTS:
                own=sorted([r for r in cells if r['cache']==cache and r['gzip'] and r['fault']=='clean' and r['variant']==v],key=lambda r:r['rtt_ms'])
                ax.plot([r['rtt_ms'] for r in own],[r[metric]/scale for r in own],marker='o',label=v,color=colors[v])
            ax.set_title(f'Справочный текст: {cache//1024} KiB; gzip ответов');ax.set_xlabel('Добавленная RTT, мс');ax.set_ylim(bottom=0);ax.set_xticks([0,80,250])
        maximum=max(r[metric]/scale for r in cells if r['gzip'] and r['fault']=='clean')
        for ax in axs: ax.set_ylim(0,maximum*1.12)
        if all(r['n']==1 for r in cells): fig.suptitle('Локальный пилот: один запуск на точку, без оценки статистической значимости')
        axs[0].set_ylabel(label);axs[-1].legend(fontsize=8)
        for suffix in ('png','svg'):fig.savefig(out/(name+'.'+suffix))
        plt.close(fig)
    fig,ax=plt.subplots(figsize=(11,5),layout='constrained')
    faults=['clean','offline_restart','sync_ack_loss','submit_ack_loss','client_crash_after_submit','server_crash_before_commit']
    for j,v in enumerate(VARIANTS):
        own=[next(r for r in cells if r['variant']==v and r['fault']==fault and r['cache']==16384 and r['rtt_ms']==250 and r['gzip']) for fault in faults]
        ax.bar([i+(j-1)*.25 for i in range(len(faults))],[r['delivery_p50_ms']/1000 for r in own],width=.24,label=v,color=colors[v])
    ax.set_xticks(range(len(faults)),['Без сбоя','Offline +\nрестарт','Потеря\nsync ACK','Потеря\nsubmit ACK','Авария\nклиента','Авария\nbackend'])
    ns=sorted({r['n'] for r in cells if r['cache']==16384 and r['rtt_ms']==250 and r['gzip']})
    repeats=' / '.join(map(str,ns))
    ax.set_ylabel('Медиана до подтверждённой квитанции, с');ax.set_title(f'16 KiB, RTT 250 мс, gzip ответов; число испытаний на условие: {repeats}');ax.legend()
    if ns==[1]: fig.suptitle('Локальный пилот: один запуск на точку, без оценки статистической значимости')
    for suffix in ('png','svg'):fig.savefig(out/('faults.'+suffix))
    plt.close(fig)
    if not comparisons: return
    selected=[r for r in comparisons if r['cache']==16384 and r['rtt_ms']==250 and r['gzip'] and r['fault']=='clean']
    fig,ax=plt.subplots(figsize=(10,4),layout='constrained')
    for i,r in enumerate(selected):
        ax.errorbar(r['ratio'],i,xerr=[[r['ratio']-r['ci95'][0]],[r['ci95'][1]-r['ratio']]],fmt='o',capsize=4,color='#16a34a')
    ax.axvline(1,color='#64748b',linestyle='--');ax.set_yticks(range(len(selected)),[r['metric']+' / '+r['baseline'] for r in selected]);ax.set_xlabel('Отношение unified / baseline, 95% paired bootstrap CI');ax.set_title('Основной профиль: 16 KiB, RTT 250 мс, gzip ответов')
    for suffix in ('png','svg'):fig.savefig(out/('paired-ratios.'+suffix))
    plt.close(fig)

if __name__=='__main__':main(Path(sys.argv[1]).resolve())
