#!/bin/sh
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
frozen="$repo/reports/language-large-v1/frozen"
action=${1:-score}
case "$action" in
    score) module=scripts.language_large_experiment ;;
    report) module=report_language_large ;;
    verify) module=verify_language_large ;;
    *) printf '%s\n' 'Expected score, report or verify' >&2; exit 2 ;;
esac
set -- docker run --rm --network none --entrypoint python \
    -v "$frozen/scripts:/app/scripts:ro" -v "$frozen/src:/app/src:ro" \
    -v "$frozen/configs:/app/configs:ro" -v "$frozen/ACCEPTANCE.yaml:/app/ACCEPTANCE.yaml:ro" \
    -v "$frozen/uv.lock:/app/uv.lock:ro" \
    -v "$repo/scripts/report_language_large.py:/app/report_language_large.py:ro" \
    -v "$repo/scripts/verify_language_large.py:/app/verify_language_large.py:ro" \
    -v "$repo/reports:/reports" -v "$repo/data/curated/language-large-v1/scoring:/scoring:ro" \
    -v "$repo/data/curated/reviewed-pilot-v2:/reviewed:ro" \
    -v north55-speech_audio_data:/audio:ro -v north55-speech_model_cache:/models:ro \
    north55-speech:login-fix-v1 -m "$module"
if [ "$action" = score ]; then set -- "$@" score; fi
exec "$@"
