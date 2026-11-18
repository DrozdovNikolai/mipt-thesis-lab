---
dataset_info:
  features:
  - name: audio
    dtype:
      audio:
        sampling_rate: 16000
  - name: text
    dtype: string
  - name: label
    dtype: int64
  - name: voice
    dtype: string
  - name: speed
    dtype: float64
  - name: noise_level
    dtype: float64
  - name: cabin_noise_level
    dtype: float64
  splits:
  - name: train
    num_bytes: 129143918.25
    num_examples: 1182
  download_size: 129060802
  dataset_size: 129143918.25
configs:
- config_name: default
  data_files:
  - split: train
    path: data/train-*
---
