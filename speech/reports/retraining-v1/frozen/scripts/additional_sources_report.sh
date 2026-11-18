#!/bin/sh
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
frozen="$repo/reports/additional-sources-v1/frozen"
test -f "$frozen/manifest.json" || { printf '%s\n' 'Frozen experiment source is missing' >&2; exit 2; }
action=${1:-score}
case "$action" in
  score) module=scripts.additional_asr_experiment; set -- score ;;
  report) module=scripts.report_additional_sources; set -- ;;
  verify) module=scripts.verify_additional_sources; set -- ;;
  *) printf '%s\n' 'Usage: additional_sources_report.sh [score|report|verify]' >&2; exit 2 ;;
esac
exec docker run --rm --network none --entrypoint python \
  -v "$frozen/scripts:/app/scripts:ro" \
  -v "$frozen/src:/app/src:ro" \
  -v "$frozen/configs:/app/configs:ro" \
  -v "$frozen/ACCEPTANCE.yaml:/app/ACCEPTANCE.yaml:ro" \
  -v "$frozen/uv.lock:/app/uv.lock:ro" \
  -v "$repo/scripts/report_additional_sources.py:/app/scripts/report_additional_sources.py:ro" \
  -v "$repo/scripts/verify_additional_sources.py:/app/scripts/verify_additional_sources.py:ro" \
  -v "$repo/reports:/reports" \
  -v "$repo/data/curated/additional-audio-v1:/additional-audio:ro" \
  -v "$repo/data/curated/cvr-native-v1:/cvr:ro" \
  -v "$repo/data/input/bleriot/bleriot-b:/source-b:ro" \
  -v "$repo/data/input/fleurs-ru-v1:/fleurs:ro" \
  -v north55-speech_audio_data:/audio:ro \
  -v north55-speech_model_cache:/models:ro \
  north55-speech:login-fix-v1 -m "$module" "$@"
