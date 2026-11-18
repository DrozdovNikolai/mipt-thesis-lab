#!/bin/sh
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
action=${1:-score}
case "$action" in
  score) module=scripts.evaluate_expanded_sources; set -- score ;;
  report) module=scripts.report_expanded_sources; set -- ;;
  verify) module=scripts.verify_expanded_sources; set -- ;;
  *) printf '%s\n' 'Usage: all_sources_report.sh [score|report|verify]' >&2; exit 2 ;;
esac
exec docker run --rm --network none --entrypoint python \
  -v "$repo/scripts:/app/scripts:ro" \
  -v "$repo/src:/app/src:ro" \
  -v "$repo/configs:/app/configs:ro" \
  -v "$repo/ACCEPTANCE.yaml:/app/ACCEPTANCE.yaml:ro" \
  -v "$repo/reports:/reports" \
  -v "$repo/data/curated/publisher-expanded-v1:/expanded:ro" \
  -v "$repo/data/curated/voici-diagnostic-v1:/voici-diagnostic:ro" \
  -v north55-speech_audio_data:/audio:ro \
  -v north55-speech_model_cache:/models:ro \
  north55-speech:login-fix-v1 -m "$module" "$@"
