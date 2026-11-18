"""One bounded 1 -> 0 -> 1 -> 0 infrastructure probe after the last control.

The original writer is paused only AFTER its last trial has retired and backed
up. A separate manifest owns the probe pool. Its original cluster deadline is
unchanged; the original writer resumes for normal cluster cleanup afterwards.
"""
from datetime import datetime, UTC, timedelta
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import time

from h2.cloudru_ops import Cloud, assert_owned, save, stamp
from h2.cloudru_trial import nodes

TRIAL = 'scale-zero-probe'


def read(path):
    return json.loads(path.read_text())


def process_identity(pid):
    path = Path('/proc') / str(pid)
    command = (path / 'cmdline').read_bytes().replace(b'\0', b' ').decode()
    birth = (path / 'stat').read_text().rsplit(')', 1)[1].split()[19]
    return command, birth


def paused_tree(pid):
    command, birth = process_identity(pid)
    if '-m h2.cloudru_reboot_recovery ' not in command:
        raise ValueError('Expected the recorded recovery writer')
    saved = []

    def pause(target):
        cmd, born = process_identity(target)
        os.kill(target, signal.SIGSTOP)
        saved.append((target, born))
        children = Path(f'/proc/{target}/task/{target}/children').read_text().split()
        for child in children:
            try:
                pause(int(child))
            except FileNotFoundError:
                pass

    try:
        pause(pid)
        return saved
    except BaseException:
        resume_tree(saved)
        raise


def resume_tree(saved):
    for pid, birth in reversed(saved):
        try:
            if process_identity(pid)[1] == birth:
                os.kill(pid, signal.SIGCONT)
        except (FileNotFoundError, ProcessLookupError):
            pass


def validate_handoff(state, retired, cluster, events):
    if not retired['backup_verified'] or retired['trial'] != 'main-mixed-fixed':
        raise ValueError('The last original control must have retired with its backup')
    active = [name for name, g in state['groups'].items() if not g.get('deleted_at')]
    if active != ['system']:
        raise ValueError('Original ASR pools are still active')
    assert_owned(cluster, state['cluster'], state['project_id'])
    if cluster['status'] != 'OBJECT_STATUS_RUNNING':
        raise ValueError('Original cluster is no longer available for a short probe')
    if any(e.get('name') == 'request' and e.get('label') in ('stop', 'delete:cluster')
           and e['at'] >= retired['at'] for e in events):
        raise ValueError('Final cluster cleanup has already started')


class ProbeCloud(Cloud):
    def stop(self):
        raise ValueError('Borrowed cluster belongs to the original cleanup writer')

    def cleanup(self):
        raise ValueError('The probe may remove only its own node pool')

    def delete_group(self, trial_id):
        if trial_id != TRIAL:
            raise ValueError('Only the separately owned probe pool can be deleted')
        return super().delete_group(trial_id)

    def wait_operation(self, service, op, timeout=1200, observe=None):
        return super().wait_operation(service, op, timeout=min(timeout, 600), observe=observe)


