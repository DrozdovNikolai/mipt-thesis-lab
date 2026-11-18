"""Recompute checks from archived journals and traffic without changing raw files."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

from h1.journal import encode, receipt_matches
from h1.verify import compare


def main(run):
    checks = []
    for rep in range(8):
        base = run / f'artifacts/loadgen/main/r{rep}'
        rows = [json.loads(line) for line in (base / 'cases.jsonl').read_text().splitlines()]
        for row in rows:
            case = row['case_id']
            fixture = json.loads((base / (case + '-fixture.json')).read_text())
            verification = json.loads((base / (case + '-verification.json')).read_text())
            traffic = verification['traffic']
            db = sqlite3.connect((base / (case + '.sqlite')).resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
            intent = db.execute('SELECT expected,submit_body,sha256 FROM intent').fetchall()
            receipts = db.execute('SELECT body FROM receipt').fetchall()
            remaining = db.execute('SELECT count(*) FROM queue').fetchone()[0]
            integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
            db.close()
            valid_intent = len(intent) == 1 and (
                json.loads(intent[0][0]) == fixture['expected']
                and intent[0][1] == encode(fixture['queue'][-1]['body'])
                and intent[0][2] == hashlib.sha256(intent[0][1].encode()).hexdigest())
            valid_receipt = len(receipts) == 1 and receipt_matches(json.loads(receipts[0][0]), fixture['expected'])
            submits = [t for t in traffic if t['path'].endswith('/submit')]
            immutable_wire = bool(submits) and {t['request_body_sha256'] for t in submits} == {intent[0][2]}
            fault = row['fault']
            lost = [t for t in traffic if t.get('dropped') == 'after_backend_response']
            injected = fault == 'clean'
            if fault == 'offline_restart':
                injected = 77 in row['exit_codes'] and len(set(row['pids'])) == 2 and any(t.get('dropped') == 'before_forward' for t in traffic)
            elif fault in ('sync_ack_loss', 'submit_ack_loss'):
                suffix = '/submit' if fault == 'submit_ack_loss' else ('/draft' if row['variant'] == 'split_full' else '/sync')
                injected = len(lost) == 1 and lost[0]['path'].endswith(suffix)
            elif fault == 'client_crash_after_submit':
                injected = row['exit_codes'] == [77, 0] and len(set(row['pids'])) == 2
            elif fault == 'server_crash_before_commit':
                rollback = row['server_after']['last_rollback']
                injected = (row['server_before']['instance'] != row['server_after']['instance']
                            and rollback['training_id'] == row['training_id'] and rollback['passed']
                            and not rollback['submitted'] and not rollback['sealed'] and rollback['grades'] == 0
                            and any(t.get('dropped') == 'upstream_transport' for t in traffic))
            result = {'case_id': case, 'sqlite_integrity': integrity == 'ok', 'intent_unchanged': valid_intent,
                      'receipt_matches': valid_receipt, 'queue_empty': remaining == 0,
                      'submit_wire_unchanged': immutable_wire, 'fault_injected': bool(injected),
                      'domain_parity': not compare(verification['actual'], fixture['expected'])}
            result['passed'] = all(v for k, v in result.items() if k != 'case_id')
            checks.append(result)
    assert len(checks) == 768
    summary = {'cases': len(checks), 'passed': all(r['passed'] for r in checks), 'checks': checks,
               'note': 'Read-only recomputation from archived SQLite, HTTP trace and PostgreSQL oracle; no raw files modified.'}
    with (run / 'analysis/archive-audit.json').open('x') as stream:
        json.dump(summary, stream, indent=2)
    print(json.dumps({k: summary[k] for k in ('cases', 'passed')}))


if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve())
