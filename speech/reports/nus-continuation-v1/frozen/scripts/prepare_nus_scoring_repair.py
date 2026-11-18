"""Record a narrow legacy-field compatibility repair; preserve frozen experiments."""


from scripts.run_nus_failure_diagnosis import REPO, save, sha


def replace_once(source, before, after):
    if source.count(before) != 1:
        raise ValueError('Repair target is ambiguous or changed: ' + before)
    return source.replace(before, after, 1)


def main():
    for directory, filename in (('nus-diagnosis-v1', 'score_nus_failure_diagnosis.py'),
                                ('nus-lora-ablation-v1', 'nus_lora_ablation.py')):
        root = REPO / 'reports' / directory
        destination = root / 'scoring-repair'
        if destination.exists() or (root/'comparison.json').exists():
            raise ValueError('Preserve the existing repair/result')
        original = root / 'frozen/scripts' / filename
        source = original.read_text(encoding='utf-8')
        source = replace_once(source, 'import json\n', 'import json\n\nfrom research_audio_evidence import same_waveform, write_legacy_evidence\n')
        if directory == 'nus-diagnosis-v1':
            source = replace_once(source,
                "traces[base + '_on'][i['id']]['effective_waveform_sha256'] == historical[base][i['id']]['effective_waveform_sha256']",
                "same_waveform(i, historical[base][i['id']], traces[base + '_on'][i['id']]['effective_waveform_sha256'])")
            source = replace_once(source, "'quality_evidence': False, 'release': 'FAIL'", 
                "'scoring_amendment_sha256': file_hash(ROOT / 'scoring-amendment.json'), 'quality_evidence': False, 'release': 'FAIL'")
        else:
            source = replace_once(source,
                "records[i['id']]['effective_waveform_sha256'] == historical['parent_on'][i['id']]['effective_waveform_sha256']",
                "same_waveform(i, records[i['id']], new['encoder_on'][i['id']]['effective_waveform_sha256'])")
            source = replace_once(source, "'new_CPU_predictions': 2, 'plan_sha256':",
                "'scoring_amendment_sha256': file_hash(ROOT / 'scoring-amendment.json'), 'new_CPU_predictions': 2, 'plan_sha256':")
        source = replace_once(source, "atomic_json(ROOT / 'comparison.json', result)",
                "write_legacy_evidence(ROOT / 'legacy-waveform-evidence.json')\n    atomic_json(ROOT / 'comparison.json', result)")
        destination.mkdir()
        (destination / filename).write_text(source, encoding='utf-8', newline='\n')
        helper = REPO / 'scripts/research_audio_evidence.py'
        (destination / helper.name).write_bytes(helper.read_bytes())
        save(root / 'scoring-amendment.json', {
            'kind': 'legacy_source_audio_identity_compatibility',
            'reason': 'Legacy parent records lack effective_waveform_sha256; they preserve source file hashes and declared zero-gain preprocessing.',
            'original_scorer_sha256': sha(original), 'frozen_sources_modified': False,
            'files': {p.name: sha(p) for p in destination.iterdir() if p.is_file()},
            'entrypoint': filename, 'audio_volume_mounted_readonly_for_scoring': True,
            'metrics_normalizer_thresholds_changed': False, 'predictions_modified': False,
            'new_ASR_calls': 0, 'test_accessed': False})
        print('Prepared ' + directory + ' scoring compatibility repair')


if __name__ == '__main__':
    main()
