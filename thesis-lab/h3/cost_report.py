"""Plot observed billing snapshots; never allocate VM charges by CPU utilization."""

from datetime import datetime
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

from cloud.ops import save


def main(run):
    files=sorted(run.glob('cost-snapshots/*/summary.json'))
    rows=[json.loads(file.read_text()) for file in files]
    output=run/'analysis'
    if (output/'cost-summary.json').exists():
        raise RuntimeError('Preserve the existing cost report')
    assert rows
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    plt.rcParams.update({'font.family':'DejaVu Sans','figure.dpi':150,'axes.spines.top':False,'axes.spines.right':False,'axes.grid':True,'grid.alpha':.2})
    fig,axis=plt.subplots(figsize=(11,4.5),layout='constrained')
    times=[datetime.fromisoformat(row['observed_at']) for row in rows]
    for key,label,color in (
        ('estimated_compute_disk_ip_rub','Оценка второго запуска: ВМ, SSD, IPv4','#2563eb'),
        ('billing_cost_before_credits_rub','Billing всего каталога до гранта (оба запуска)','#ea580c'),
        ('billing_expense_after_credits_rub','Billing после зачёта гранта','#64748b'),
    ):
        axis.plot(times,[row[key] for row in rows],marker='o',markersize=3,label=label,color=color)
    axis.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m %H:%M',tz=ZoneInfo('Europe/Moscow')))
    axis.set_ylabel('Накопленные расходы, ₽'); axis.set_xlabel('Время наблюдения, МСК')
    axis.set_ylim(bottom=0); axis.legend(); axis.set_title('Второй запуск: оценка; каталог целиком: предварительный Billing')
    for suffix in ('png','svg'): fig.savefig(output/('costs.'+suffix))
    plt.close(fig)
    summary={'snapshots':len(rows),'source_files':[str(file.relative_to(run)) for file in files],
             'last':rows[-1],
             'notes':['Billing includes the earlier baseline run and can arrive with delay; lines join observations, not billing events.',
                      'The estimate excludes Monitoring and other services; it conservatively includes all creation-to-deletion time.',
                      'All variants share the same fixed VMs. This graph does not show cost savings of a query variant.']}
    save(output/'cost-summary.json',summary)
    print(json.dumps({'snapshots':len(rows),'last_observed_at':rows[-1]['observed_at'],
                      'estimated_rub':rows[-1]['estimated_compute_disk_ip_rub'],
                      'billing_preliminary_rub':rows[-1]['billing_cost_before_credits_rub']},indent=2))


if __name__=='__main__':
    main(Path(sys.argv[1]).resolve())