class Probe:
    def __init__(self, cloud):
        self.c = cloud
        self.vm_ids, self.disk_ids = set(), set()

    def observe(self):
        c = self.c
        pool = c.state['groups'][TRIAL]
        pool_nodes = nodes(c.client, pool['id'])
        for node in pool_nodes:
            if node['nodePoolId'] != pool['id'] or node['clusterId'] != c.state['cluster']['id']:
                raise ValueError('Node ownership mismatch')
            if node.get('machine', {}).get('id'):
                self.vm_ids.add(node['machine']['id'])
        vms = [v for v in c.client.compute_list('vms')['items'] if v['id'] in self.vm_ids]
        all_disks = c.client.compute_list('disks')['items']
        for d in all_disks:
            if any(v['id'] in self.vm_ids for v in d['vms']):
                self.disk_ids.add(d['id'])
        disks = [d for d in all_disks if d['id'] in self.disk_ids]
        kube_nodes = json.loads(c.kube('get', 'nodes', '-l', 'mk8s.cloud.ru/node-pool-id=' + pool['id'], '-o', 'json'))['items']
        ready = [n['metadata']['name'] for n in kube_nodes if any(
            x['type'] == 'Ready' and x['status'] == 'True' for x in n.get('status', {}).get('conditions', []))]
        point = {'at': stamp(), 'monotonic': time.monotonic(), 'ready_nodes': ready,
            'vms': [{k: v[k] for k in ('id', 'name', 'state', 'created_time')} for v in vms],
            'disks': [{k: d[k] for k in ('id', 'name', 'state', 'created_time', 'size')} for d in disks],
            'known_vm_ids': sorted(self.vm_ids), 'known_disk_ids': sorted(self.disk_ids)}
        save(c.run / 'resource-identities.json', {'pool_id': pool['id'], 'vm_ids': sorted(self.vm_ids), 'disk_ids': sorted(self.disk_ids)})
        with (c.run / 'observations.jsonl').open('a') as stream:
            stream.write(json.dumps(point) + '\n')
        return point

    def matches(self, point, count):
        if count == 0:
            return bool(self.vm_ids and self.disk_ids) and not point['vms'] and not point['disks'] and not point['ready_nodes']
        return (len(point['vms']) == len(point['disks']) == len(point['ready_nodes']) == count
                and all(v['state'] == 'running' for v in point['vms']))

    def wait_ready(self, count, timeout=600):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.c.ensure_time(60)
            point = self.observe()
            if self.matches(point, count):
                return point
            time.sleep(5)
        raise TimeoutError('Capacity did not reach the expected state')

    def scale(self, count, label):
        c = self.c
        c.ensure_time(600)
        pool = c.state['groups'][TRIAL]
        path = '/v3/nodePools/' + pool['id']
        before = c.client.request('mk8s', path)
        assert_owned(before, pool)
        if before['clusterId'] != c.state['cluster']['id'] or 'fixedScale' not in before['scalePolicy']:
            raise ValueError('The probe is the sole scaler of this fixed-size pool')
        started, at, first_match = time.monotonic(), stamp(), None

        def observe():
            nonlocal first_match
            point = self.observe()
            if first_match is None and self.matches(point, count):
                first_match = point

        op = c.mutate('mk8s', path, method='PATCH', label=label,
            body={'nodePoolId': pool['id'], 'scalePolicy': {'fixedScale': {'count': count}}})
        c.wait_operation('mk8s', op, observe=observe)
        operation_seconds = time.monotonic() - started
        final = self.wait_ready(count)
        first_match = first_match or final
        after = c.client.request('mk8s', path)
        assert_owned(after, pool)
        if after['scalePolicy'] != {'fixedScale': {'count': count}}:
            raise ValueError('Scale-policy readback differs from request')
        if before['machineConfiguration'] != after['machineConfiguration']:
            raise ValueError('Scaling changed the machine configuration')
        result = {'phase': label, 'request_at': at, 'count': count,
            'request_to_observed_state_seconds_upper': first_match['monotonic'] - started,
            'request_to_operation_done_seconds': operation_seconds,
            'final': final, 'policy_verified': True, 'same_pool_id': pool['id']}
        save(c.run / (label + '.json'), result)
        print(json.dumps({k: v for k, v in result.items() if k != 'final'}), flush=True)
        return result


