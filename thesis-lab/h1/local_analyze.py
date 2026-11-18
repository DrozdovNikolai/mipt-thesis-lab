"""Audit the single local pilot without inferring statistical significance."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics

from h1.analyze import plots, quantile
from h1.verify import compare


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('pilot', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    rows = [json.loads(line) for line in (args.pilot / 'cases.jsonl').read_text().splitlines()]
    matrix = json.loads((args.pilot / 'matrix.json').read_text())
    assert len(rows) == len(matrix) == 96
    assert len({r['training_id'] for r in rows}) == 96
    for row, wanted in zip(rows, matrix):
        assert all(row[key] == value for key, value in wanted.items())
        evidence = json.loads((args.pilot / (row['case_id'] + '-verification.json')).read_text())
        fixture = json.loads((args.pilot / (row['case_id'] + '-fixture.json')).read_text())
        assert not compare(evidence['actual'], fixture['expected'])
        assert row['correct'] and row['fault_injected']
        assert row['wire_bytes'] == sum(t['request_bytes'] + t.get('response_bytes', 0) for t in evidence['traffic'])
        assert row['requests'] == len(evidence['traffic'])

    keys = ('cache', 'rtt_ms', 'gzip', 'fault', 'variant')
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row[k] for k in keys)].append(row)
    cells = [dict(zip(keys, key), n=len(group), correct=sum(r['correct'] for r in group),
                  delivery_p50_ms=quantile([r['delivery_ms'] for r in group], .5),
                  delivery_p95_ms=quantile([r['delivery_ms'] for r in group], .95),
                  bytes_mean=statistics.mean(r['wire_bytes'] for r in group),
                  requests_mean=statistics.mean(r['requests'] for r in group))
             for key, group in sorted(groups.items())]
    assert len(cells) == 96 and all(c['n'] == 1 for c in cells)
    primary = [r for r in rows if r['cache'] == 16384 and r['rtt_ms'] == 250 and r['gzip'] and r['fault'] == 'clean']
    summary = {'cases': len(rows), 'passed': True, 'technical_blocks': 1, 'confirmatory': False,
               'note': 'Shared local WSL/Docker host, technical validation only; no CI or significance claim.',
               'primary': primary, 'cells': cells}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2))
    plots(args.output, cells, [])
    print(json.dumps({'cases': len(rows), 'passed': True,
                      'primary': [{k:r[k] for k in ('variant','delivery_ms','wire_bytes','requests')} for r in primary]}, indent=2))


if __name__ == '__main__':
    main()
