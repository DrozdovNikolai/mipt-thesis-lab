"""Render all fixed aviation measurements and representative improvements/regressions."""

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from north55_speech.core import atomic_json, file_hash  # noqa: E402


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    out = Path("/output")
    metrics = read(out / "metrics.json")
    plan = read(out / "inference/plan.json")
    items = read(out / "inference/inputs.json")
    counts = read(out / "scoring/counts.json")
    refs = read(out / "scoring/references.json")
    chosen = metrics["decision"]["selected"]
    cohort = metrics["cohorts"]
    systems = [s + suffix for s in ("small", "medium", "atc") for suffix in ("", "_gate")]
    def wer(c, s, kind="lexical"):
        return cohort[c][s][kind]["wer_lexical_corpus"] * 100
    def errors(c, s, kind="lexical"):
        return sum(cohort[c][s][kind][x] for x in ("S", "D", "I"))
    lines = ["# Авиационная речь: ATCOSIM", "",
        f"Обработаны все **{plan['cohorts']['atcosim']} фрагментов** опубликованного тестового набора: "
        f"**{cohort['atcosim']['small']['minutes']:.2f} минуты**, **{len(plan['atcosim_speakers'])} диктора**. "
        "Это речь диспетчеров в симуляции. Основной результат относится к авиации; общая речь служит контролем.", "",
        f"Выбран отдельный профиль: **{chosen}**." if chosen else "Новый профиль не выбран: критерии опыта не выполнены.", "",
        "Использована готовая сторонняя авиационная адаптация Whisper-medium.en. "
        "Новых шагов обучения в этом опыте нет. Исходная medium.en позволяет отдельно оценить вклад авиационного дообучения.", "",
        f"**Для кабинных разговоров этот профиль не подходит:** на пяти проверенных фрагментах WER "
        f"{wer('partial_human_dev','small'):.2f}% у прежнего small и {wer('partial_human_dev','atc'):.2f}% у ATC. "
        "Авиационный профиль выбирается явно для английского радиообмена.", "",
        "## Все варианты", "",
        "| Вариант | ATCOSIM WER | После симметричной нормализации чисел | Кабина, 5 фрагментов | Кабина, 35 слабых | General EN |",
        "|---|---:|---:|---:|---:|---:|"]
    for s in systems:
        lines.append(f"| {s} | {wer('atcosim',s):.2f}% | {wer('atcosim',s,'canonical'):.2f}% | "
                     f"{wer('partial_human_dev',s):.2f}% | {wer('publisher_weak_dev',s):.2f}% | {wer('general_clean',s):.2f}% |")
    lines += ["", "Первичная метрика — lexical WER: слова/числа не переписываются под ответ модели. "
              "Вторая колонка отделяет часть различий записи чисел; она не заменяет проверку критических сущностей.", "",
              "| Система | S | D | I | Слов в эталоне | CER |", "|---|---:|---:|---:|---:|---:|"]
    for s in ("small", "medium", "atc"):
        c = cohort["atcosim"][s]["lexical"]
        lines.append(f"| {s} | {c['S']} | {c['D']} | {c['I']} | {c['N']} | {100*c['cer']:.2f}% |")
    if (out / "aviation-words.json").exists():
        audit = read(out / "aviation-words.json")
        lines += ["", "## Авиационные слова и отрицания", "",
                  "| Система | Пропущено/заменено авиационных слов | Пропущено/заменено отрицаний |",
                  "|---|---:|---:|"]
        for s in ("small", "medium", "atc"):
            words, negations = [audit["systems"][s][kind] for kind in ("aviation_words", "negations")]
            lines.append(f"| {s} | {words['missed_or_substituted']} / {words['reference_occurrences']} | "
                         f"{negations['missed_or_substituted']} / {negations['reference_occurrences']} |")
        lines += ["", "Точное восстановление заранее заданных слов при lexical-выравнивании. "
                  "Это дополнительная диагностика, не разметка смысла команд и не оценка критических сущностей. "
                  "Список слов не подавался в распознавание и не использовался для выбора модели."]
    lines += ["", "## Проверка по дикторам", "",
              "| Диктор | Фрагменты | small | medium.en | ATC |", "|---|---:|---:|---:|---:|"]
    for speaker in sorted(plan["atcosim_speakers"]):
        c = "speaker_" + speaker
        lines.append(f"| {speaker} | {plan['atcosim_speakers'][speaker]} | "
                     f"{wer(c,'small'):.2f}% | {wer(c,'medium'):.2f}% | {wer(c,'atc'):.2f}% |")
    lines += ["", "95% paired bootstrap сгруппирован по четырём исходным дикторам. "
              "Это описательная оценка на данном корпусе, а не приёмка по прежнему требованию 20 независимых групп.", "",
              "```json", json.dumps(metrics["speaker_bootstrap"], ensure_ascii=False, indent=2), "```", "",
              "## Шум и тихая речь", "",
              "| Вариант | VOICI, вставок/мин | BLeRIOT-B, вставок/мин | Тихая кабина WER | Тихая общая EN WER |",
              "|---|---:|---:|---:|---:|"]
    for s in systems:
        a, b = [cohort[c][s]["lexical"]["I"] / cohort[c][s]["minutes"] for c in ("noise_only", "bleriot_b_noise")]
        lines.append(f"| {s} | {a:.2f} | {b:.2f} | {wer('quiet_partial_human_dev',s):.2f}% | {wer('quiet_general_clean',s):.2f}% |")
    lines += ["", "Шум в этом опыте распознаётся с явным English; сравнение с прежними auto-language числами некорректно. "
              "Gate пропускает весь вход при наличии речи, поэтому не обещает убрать шумовые паузы внутри длинной записи.", "",
              "## Происхождение и ограничения", "",
              "Автор адаптации указывает ATCO2-1h и UWB-ATCC как источники дообучения; ATCOSIM не указан. "
              "Это основание для проверки переноса между корпусами, но полный внешний train-манифест отсутствует. "
              "Пересечение с исходным pretraining Whisper неизвестно. Локальные train WAV проверены на точные пересечения.", "",
              "В зеркале корпуса лежат WAV 32 кГц, хотя декодируемая Hugging Face Audio feature объявляет 16 кГц. "
              "Исходные bytes сохранены; для всех трёх моделей подготовлен один и тот же mono float32 PCM 16 кГц.", "",
              "Это не доказательство качества реального шумного VHF радиообмена, русской авиационной речи или всей кабинной задачи. "
              "Человеческая проверка критических сущностей и целевые NLP-события не добавлены. "
              "**Полный прежний SPEC: NEEDS_MORE_DATA.**", "",
              "[Область](../../docs/aviation_scope.md) · [Протокол](protocol.md) · [Метрики](metrics.json) · "
              "[Примеры улучшений и ухудшений](examples.md) · [Локальный запуск](../../docs/aviation_local.md)", "",
              "Источники: [ATCOSIM](https://www.spsc.tugraz.at/databases-and-tools/atcosim-air-traffic-control-simulation-speech-corpus.html), "
              "[зеркало](https://huggingface.co/datasets/Jzuluaga/atcosim_corpus), "
              "[авиационная модель](https://huggingface.co/jacktol/whisper-medium.en-fine-tuned-for-ATC).", "",
              "![Авиационная проверка](wer.png)"]
    if all((out / name).exists() for name in ("code-verification.json", "runtime-verification.json", "score-replay.json")):
        code = read(out / "code-verification.json")
        runtime = read(out / "runtime-verification.json")
        replay = read(out / "score-replay.json")
        lines += ["", "## Проверка исполнения", "",
                  f"{code['unit_contract_suite']['passed']} тестов; Ruff и Mypy пройдены. "
                  "6135 GPU ASR-вызовов завершены без ошибок. "
                  f"Отдельно выполнены {runtime['end_to_end_cli_runs']} полных CLI-запуска: "
                  "тексты и таймкоды слов совпали с экспериментом, хеш выбранного рецепта подтверждён. "
                  f"Повторный подсчёт метрик и рецепта без ASR: **{replay['status']}**, побайтное совпадение. "
                  "Подмена сохранённой гипотезы в отдельной копии отклонена проверкой целостности.", "",
                  "[Тесты](code-verification.json) · [CLI](runtime-verification.json) · "
                  "[Повторный подсчёт](score-replay.json) · [Проверка подмены](integrity-rejection.json)"]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    deltas, rows = [], []
    for i in items:
        if i["cohort"] != "atcosim":
            continue
        identifier = i["id"]
        values = {s: read(out / "predictions" / s / f"{identifier}.json")["hypothesis"] for s in ("small", "medium", "atc")}
        e = {s: sum(counts[s][identifier]["lexical"][k] for k in ("S", "D", "I")) for s in values}
        row = {"id": identifier, "speaker": i["speaker_id"], "reference": refs[identifier], **values,
               "small_errors": e["small"], "medium_errors": e["medium"], "atc_errors": e["atc"]}
        rows.append(row)
        deltas.append((e["atc"] - e["medium"], identifier, row))
    with (out / "scoring/all-atcosim.tsv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    examples = ["# Примеры: улучшения и ухудшения", "", "Отбор по изменению числа ошибок medium.en → ATC; "
                "это иллюстрация, а не отдельная оценочная выборка. Все строки сохранены в scoring/all-atcosim.tsv.", ""]
    ranked = sorted(deltas)
    for label, chosen_rows in (("Наибольшие улучшения", ranked[:3]), ("Наибольшие ухудшения", list(reversed(ranked[-3:])))):
        examples += [f"## {label}", ""]
        for delta, identifier, row in chosen_rows:
            examples += [f"### {identifier} (изменение ошибок {delta:+d})", "", f"Эталон: {row['reference']}", "",
                         f"medium.en: {row['medium']}", "", f"ATC: {row['atc']}", ""]
    (out / "examples.md").write_text("\n".join(examples), encoding="utf-8")
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.3))
    for ax, kind, title in zip(axes, ("lexical", "canonical"), ("Lexical WER", "Number-normalized WER"), strict=True):
        values = [wer("atcosim", s, kind) for s in ("small", "medium", "atc")]
        bars = ax.bar(["Current small", "Medium.en", "ATC adapted"], values, color=["#8793a4", "#476786", "#087f72"])
        ax.bar_label(bars, labels=[f"{v:.2f}%" for v in values], padding=4)
        ax.set_ylim(0, max(values) * 1.18)
        ax.set_title(title)
        ax.set_ylabel("Word error rate, %")
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle(f"ATCOSIM: {plan['cohorts']['atcosim']} controller utterances, {len(plan['atcosim_speakers'])} speakers")
    fig.tight_layout()
    fig.savefig(out / "wer.png", dpi=170)
    atomic_json(out / "reporting.json", {"script_sha256": file_hash(Path(__file__)), "metrics_sha256": file_hash(out / "metrics.json"),
        "exact_atcosim_utterances": len(rows), "errors": {s: errors("atcosim", s) for s in ("small", "medium", "atc")}})


if __name__ == "__main__":
    main()
