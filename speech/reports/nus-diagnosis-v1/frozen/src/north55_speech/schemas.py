from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from north55_speech.core import StrictModel, digest

Language = Literal["en", "ru", "mixed", "auto"]
Role = Literal["captain", "first_officer", "instructor", "unknown"]
LABELS = [
    "CHECKLIST",
    "CONFIGURATION_MENTION",
    "REPORTED_DEVIATION",
    "WARNING_MENTION",
    "CREW_COORDINATION",
    "INSTRUCTOR_FEEDBACK",
    "OTHER",
]


class ChannelIdentity(StrictModel):
    speaker_id: str
    role: Role = "unknown"
    provenance: str = Field(min_length=1)


class UploadMetadata(StrictModel):
    language: Language = "auto"
    channel_mode: Literal["mixed", "separate_channels", "explicit_mapping"] = "mixed"
    channel_mapping: dict[int, ChannelIdentity] = Field(default_factory=dict)
    diarization: Literal["off", "channel_mapping", "pyannote_local"] = "off"
    rights_confirmed: bool
    provenance: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def check_mapping(self):
        if not self.rights_confirmed:
            raise ValueError("The owner must confirm rights to process this recording")
        if self.channel_mode == "explicit_mapping" and not self.channel_mapping:
            raise ValueError("explicit_mapping requires channel identities with provenance")
        if self.channel_mapping and self.channel_mode != "explicit_mapping":
            raise ValueError("channel_mapping requires explicit_mapping mode")
        if any(i < 0 or i >= 8 for i in self.channel_mapping):
            raise ValueError("Invalid channel index")
        return self


class VadConfig(StrictModel):
    enabled: bool = False
    threshold: float = Field(default=0.5, ge=0, le=1)
    min_speech_duration_ms: int = Field(default=100, ge=0)
    min_silence_duration_ms: int = Field(default=400, ge=0)
    speech_pad_ms: int = Field(default=200, ge=0)
    max_speech_duration_s: float = Field(default=30, gt=0, le=120)


class DenoiseConfig(StrictModel):
    enabled: bool = False
    strength: float = Field(default=0.5, ge=0, le=1)
    floor: float = Field(default=0.3, gt=0, le=1)
    noise_percentile: float = Field(default=10, gt=0, le=50)


