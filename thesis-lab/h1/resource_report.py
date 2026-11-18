"""Host/native plots plus cgroup resource observations for the H1 run."""
from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path
import sys
from h1.host_resource_report import main as host_report
from cloud.monitoring import percentile


def main(run):
    host_report(run)
    start=datetime.fromisoformat(json.loads((run/'main-started.json').read_text())['at']).timestamp()
    end=datetime.fromisoformat(json.loads((run/'main-complete.json').read_text())['at']).timestamp()
    groups=defaultdict(list)
    for role in ('server','loadgen'):
        for line in (run/'artifacts'/role/'telemetry/host-samples.jsonl').read_text().splitlines():
            row=json.loads(line)
            if not start<=row['time']<=end:continue
            for c in row['containers']:
                groups[(role,c['container'])].append({'time':row['time'],**c})
    summary={'note':'Cgroup snapshots every ten seconds, across the whole main window including preparation. Positive CPU counter differences are summed only within each container ID. Intervals with a detected counter reset are omitted; unsampled resets, boundary intervals and short-lived containers prevent an exact lifetime total. No exact attribution to a benchmark variant is claimed.','containers':{}}
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.family':'DejaVu Sans','figure.dpi':150,'axes.spines.top':False,'axes.spines.right':False,'axes.grid':True,'grid.alpha':.2})
    fig,axes=plt.subplots(2,1,figsize=(12,7),layout='constrained',sharex=True)
    selected=('db','functional')
    colors={'functional':'#16a34a','db':'#111827','original':'#64748b','optimized':'#2563eb','projection':'#ea580c','incremental':'#16a34a','worker':'#c2410c','worker-incremental':'#86a61b'}
    for (role,name),samples in sorted(groups.items()):
        segments=defaultdict(list)
        for row in samples:segments[row['id']].append(row)
        deltas=[b['cpu_seconds']-a['cpu_seconds'] for segment in segments.values() for a,b in zip(segment,segment[1:])]
        cpu=sum(max(0,value) for value in deltas)
        summary['containers'][role+'/'+name]={'samples':len(samples),'container_ids':len(segments),
            'observed_positive_cpu_deltas_seconds':cpu,'detected_cpu_counter_resets':sum(v<0 for v in deltas),
            'memory_p95_bytes':percentile([r['memory_bytes'] for r in samples],.95),
            'memory_max_bytes':max(r['memory_bytes'] for r in samples),
            'first_sample':samples[0]['time'],'last_sample':samples[-1]['time']}
        if role!='server' or name not in selected:continue
        for i,segment in enumerate(segments.values()):
            # CPU utilization averaged between sampled counters; quota is 2 vCPU per container.
            pairs=list(zip(segment,segment[1:]))
            axes[0].plot([(b['time']-start)/60 for a,b in pairs],
                [(b['cpu_seconds']-a['cpu_seconds'])/(b['time']-a['time']) if b['cpu_seconds']>=a['cpu_seconds'] else float('nan') for a,b in pairs],
                label=name if i==0 else None,color=colors[name],linewidth=.9)
            axes[1].plot([(r['time']-start)/60 for r in segment],[r['memory_bytes']/2**30 for r in segment],
                label=name if i==0 else None,color=colors[name],linewidth=.9)
    axes[0].set_ylabel('CPU·с / с (занятых ядер)');axes[0].set_title('Контейнеры: CPU по разности накопленных счётчиков')
    axes[1].set_ylabel('cgroup memory.current, ГиБ');axes[1].set_xlabel('Минуты от начала основной серии, включая подготовку')
    for ax in axes:ax.set_ylim(bottom=0);ax.legend(ncol=4,fontsize=8)
    for suffix in ('png','svg'):fig.savefig(run/'analysis'/('container-resources.'+suffix))
    plt.close(fig)
    (run/'analysis/cgroup-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary['containers'].get('server/db',{}),indent=2))


if __name__=='__main__':main(Path(sys.argv[1]).resolve())
