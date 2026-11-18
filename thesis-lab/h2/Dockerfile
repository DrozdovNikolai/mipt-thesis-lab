FROM firefly-backend-celery_worker:latest
ENV HF_HOME=/opt/h2-cache/hf TORCH_HOME=/opt/h2-cache/torch HF_HUB_OFFLINE=1 \
    SPEECH_DEVICE=cpu ASR_PRESET_CPU_MODEL=tiny.en WHISPER_LANGUAGE=en \
    WHISPERX_VAD_METHOD=silero WHISPERX_ENABLE_ALIGNMENT=false \
    OMP_NUM_THREADS=3 MKL_NUM_THREADS=3 OPENBLAS_NUM_THREADS=3 \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN rm -rf /app/app /app/scripts /app/seed /app/alembic /app/runtime /app/.env* \
    && apt-get update && apt-get install -y --no-install-recommends espeak-ng \
    && rm -rf /var/lib/apt/lists/*
COPY app /app/app
COPY scripts /app/scripts
COPY h2 /app/h2
COPY cache/hf /opt/h2-cache/hf
COPY cache/torch /opt/h2-cache/torch
RUN python -m h2.fixtures /fixtures
WORKDIR /app
CMD ["python", "-m", "h2.worker"]
