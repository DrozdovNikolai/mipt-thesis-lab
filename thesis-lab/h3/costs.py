"""Archive preliminary folder billing separately from a conservative VM estimate."""

import argparse
from datetime import UTC, datetime
from decimal import Decimal
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from h3.monitoring import Monitoring
from cloud.ops import read, save, yc


def snapshot(run, billing_file=None):
    plan, state = read(run)
    now = datetime.now(UTC)
    stamp = now.isoformat()
    directory = run / 'cost-snapshots' / now.strftime('%Y%m%dT%H%M%SZ')
    directory.mkdir(parents=True, exist_ok=False)
    if billing_file:
        billing = json.loads(billing_file.read_text())
    else:
        day = datetime.fromisoformat(state['created_at']).astimezone(ZoneInfo('Europe/Moscow')).strftime('%Y-%m-%d')
        end_day = now.astimezone(ZoneInfo('Europe/Moscow')).strftime('%Y-%m-%d')
        billing = yc(plan, 'billing', 'consumption-core', 'get-folder-usage-report',
                     plan['billing_account_id'], '--start-date', day+'T00:00:00Z',
                     '--end-date', end_day+'T23:59:59Z', '--folder-ids', plan['folder_id'],
                     '--aggregation-period', 'day')
    assert billing['currency'] == 'RUB'
    save(directory / 'billing.json', billing)
    rates = {k: Decimal(v) for k, v in plan['rates_rub_per_hour'].items()}
    machines = {m['role']: m for m in plan['machines']}
    deletion = {}
    if (run / 'cleanup.json').exists():
        deletion = {r['id']: r['at'] for r in json.loads((run/'cleanup.json').read_text())['removed'] if r['type']=='instance'}
    instances = list(state.get('retired_instances', [])) + [
        {'role': role, 'instance': instance, 'deleted_at': deletion.get(instance['id'], stamp)}
        for role, instance in state['instances'].items()]
    lines = []
    total = Decimal(0)
    for item in instances:
        role, instance = item['role'], item['instance']
        machine = machines[role]
        start = datetime.fromisoformat(instance['created_at'])
        end = datetime.fromisoformat(item['deleted_at'])
        hours = Decimal(str(max(0, (end-start).total_seconds()))) / Decimal(3600)
        hourly = (rates['vcpu']*machine['cores'] + rates['ram_gib']*machine['memory_gib']
                  + rates['network_ssd_gib']*machine['ssd_gib'] + rates['active_public_ipv4'])
        amount = hours * hourly
        total += amount
        lines.append({'id': instance['id'], 'role': role, 'from': start.isoformat(),
                      'to': end.isoformat(), 'hours': float(hours),
                      'rub_per_hour': float(hourly), 'estimated_rub': float(amount)})
    actual = Decimal(billing['cost']['value'])
    credit = Decimal(billing['credit_details']['credit']['value'])
    grant = Decimal(billing['credit_details']['monetary_grant_credit']['value'])
    expense = Decimal(billing['expense']['value'])
    summary = {
        'observed_at': stamp, 'currency': 'RUB', 'estimated_compute_disk_ip_rub': float(total),
        'estimated_instances': lines, 'billing_cost_before_credits_rub': float(actual),
        'billing_total_credit_rub': float(credit), 'billing_grant_credit_rub': float(grant),
        'billing_expense_after_credits_rub': float(expense), 'billing_final': False,
        'billing_source_file': str(billing_file) if billing_file else 'YC ConsumptionCore API',
        'limitations': [
            'Billing covers the folder and includes the earlier baseline run on the same day; delayed charges cannot be assigned exactly to this run or a variant.',
            'Estimate counts all time from creation to deletion, including provisioning and the shutdown test.',
            'Estimate includes retired setup VMs; excludes Monitoring and any other billed services.',
            'Grants are credits against cost; expense after credits is not the resource price.',
        ],
    }
    if (run/'billing-before.json').exists():
        initial=json.loads((run/'billing-before.json').read_text())
        summary['billing_before_launch_rub']=float(initial['cost']['value'])
        summary['billing_observed_change_rub']=float(actual-Decimal(initial['cost']['value']))
        summary['limitations'].append('Observed Billing difference may include delayed prior-run charges; it is not an exact incremental-run invoice.')
    save(directory / 'summary.json', summary)
    labels = {'run_id': state['run_id']}
    values = {'estimated_total_rub': float(total), 'billing_cost_before_credits_rub': float(actual),
              'billing_expense_after_credits_rub': float(expense), 'billing_grant_applied_rub': float(-grant)}
    result = Monitoring(run).write([{'name': 'firefly_'+k, 'labels': labels, 'value': v,
                                    'ts': stamp.replace('+00:00', 'Z')} for k, v in values.items()])
    save(directory / 'monitoring-result.json', result)
    print(json.dumps({k: v for k, v in summary.items() if k not in ('estimated_instances','limitations')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--billing-file', type=Path)
    args = parser.parse_args()
    snapshot(args.run.resolve(), args.billing_file)
