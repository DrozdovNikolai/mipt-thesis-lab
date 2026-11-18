#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
trap 'docker compose start rabbitmq worker' EXIT
docker compose stop rabbitmq
docker compose --profile tools run --rm tools selftest create-job --kind short
docker compose start rabbitmq
docker compose --profile tools run --rm tools selftest wait-job --kind short
docker compose --profile tools run --rm tools selftest create-job --kind long
docker compose --profile tools run --rm tools selftest wait-running --kind long
docker compose kill -s SIGKILL worker
docker compose up -d worker
docker compose --profile tools run --rm tools selftest wait-job --kind long
