# Model card

Status: research implementation; no validated cockpit quality or release candidate.

Latest adaptation experiment: [nus-retention-v1](../reports/nus-retention-v1/report.md).
Two fresh decoder LoRAs trained on the existing 275 NUS + 200 EN + 200 RU pairs,
1200 actual updates each: matched CE control versus CE + KL against the immutable
original Whisper-small. Both use BF16 training and CT2 float16 inference. KL reduces
EN regression (7.99% → 5.44% WER), but the parent remains better (3.62%); cockpit
dev is 24.35% for both versus parent 13.91%. RU and non-speech guards also fail.
These diagnostic weights are not released or served. 51 tests, 868 GPU ASR and
4 CPU smokes, optimizer/base/teacher identity checks and PS/Linux replay executed.
NUS fit is training error; five exposed human clips do not establish independent
quality, and no critical-entity or temporal labels were manufactured.

CPU baseline: Systran/faster-whisper-small, multilingual Whisper small conversion,
revision `536b0662742c02347bc0e980a01041f333bce120`, runtime int8, beam 5, temperature 0.
`model.bin` SHA-256:
`3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671`.
The complete actual acquisition manifest resides at `/models/small/manifest.json`.

CPU and GPU (CUDA/float16) human-audio smoke inference have executed. These are
engineering controls on LibriSpeech and now FLEURS RU, not a test of cockpit speech or evidence that
GPU precision improves accuracy. Large-v3 remains an optional separately acquired
main GPU research checkpoint. A separate pinned SYSTRAN large-v3 CT2 diagnostic
is now executed; its results and restrictions are below.

EN, RU, mixed and auto are input modes. None has confirmed cockpit quality. Mixed
uses the pinned backend's multilingual option; short code-switches and language
detection remain unvalidated. Forced translation is forbidden. No cloud inference
is required after acquisition. Missing weights fail explicitly.

Rules are the default event baseline with unknown salience. The TF-IDF word/character
OneVsRest logistic classifier and separate salience model are implemented and fitted
in synthetic code tests only. There is no released classifier trained on independent
human cockpit event labels. Safe skops artifacts require local checksums; arbitrary
uploaded pickle models are not accepted. Probabilities are not calibrated correctness.

A separate Noort source-native safety-voice model has now been trained on 2838
human-labelled text rows, with 394 dev rows and a frozen 49-row/one-case holdout.
The selected word/character logistic model includes only the immediately preceding
admitted turn. Holdout macro-F1 .5000 is below broad rules .6449; generalization is
INCONCLUSIVE. It is neither the project's event/salience model nor temporal event
detection, and has not been installed in serving. See [additional_sources](additional_sources.md).

LoRA uses local Transformers/PEFT weights, supervised loss, dev early stopping,
checkpoints, merge and CTranslate2 conversion plus a real converted-model smoke path.
Two bounded 40-step publisher-reference runs have executed, with local adapters,
merged/converted models and actual CPU/GPU inference. These weak script alignments
are not independent gold. The expanded run worsened clean publisher disagreement
and noise insertion rates; no adapted model was promoted. See
[all_sources_experiment](all_sources_experiment.md).

The latest pause-handling experiment uses the same pinned OpenAI Whisper-small
parent CT2 checkpoint and CUDA/float16 for all five systems, on 661 inputs.
Gate+denoise changes partial human dev WER from 34/115 to 33/115 (2.94% relative),
paired 95% CI delta [-.043478, 0]. It does not meet the 10% target or significance.
The separate general RU control changes 9.55% to 9.23%; unknown speaker identities
prevent independent-cluster inference. Noise gating has a measured diagnostic
benefit, but no stage is activated without the required critical-entity and final
test gates. The production Systran CPU baseline above remains unchanged.

Whisper pretraining overlap with public corpora cannot be excluded. Read speech,
including the latest dev diagnostics, remains distinct from independent evaluation.
The large-v3 experiment ran 661 inputs on GPU and three CPU smoke samples. Passing
the five saved EN language declarations reduces small errors 34→16; large with
that same EN gives 20 errors. General RU improves 9.55%→5.21%, but general EN and
noise guardrails fail. The model is stored locally as whisper-large-v3-systran-ct2
at SYSTRAN revision edaa852ec7e145841d8ffdb056a99866b5f0a478 (MIT).
No deployment/pipeline quality claim follows; see [language_large](language_large.md).

Read speech,
synthetic additive noise and general English controls do not demonstrate natural
crew dialogue, real flight acoustics, RU quality, speaker identity or pilot skill.
