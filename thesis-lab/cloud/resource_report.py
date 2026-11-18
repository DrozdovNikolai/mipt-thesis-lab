"""Describe resource pressure and telemetry completeness without rejecting slow runs."""

from datetime import datetime
import json
from pathlib import Path
import sys

from cloud.monitoring import percentile
from cloud.ops import save


def load_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def main(run):
    output = run/'analysis'
    if (output/'resource-summary.json').exists():
        raise RuntimeError('Preserve the existing resource analysis')
    start = datetime.fromisoformat(json.loads((run/'main-started.json').read_text())['at']).timestamp()
    end = datetime.fromisoformat(json.loads((run/'main-complete.json').read_text())['at']).timestamp()
    summary = {'window_start': start, 'window_end': end, 'roles': {},
               'note': 'Ten-second samples; percentiles describe observed host pressure, not hypothesis tests. No measurements are removed.'}
    selected = {}
    names = ('host_cpu_percent','host_memory_used_bytes','host_iowait_percent','host_steal_percent')
    for role in ('server','loadgen'):
        telemetry = run/'artifacts'/role/'telemetry'
        samples = load_rows(telemetry/'metric-points.jsonl')
        samples = [r for r in samples if start<=datetime.fromisoformat(r['ts']).timestamp()<=end]
        selected[role] = samples
        totals = {}
        active = {}
        for name in names:
            observations = [m['value'] for r in samples for m in r['metrics'] if m['name']=='firefly_'+name]
            measurements = [m['value'] for r in samples for m in r['metrics']
                            if m['name']=='firefly_'+name and m['labels']['phase'] in ('reads','mixed')]
            totals[name] = {'p50': percentile(observations,.5), 'p95': percentile(observations,.95), 'max': max(observations)}
            active[name] = {'p50': percentile(measurements,.5), 'p95': percentile(measurements,.95), 'max': max(measurements)}
        times = [datetime.fromisoformat(r['ts']).timestamp() for r in samples]
        logs = [r for r in load_rows(telemetry/'metrics-export.jsonl')
                if start<=datetime.fromisoformat(r['at']).timestamp()<=end]
        summary['roles'][role] = {'sample_batches': len(samples),
            'max_sample_gap_seconds': max(b-a for a,b in zip(times,times[1:])),
            'export_batches': len(logs), 'export_errors': [r for r in logs if 'error' in r],
            'whole_window': totals, 'read_and_mixed_phases': active}

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.family':'DejaVu Sans','figure.dpi':150,'axes.spines.top':False,'axes.spines.right':False,'axes.grid':True,'grid.alpha':.2})
    fig, axes = plt.subplots(2,2,figsize=(12,7),layout='constrained',sharex=True)
    titles = ('CPU гостевой ОС, %','RAM гостевой ОС, ГиБ','Ожидание диска, %','Steal CPU, %')
    for axis,name,title in zip(axes.flat,names,titles):
        for role,color in (('server','#2563eb'),('loadgen','#ea580c')):
            pairs = [(datetime.fromisoformat(r['ts']).timestamp(),m['value']) for r in selected[role] for m in r['metrics'] if m['name']=='firefly_'+name]
            factor = 2**30 if name=='host_memory_used_bytes' else 1
            axis.plot([(t-start)/60 for t,v in pairs],[v/factor for t,v in pairs],label=role,color=color,linewidth=1)
        axis.set_title(title); axis.set_ylim(bottom=0); axis.legend()
    for axis in axes[-1]: axis.set_xlabel('Минуты от начала основной серии, включая подготовку профилей')
    fig.suptitle('Гостевые метрики: исходные точки, отправленные в Yandex Monitoring')
    for suffix in ('png','svg'): fig.savefig(output/('guest-resources.'+suffix))
    plt.close(fig)

    exports = sorted(run.glob('monitoring-export-*/compute-response.json'))
    native = json.loads(exports[-1].read_text())
    fig, axis = plt.subplots(figsize=(11,4),layout='constrained')
    counts = {}
    for metric in native['metrics']:
        if metric['name']!='cpu_usage': continue
        series = metric['timeseries']
        values = series.get('doubleValues',series.get('int64Values',[]))
        pairs = [(t/1000,float(v)) for t,v in zip(series['timestamps'],values) if start<=t/1000<=end]
        label = metric['labels']['resource_id']
        counts[label] = len(pairs)
        color='#ea580c' if 'loadgen' in label else '#2563eb'
        axis.plot([(t-start)/60 for t,v in pairs],[v for t,v in pairs],label=label,color=color,linewidth=1.2)
    axis.set_ylabel('CPU в Yandex Monitoring, %'); axis.set_xlabel('Минуты от начала основной серии'); axis.set_ylim(bottom=0); axis.legend()
    axis.set_title('Нативная cpu_usage: данные API Compute / Monitoring')
    for suffix in ('png','svg'): fig.savefig(output/('native-cpu.'+suffix))
    plt.close(fig)
    summary['native_cpu_points'] = counts
    summary['native_export_file'] = str(exports[-1].relative_to(run))
    save(output/'resource-summary.json',summary)
    print(json.dumps({role:{k:v for k,v in data.items() if k not in ('whole_window','read_and_mixed_phases')} for role,data in summary['roles'].items()},indent=2))


if __name__=='__main__':
    main(Path(sys.argv[1]).resolve())
