#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
phase="${1:-all}"
case "$phase" in all|h1|h2|h3) ;; *) echo 'Usage: ./run.sh [all|h1|h2|h3]' >&2; exit 2;; esac
run_id="main-$(date -u +%Y%m%dT%H%M%SZ)-$phase"
mkdir -p "results/$run_id"
docker compose config > "results/$run_id/compose.yml"
python3 scripts/record_versions.py "results/$run_id/versions.json"
docker compose stop app baseline
docker compose up -d --wait db redis
docker compose run --rm --no-deps init python /lab/benchmarks/init_db.py --reset
docker compose up -d --wait app
docker compose up -d --wait baseline
docker compose run --rm --no-deps -e "THESIS_OUTPUT=/results/$run_id" runner \
  python -m benchmarks.run --phase "$phase" 2>&1 | tee "results/$run_id/console.log"
python3 scripts/verify_results.py "results/$run_id"
if [[ "$phase" == all || "$phase" == h3 ]]; then
  docker compose run --rm --no-deps runner python /lab/scripts/verify_final_analytics.py \
    "/results/$run_id/final-analytics-audit.json"
fi
python3 scripts/report.py "results/$run_id"
echo "Results: results/$run_id"
