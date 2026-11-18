# ruff: noqa
# Preserve the audited upstream loop syntax; local changes are documented below.
"""Vendored faster-whisper 1.2.1 loop, MIT (see faster_whisper_LICENSE.txt).

Only the seek-after-alignment block differs: re-entry targets a new uncovered
speech onset with context. Kept as readable source, with no runtime code patch.
"""
import logging
from typing import Iterable, List, Optional, Tuple

import ctranslate2
import numpy as np
from faster_whisper.audio import pad_or_trim
from faster_whisper.tokenizer import Tokenizer
from faster_whisper.transcribe import Segment, TranscriptionOptions, Word
from faster_whisper.utils import format_timestamp, get_end
from tqdm import tqdm

def generate_segments(
    self,
    features: np.ndarray,
    tokenizer: Tokenizer,
    options: TranscriptionOptions,
    log_progress,
    encoder_output: Optional[ctranslate2.StorageView] = None,
) -> Iterable[Segment]:
    content_frames = features.shape[-1] - 1
    content_duration = float(content_frames * self.feature_extractor.time_per_frame)

    if isinstance(options.clip_timestamps, str):
        options.clip_timestamps = [
            float(ts)
            for ts in (
                options.clip_timestamps.split(",")
                if options.clip_timestamps
                else []
            )
        ]

    seek_points: List[int] = [
        round(ts * self.frames_per_second) for ts in options.clip_timestamps
    ]
    if len(seek_points) == 0:
        seek_points.append(0)
    if len(seek_points) % 2 == 1:
        seek_points.append(content_frames)
    seek_clips: List[Tuple[int, int]] = list(
        zip(seek_points[::2], seek_points[1::2])
    )

    punctuation = "\"'“¿([{-\"'.。,，!！?？:：”)]}、"

    idx = 0
    clip_idx = 0
    seek = seek_clips[clip_idx][0]
    all_tokens = []
    prompt_reset_since = 0

    if options.initial_prompt is not None:
        if isinstance(options.initial_prompt, str):
            initial_prompt = " " + options.initial_prompt.strip()
            initial_prompt_tokens = tokenizer.encode(initial_prompt)
            all_tokens.extend(initial_prompt_tokens)
        else:
            all_tokens.extend(options.initial_prompt)

    pbar = tqdm(total=content_duration, unit="seconds", disable=not log_progress)
    last_speech_timestamp = 0.0
    # NOTE: This loop is obscurely flattened to make the diff readable.
    # A later commit should turn this into a simpler nested loop.
    # for seek_clip_start, seek_clip_end in seek_clips:
    #     while seek < seek_clip_end
    while clip_idx < len(seek_clips):
        seek_clip_start, seek_clip_end = seek_clips[clip_idx]
        if seek_clip_end > content_frames:
            seek_clip_end = content_frames
        if seek < seek_clip_start:
            seek = seek_clip_start
        if seek >= seek_clip_end:
            clip_idx += 1
            if clip_idx < len(seek_clips):
                seek = seek_clips[clip_idx][0]
            continue
        time_offset = seek * self.feature_extractor.time_per_frame
        window_end_time = float(
            (seek + self.feature_extractor.nb_max_frames)
            * self.feature_extractor.time_per_frame
        )
        segment_size = min(
            self.feature_extractor.nb_max_frames,
            content_frames - seek,
            seek_clip_end - seek,
        )
        segment = features[:, seek : seek + segment_size]
        segment_duration = segment_size * self.feature_extractor.time_per_frame
        segment = pad_or_trim(segment)

        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(
                "Processing segment at %s", format_timestamp(time_offset)
            )

        previous_tokens = all_tokens[prompt_reset_since:]

        if seek > 0 or encoder_output is None:
            encoder_output = self.encode(segment)

        if options.multilingual:
            results = self.model.detect_language(encoder_output)
            language_token, language_probability = results[0][0]
            language = language_token[2:-2]

            tokenizer.language = tokenizer.tokenizer.token_to_id(language_token)
            tokenizer.language_code = language

        prompt = self.get_prompt(
            tokenizer,
            previous_tokens,
            without_timestamps=options.without_timestamps,
            prefix=options.prefix if seek == 0 else None,
            hotwords=options.hotwords,
        )

        (
            result,
            avg_logprob,
            temperature,
            compression_ratio,
        ) = self.generate_with_fallback(encoder_output, prompt, tokenizer, options)

        if options.no_speech_threshold is not None:
            # no voice activity check
            should_skip = result.no_speech_prob > options.no_speech_threshold

            if (
                options.log_prob_threshold is not None
                and avg_logprob > options.log_prob_threshold
            ):
                # don't skip if the logprob is high enough, despite the no_speech_prob
                should_skip = False

            if should_skip:
                self.logger.debug(
                    "No speech threshold is met (%f > %f)",
                    result.no_speech_prob,
                    options.no_speech_threshold,
                )

                # fast-forward to the next segment boundary
                seek += segment_size
                continue

        tokens = result.sequences_ids[0]

        previous_seek = seek

        # anomalous words are very long/short/improbable
        def word_anomaly_score(word: dict) -> float:
            probability = word.get("probability", 0.0)
            duration = word["end"] - word["start"]
            score = 0.0
            if probability < 0.15:
                score += 1.0
            if duration < 0.133:
                score += (0.133 - duration) * 15
            if duration > 2.0:
                score += duration - 2.0
            return score

        def is_segment_anomaly(segment: Optional[dict]) -> bool:
            if segment is None or not segment["words"]:
                return False
            words = [w for w in segment["words"] if w["word"] not in punctuation]
            words = words[:8]
            score = sum(word_anomaly_score(w) for w in words)
            return score >= 3 or score + 0.01 >= len(words)

        def next_words_segment(segments: List[dict]) -> Optional[dict]:
            return next((s for s in segments if s["words"]), None)

        (
            current_segments,
            seek,
            single_timestamp_ending,
        ) = self._split_segments_by_timestamps(
            tokenizer=tokenizer,
            tokens=tokens,
            time_offset=time_offset,
            segment_size=segment_size,
            segment_duration=segment_duration,
            seek=seek,
        )

        if options.word_timestamps:
            self.add_word_timestamps(
                [current_segments],
                tokenizer,
                encoder_output,
                segment_size,
                options.prepend_punctuations,
                options.append_punctuations,
                last_speech_timestamp=last_speech_timestamp,
            )
            if not single_timestamp_ending:
                next_speech_seek = self.remaining_speech_seek(current_segments, previous_seek, previous_seek + segment_size)
                if next_speech_seek is not None:
                    seek = next_speech_seek

            # skip silence before possible hallucinations
            if options.hallucination_silence_threshold is not None:
                threshold = options.hallucination_silence_threshold

                # if first segment might be a hallucination, skip leading silence
                first_segment = next_words_segment(current_segments)
                if first_segment is not None and is_segment_anomaly(first_segment):
                    gap = first_segment["start"] - time_offset
                    if gap > threshold:
                        seek = previous_seek + round(gap * self.frames_per_second)
                        continue

                # skip silence before any possible hallucination that is surrounded
                # by silence or more hallucinations
                hal_last_end = last_speech_timestamp
                for si in range(len(current_segments)):
                    segment = current_segments[si]
                    if not segment["words"]:
                        continue
                    if is_segment_anomaly(segment):
                        next_segment = next_words_segment(
                            current_segments[si + 1 :]
                        )
                        if next_segment is not None:
                            hal_next_start = next_segment["words"][0]["start"]
                        else:
                            hal_next_start = time_offset + segment_duration
                        silence_before = (
                            segment["start"] - hal_last_end > threshold
                            or segment["start"] < threshold
                            or segment["start"] - time_offset < 2.0
                        )
                        silence_after = (
                            hal_next_start - segment["end"] > threshold
                            or is_segment_anomaly(next_segment)
                            or window_end_time - segment["end"] < 2.0
                        )
                        if silence_before and silence_after:
                            seek = round(
                                max(time_offset + 1, segment["start"])
                                * self.frames_per_second
                            )
                            if content_duration - segment["end"] < threshold:
                                seek = content_frames
                            current_segments[si:] = []
                            break
                    hal_last_end = segment["end"]

            last_word_end = get_end(current_segments)
            if last_word_end is not None:
                last_speech_timestamp = last_word_end
        for segment in current_segments:
            tokens = segment["tokens"]
            text = tokenizer.decode(tokens)

            if segment["start"] == segment["end"] or not text.strip():
                continue

            all_tokens.extend(tokens)
            idx += 1

            yield Segment(
                id=idx,
                seek=previous_seek,
                start=segment["start"],
                end=segment["end"],
                text=text,
                tokens=tokens,
                temperature=temperature,
                avg_logprob=avg_logprob,
                compression_ratio=compression_ratio,
                no_speech_prob=result.no_speech_prob,
                words=(
                    [Word(**word) for word in segment["words"]]
                    if options.word_timestamps
                    else None
                ),
            )

        if (
            not options.condition_on_previous_text
            or temperature > options.prompt_reset_on_temperature
        ):
            if options.condition_on_previous_text:
                self.logger.debug(
                    "Reset prompt. prompt_reset_on_temperature threshold is met %f > %f",
                    temperature,
                    options.prompt_reset_on_temperature,
                )

            prompt_reset_since = len(all_tokens)

        pbar.update(
            (min(content_frames, seek) - previous_seek)
            * self.feature_extractor.time_per_frame,
        )
    pbar.close()