def run(original, output, pid):
    output.mkdir(parents=True, exist_ok=False)
    old_state = read(original / 'state.json')
    retired_path = original / 'trials/main-mixed-fixed/retired.json'
    save(output / 'plan.json', {**read(original / 'plan.json'), 'at': stamp(),
        'purpose': 'One actual fixed-pool 1->0->1->0 test; no statistical main series',
        'borrowed_original_run': str(original), 'writer_pid': pid,
        'original_deadline_unchanged': old_state['deadline'], 'probe_workers_max': 1,
        'maximum_probe_minutes': 25, 'start_condition': 'Last original control fully retired and backed up',
        'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    (output / 'cloudru_zero_probe.py').write_bytes(Path(__file__).read_bytes())
    save(output / 'status.json', {'at': stamp(), 'phase': 'waiting_for_last_control', 'pid': os.getpid()})
    print(json.dumps({'phase': 'waiting_for_last_control', 'retirement_file': str(retired_path)}), flush=True)
    paused, cloud, probe, error, cleanup_error = [], None, None, None, None
    try:
        while not retired_path.exists():
            process_identity(pid)
            if datetime.now(UTC) + timedelta(minutes=30) >= datetime.fromisoformat(old_state['deadline']):
                raise TimeoutError('Insufficient original guarded time; no cloud changes made')
            time.sleep(.02)
        paused = paused_tree(pid)
        old_state = read(original / 'state.json')
        probe_deadline = min(datetime.now(UTC) + timedelta(minutes=25),
                             datetime.fromisoformat(old_state['deadline']) - timedelta(minutes=10))
        state = {k: old_state[k] for k in ('project_id', 'runtime', 'cluster', 'subnet', 'flavor_id')}
        state.update(run_id=output.name, prefix='ffzero-' + datetime.now(UTC).strftime('%m%d%H%M%S'),
            created_at=stamp(), deadline=probe_deadline.isoformat(), groups={'system': old_state['groups']['system']},
            borrowed_cluster=True, cleanup_owner_original_run=str(original))
        save(output / 'state.json', state)
        cloud = ProbeCloud(output)
        cluster = cloud.client.request('mk8s', '/v3/clusters/' + state['cluster']['id'])
        events = [json.loads(x) for x in (original / 'events.jsonl').read_text().splitlines()]
        validate_handoff(old_state, read(retired_path), cluster, events)
        save(output / 'handoff.json', {'at': stamp(), 'old_writer_paused': [p for p, _ in paused],
            'last_control_retired': read(retired_path), 'original_shared_cost_extension_separate_probe': True,
            'original_measurement_sources_unchanged': True, 'original_deadline': old_state['deadline']})
        save(output / 'status.json', {'at': stamp(), 'phase': 'creating_one_probe_node', 'pid': os.getpid()})
        print(json.dumps({'phase': 'creating_one_probe_node', 'deadline': state['deadline']}), flush=True)
        cloud.create_group(TRIAL, fixed=1)
        probe = Probe(cloud)
        first = probe.wait_ready(1)
        save(output / 'initial-ready.json', first)
        print(json.dumps({'phase': 'initial_node_ready', 'vm_ids': list(probe.vm_ids)}), flush=True)
        down1 = probe.scale(0, 'down-1')
        up = probe.scale(1, 'up-1')
        down2 = probe.scale(0, 'down-2')
        save(output / 'result.json', {'at': stamp(), 'passed': True,
            'actual_sequence': [1, 0, 1, 0], 'same_pool_preserved_between_steps': True,
            'vm_and_disk_absence_verified_twice': True, 'new_worker_ready_verified': True,
            'down_seconds': [down1['request_to_observed_state_seconds_upper'], down2['request_to_observed_state_seconds_upper']],
            'up_seconds': up['request_to_observed_state_seconds_upper'],
            'scope': 'Fixed node-pool API mechanism. No ASR traffic, autoscaling controller or cost-saving claim.'})
    except BaseException as exc:
        error = str(exc)
        save(output / 'failure.json', {'at': stamp(), 'type': type(exc).__name__, 'error': error})
    finally:
        if cloud and TRIAL in cloud.state['groups']:
            try:
                if probe:
                    point = probe.observe()
                    save(output / 'before-cleanup.json', point)
                cloud.delete_group(TRIAL)
                if probe:
                    remaining_vms = [v['id'] for v in cloud.client.compute_list('vms')['items'] if v['id'] in probe.vm_ids]
                    remaining_disks = [d['id'] for d in cloud.client.compute_list('disks')['items'] if d['id'] in probe.disk_ids]
                    if remaining_vms or remaining_disks:
                        raise ValueError('Probe resources still present after pool cleanup')
                save(output / 'cleanup.json', {'at': stamp(), 'probe_pool_deleted': True,
                    'borrowed_cluster_not_deleted_by_probe': True})
            except BaseException as exc:
                cleanup_error = str(exc)
                save(output / 'cleanup-failure.json', {'at': stamp(), 'error': cleanup_error,
                    'original_cluster_cleanup_will_resume': True})
        resume_tree(paused)
        save(output / 'status.json', {'at': stamp(), 'phase': 'failed' if error or cleanup_error else 'completed',
            'error': error, 'cleanup_error': cleanup_error, 'original_writer_resumed': bool(paused)})
        print(json.dumps(read(output / 'status.json')), flush=True)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *args: (_ for _ in ()).throw(KeyboardInterrupt('Probe interrupted')))
    run(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), int(sys.argv[3]))
