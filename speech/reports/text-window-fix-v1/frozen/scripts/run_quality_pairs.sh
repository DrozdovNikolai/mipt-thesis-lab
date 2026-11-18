#!/bin/sh
set -eu
stage=${1:-prepare}
case "$stage" in prepare|small|large|assemble|tests) ;; *) echo 'Unknown stage' >&2; exit 2;; esac
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
name="north55-quality-pairs-$stage-v1"
if [ -n "$(docker ps -a --filter "name=^/$name$" --format '{{.Names}}')" ]; then
    echo "Container $name exists. Preserve it; use docker start -a $name to resume." >&2
    exit 1
fi
set -- run -d --name "$name" --network none -e CUDA_VISIBLE_DEVICES=0 \
    -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 --entrypoint python \
    -v "$repo/scripts:/app/scripts:ro" -v "$repo/src:/app/src:ro" -v "$repo/tests:/app/tests:ro" \
    -v "$repo/uv.lock:/app/uv.lock:ro" -v "$repo/ACCEPTANCE.yaml:/app/ACCEPTANCE.yaml:ro" \
    -v "$repo/SPEC.md:/app/SPEC.md:ro" -v "$repo/SOURCES.md:/app/SOURCES.md:ro" \
    -v "$repo/reports/pair-quality-v1:/study" -v north55-speech_model_cache:/models:ro
case "$stage" in small|large|assemble) set -- "$@" --gpus all;; esac
case "$stage" in
    small|large)
        set -- "$@" -v "$repo/data/curated/pair-quality-v1/plan.json:/pairs/plan.json:ro" \
            -v "$repo/data/curated/pair-quality-v1/$stage:/pairs/$stage" -v north55-speech_audio_data:/audio:ro;;
    tests) ;;
    *)
        mount=north55-speech_audio_data:/audio:ro
        [ "$stage" != prepare ] || mount=north55-speech_audio_data:/audio
        set -- "$@" -v "$repo/data/curated/pair-quality-v1:/pairs" \
            -v "$repo/data/curated/publisher-expanded-v1:/old:ro" \
            -v "$repo/data/curated/bleriot-v2/manifests/train-dev/train.jsonl:/source-train.jsonl:ro" -v "$mount";;
esac
set -- "$@" north55-speech-gpu:0.1.0
case "$stage" in
    tests) set -- "$@" -m pytest tests/test_quality_pairs.py tests/test_quality_pair_groups.py tests/test_training_support_import.py tests/unit/test_publisher_training.py -q --junitxml=/study/contracts-v3.xml;;
    small|large) set -- "$@" -m scripts.prepare_quality_pairs infer --system "$stage";;
    assemble) set -- "$@" -m scripts.assemble_quality_pairs;;
    *) set -- "$@" -m scripts.prepare_quality_pairs "$stage";;
esac
docker "$@"
echo "Started $name. Read progress with docker logs $name; wait with docker wait $name."
