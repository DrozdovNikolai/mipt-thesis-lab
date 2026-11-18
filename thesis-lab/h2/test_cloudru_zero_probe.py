import pytest
from h2.cloudru_zero_probe import Probe, ProbeCloud, validate_handoff


def test_zero_requires_real_disappearance_of_both_vm_and_disk():
    p = Probe(None)
    point = {'vms': [], 'disks': [], 'ready_nodes': []}
    assert not p.matches(point, 0)
    p.vm_ids.add('vm'); p.disk_ids.add('disk')
    assert p.matches(point, 0)
    assert not p.matches({**point, 'disks': [{'id': 'disk'}]}, 0)
    assert not p.matches({**point, 'vms': [{'id': 'vm', 'state': 'stopped'}]}, 0)


def test_borrowed_cluster_and_system_pool_cannot_be_deleted():
    cloud = ProbeCloud.__new__(ProbeCloud)
    for fn in (cloud.stop, cloud.cleanup, lambda: cloud.delete_group('system')):
        with pytest.raises(ValueError):
            fn()


def test_handoff_requires_finished_control_and_no_cleanup_in_flight():
    state = {'cluster': {'id': 'cluster', 'name': 'name'}, 'project_id': 'project',
             'groups': {'system': {}, 'main-mixed-fixed': {'deleted_at': 'done'}}}
    retired = {'trial': 'main-mixed-fixed', 'backup_verified': True, 'at': '2026-10-16T08:10:00Z'}
    cluster = {'id': 'cluster', 'name': 'name', 'projectId': 'project', 'status': 'OBJECT_STATUS_RUNNING'}
    validate_handoff(state, retired, cluster, [])
    with pytest.raises(ValueError):
        validate_handoff(state, retired, cluster, [{'name': 'request', 'label': 'stop', 'at': '2026-10-16T08:11:00Z'}])
    state['groups']['main-mixed-fixed'] = {}
    with pytest.raises(ValueError):
        validate_handoff(state, retired, cluster, [])
