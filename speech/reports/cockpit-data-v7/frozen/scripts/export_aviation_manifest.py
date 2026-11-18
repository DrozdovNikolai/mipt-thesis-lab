"""Export measured aviation audio into the project's existing dataset schema."""

from pathlib import Path

from north55_speech.core import atomic_json, file_hash
from north55_speech.datasets import Sample, decoded_audio_hash, validate_groups, write_manifest
from scripts.improvement_experiment import read


def main():
    study, dataset = Path("/study"), Path("/dataset")
    plan = read(study / "inference/plan.json")
    references = read(study / "scoring/references.json")
    if (file_hash(study / "inference/inputs.json") != plan["inputs_sha256"]
            or file_hash(study / "scoring/references.json") != plan["references_sha256"]):
        raise ValueError("Frozen dataset evidence changed")
    samples = []
    for item in read(study / "inference/inputs.json"):
        if item["cohort"] != "atcosim":
            continue
        relative = f"audio/{item['id']}.wav"
        audio = dataset / relative
        if file_hash(audio) != item["audio_sha256"]:
            raise ValueError("Exported audio differs from evaluated audio")
        samples.append(Sample(
            sample_id=item["id"], audio_path=relative, audio_sha256=item["audio_sha256"],
            decoded_audio_sha256=decoded_audio_hash([audio]),
            source_dataset="ATCOSIM", source_version=plan["acquisition"]["revision"],
            recording_id="atcosim:" + item["recording_id"],
            session_id="atcosim:" + item["original_id"].rsplit("_", 1)[0],
            original_utterance_id="atcosim:" + item["original_id"],
            speaker_ids=["atcosim:" + item["speaker_id"]], language="en", input_language="en",
            scope="atc", scope_verified=True, speech_origin="recorded_human", acoustic_condition="simulated_close_talk",
            duration_sec=item["duration_sec"], license_id="ATCOSIM-research-and-development",
            provenance="ATCOSIM authors / Jzuluaga mirror; local ASR research; license.txt retained in source directory",
            rights_confirmed=True, transcript_status="human_verified", reference_text=references[item["id"]],
            primary=False, split="dev", annotation_provenance={
                "source_split": "test", "local_partition": "dev_after_exploratory_comparison",
                "method": "publisher_transcript_with_mirror_normalization", "reviewed_audio": False,
                "local_manual_verification": False,
                "human_verified_scope": "publisher_provided_transcription_not_local_review",
                "scope_basis": "original corpus documentation and verified speaker/utterance metadata",
                "primary_false_reason": "separate_aviation_protocol_not_legacy_cockpit_acceptance",
                "source_sample_rate": item["source_sample_rate"], "source_pcm_sha256": item["source_pcm_sha256"],
                "experiment_plan_sha256": file_hash(study / "inference/plan.json"),
            },
        ))
    groups = validate_groups(samples)
    path = dataset / "atcosim-dev.jsonl"
    write_manifest(path, samples)
    result = {"manifest_sha256": file_hash(path), "samples": len(samples), "groups": groups,
              "scope": "atc", "local_split": "dev", "source_split": "test",
              "human_reference_scope": "publisher", "local_audio_review": False}
    atomic_json(study / "dataset-export.json", result)
    print(result)


if __name__ == "__main__":
    main()