class PipelineConfig(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    name: str = "baseline"
    model: str = "small"
    compute_type: str = "int8"
    device: str = "cpu"
    task: Literal["transcribe"] = "transcribe"
    beam_size: int = Field(default=5, ge=1)
    temperature: float = Field(default=0.0, ge=0)
    best_of: int = 5
    patience: float = 1.0
    length_penalty: float = 1.0
    repetition_penalty: float = 1.0
    no_repeat_ngram_size: int = 0
    condition_on_previous_text: bool = True
    compression_ratio_threshold: float = 2.4
    log_prob_threshold: float = -1.0
    no_speech_threshold: float = 0.6
    suppress_blank: bool = True
    suppress_tokens: list[int] = Field(default_factory=lambda: [-1])
    max_initial_timestamp: float = 1.0
    word_timestamps: bool = True
    language_detection_threshold: float = 0.5
    language_detection_segments: int = 1
    vad: VadConfig = Field(default_factory=VadConfig)
    denoise: DenoiseConfig = Field(default_factory=DenoiseConfig)
    hotwords: str | None = None
    glossary_version: str | None = None
    redecode: bool = False
    max_redecode_passes: Literal[0, 1] = 1
    redecode_logprob_threshold: float = -0.8
    episode_gap_sec: float = 2.0
    episode_max_sec: float = 30.0
    episode_max_tokens: int = 100
    classifier: str = "rules_v1"
    classifier_artifact: str | None = None

    @model_validator(mode="after")
    def validate_stages(self):
        if self.hotwords and not self.glossary_version:
            raise ValueError("hotwords require versioned provenance")
        if self.redecode and self.max_redecode_passes != 1:
            raise ValueError("redecode requires exactly one additional pass")
        if self.name == "baseline" and (
            self.vad.enabled or self.denoise.enabled or self.hotwords or self.redecode
        ):
            raise ValueError("baseline cannot contain domain improvements")
        return self

    @property
    def config_hash(self) -> str:
        return digest(self.model_dump())


class InferenceRequest(StrictModel):
    """Deliberately has no references, gold language, labels or arbitrary prompts."""

    sample_id: str
    audio_locator: str
    audio_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    language: Language = "auto"
    audio_channel: int | None = Field(default=None, ge=0, lt=8)
    channel_mode: Literal["mixed", "separate_channels", "explicit_mapping"] = "mixed"
    channel_mapping: dict[int, ChannelIdentity] = Field(default_factory=dict)
    diarization: Literal["off", "channel_mapping", "pyannote_local"] = "off"


class Word(StrictModel):
    word: str
    start_sec: float
    end_sec: float
    probability: float | None = None


class Segment(StrictModel):
    segment_id: str
    start_sec: float
    end_sec: float
    raw_asr_text: str
    display_text: str = ""
    reviewed_text: str | None = None
    channel: int | None = None
    speaker_id: str | None = None
    role: Role = "unknown"
    role_provenance: str | None = None
    language: str = "unknown"
    words: list[Word] = Field(default_factory=list)
    avg_logprob: float | None = None
    no_speech_prob: float | None = None
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
    normalization_changes: list[dict[str, Any]] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high", "unknown"] = "unknown"
    risk_reasons: list[str] = Field(default_factory=lambda: ["uncalibrated_asr_confidence"])


class Entity(StrictModel):
    type: str
    surface: str
    canonical_value: int | float | str | None
    unit: str | None = None
    polarity: Literal["affirmative", "negated", "uncertain"] = "affirmative"
    source_segment_id: str
    source_span: tuple[int, int]
    span_coordinates: Literal["raw_asr_text_unicode_codepoints"] = "raw_asr_text_unicode_codepoints"
    start_sec: float
    end_sec: float
    certainty_kind: str = "unverified_asr"
    evidence_kind: Literal["speech"] = "speech"
    alternatives: list[Any] = Field(default_factory=list)
    needs_review: bool = True


class Event(StrictModel):
    event_id: str
    start_sec: float
    end_sec: float
    speaker_id: str | None = None
    role: Role = "unknown"
    role_provenance: str | None = None
    classifier_version: str = "rules_v1"
    ontology_version: str = "1.0"
    labels: list[str]
    label_scores: dict[str, float] = Field(default_factory=dict)
    score_kind: str = "heuristic_uncalibrated"
    speech_act: str = "unknown"
    salient_for_review: bool | Literal["unknown"] = "unknown"
    evidence_segment_ids: list[str]
    evidence_quote: str
    reviewed_evidence_quote: str | None = None
    assertion_kind: Literal["spoken_mention"] = "spoken_mention"
    aircraft_state_verified: Literal[False] = False
    flight_phase: str = "unknown"
    phase_source: str = "unknown"
    entities: list[Entity] = Field(default_factory=list)
    needs_review: bool = True
    review_status: Literal["draft", "confirmed", "rejected"] = "draft"
    risk_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_labels(self):
        if not self.labels or any(x not in LABELS for x in self.labels):
            raise ValueError("Invalid event labels")
        if "OTHER" in self.labels and len(self.labels) != 1:
            raise ValueError("OTHER is exclusive")
        return self


class Review(StrictModel):
    expected_revision: int = Field(ge=0)
    author: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=2000)
    segment_id: str | None = None
    event_id: str | None = None
    reviewed_text: str | None = Field(default=None, max_length=10000)
    role: Role | None = None
    labels: list[str] | None = None
    salient_for_review: bool | None = None
    review_status: Literal["confirmed", "rejected", "draft"] | None = None

    @model_validator(mode="after")
    def check_target(self):
        if bool(self.segment_id) == bool(self.event_id):
            raise ValueError("Provide exactly one segment_id or event_id")
        if self.labels is not None and (
            not self.labels
            or any(x not in LABELS for x in self.labels)
            or ("OTHER" in self.labels and len(self.labels) > 1)
        ):
            raise ValueError("Invalid event labels")
        return self
