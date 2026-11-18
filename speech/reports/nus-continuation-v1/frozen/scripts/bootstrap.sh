#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ -e .env ]; then echo '.env exists; preserved.'; exit 0; fi
umask 077
for key in POSTGRES_PASSWORD RABBITMQ_PASSWORD NORTH55_API_KEY NORTH55_SESSION_SECRET; do
  value=$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')
  printf '%s=%s\n' "$key" "$value" >> .env
done
mkdir -p data/input data/curated data/manifests/train-dev data/manifests/test-inference data/sealed reports
echo 'Created local .env. Secrets were not printed.'

