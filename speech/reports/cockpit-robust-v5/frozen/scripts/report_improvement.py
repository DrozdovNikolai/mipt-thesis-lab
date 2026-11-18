"""Make the measured recipe and readable report from a completed frozen comparison."""

import json
from pathlib import Path

from north55_speech.core import atomic_json, digest, file_hash


def main():
    out = Path("/output")
    metrics = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    plan = json.loads((out / "inference/plan.json").read_text(encoding="utf-8"))
    cohorts = metrics["cohorts"]
    primary = cohorts["new_ru_primary"]
    before, after = (primary[s]["wer_lexical_corpus"] for s in ("small", "large"))
    ru_improved = after < before and not primary["large"]["failures"]
    english = metrics["selected_english_exploratory"]

    def config(system):
        result = plan["baseline"] | {"name": "measured_preview_v1",
                                    "model": plan["model_names"][system.split("_")[0]]}
        if "glossary" in system:
            result |= {"hotwords": plan["glossary"], "glossary_version": "train_glossary_v1"}
        if system.endswith("_gate"):
            result["vad"] = result["vad"] | {"enabled": True, "mode": "gate"} | plan["gate"]
        return result

    recipe = {"schema_version": "1.0", "source_plan_sha256": metrics["plan_sha256"],
              "metrics_sha256": file_hash(out / "metrics.json"), "default": config("small"),
              "by_language": {"en": config(english), "ru": config("large" if ru_improved else "small")},
              "model_manifest_digests": {plan["model_names"][name]: digest(value)
                                         for name, value in plan["models"].items()},
              "evaluation_scope": {"ru": "new general read-speech dev; unknown speaker identities",
                  "en": "previous exploratory cockpit dev and regression controls",
                  "auto_and_mixed": "unchanged small; no new quality validation",
                  "full_spec_gate": "NEEDS_MORE_DATA"}}
    atomic_json(out / "recipe/selected.json", recipe)

    def pct(value):
        return f"{value * 100:.2f}%" if value is not None else "—"

    rows = []
    for label, cohort in [("Новый RU: одно чтение каждого нового предложения", "new_ru_primary"),
                          ("Новый RU: дополнительные чтения", "new_ru_repeat_readings"),
                          ("Прежний RU-контроль", "general_ru"),
                          ("Человеческий кабинный dev", "partial_human_dev"),
                          ("Общий EN-контроль", "general_clean"),
                          ("Слабые кабинные эталоны", "publisher_weak_dev")]:
        systems = ("small", "large") if "ru" in cohort else ("small", english)
        a, b = (cohorts[cohort][s] for s in systems)
        rows.append(f"| {label} | {a['clips']} | {pct(a['wer_lexical_corpus'])} | {pct(b['wer_lexical_corpus'])} |")
    noise_rows = []
    for cohort in ("noise_only", "bleriot_b_noise"):
        a, b = (cohorts[cohort][s]["inserted_words_per_minute"] for s in ("small", "small"))
        noise_rows.append(f"| {cohort} | {a:.3f} | {b:.3f} |")
    all_rows = []
    for system in metrics["checks"]:
        all_rows.append(f"| {system} | {pct(cohorts['partial_human_dev'][system]['wer_lexical_corpus'])} | "
                        f"{pct(cohorts['general_clean'][system]['wer_lexical_corpus'])} | "
                        f"{metrics['checks'][system]['noise']} | {all(metrics['checks'][system].values())} |")
    executions = {s: json.loads((out / "predictions" / s / "execution.json").read_text())
                  for s in plan["systems"]}
    calls = sum(e["new_calls"] for e in executions.values())
    report = f"""# Практическое улучшение распознавания: результат

Исследование выполнено локально через Docker Compose без сети и нового обучения.
Новая RU-проверка: **{pct(before)} → {pct(after)} lexical WER**,
относительное снижение **{(before - after) / before * 100:.2f}%**.
Это эффект выбора **Whisper large-v3 вместо small**, не эффект LoRA или предобработки.
Выбранный английский вариант: **{english}**.

![WER на новых русских предложениях](wer.png)

## Новые данные и независимость

Из 356 локальных FLEURS dev-записей исключены все предложения прежних 50 controls
и sentence IDs полного локального train. Осталось 237 записей со 100 новыми
предложениями: заранее по hash имени выбрано одно чтение каждого предложения;
137 остальных чтений показаны отдельно. Новая основная выборка — 19.56 минуты,
**{primary['small']['N']} слов**, готовые человеческие тексты издателя.
Новой местной ручной разметки не было. Аудио сверено с TSV и checksums; известных
пересечений waveform с train не обнаружено. Пересечение с pretraining Whisper
неизвестно. Отдельный новый закрытый final test не создавался и старый не открывался.

Выбор large-v3 для RU сделан до просмотра новых ответов, по старой диагностике.
Это новая проверка на ранее не оценивавшихся предложениях, но дикторы неизвестны:
нельзя утверждать независимость от дикторов старого dev или строить надёжный
speaker/session CI. Условный bootstrap по предложениям сохранён в metrics.json
и не заменяет требуемую SPEC оценку по независимым группам.

## Измерения выбранного рецепта

| Набор | Записей | Исходный small | Выбранный вариант |
|---|---:|---:|---:|
{chr(10).join(rows)}

Корпусный WER = сумма S+D+I / сумма N. В новой основной RU-выборке:
small S/D/I = **{primary['small']['S']}/{primary['small']['D']}/{primary['small']['I']}**;
large S/D/I = **{primary['large']['S']}/{primary['large']['D']}/{primary['large']['I']}**.
Ошибок исполнения на ней: small {primary['small']['failures']}, large {primary['large']['failures']}.
Общие EN/RU controls не доказывают качество разговоров экипажа. Кабинный human dev
по-прежнему содержит только пять фрагментов/115 слов/три ранее просмотренные группы.
Сценарные тексты остаются слабыми эталонами. Сравнивать их WER с человеческим gold
как равнозначные показатели нельзя.

| Шум с языком auto, вставок/мин | Исходный small | Готовый рецепт |
|---|---:|---:|
{chr(10).join(noise_rows)}

Шумовые запросы имеют язык auto и в готовом рецепте проходят через исходный small.
Они не подтверждают поведение large при принудительно заданном RU на чистом шуме.

## Все восемь заранее объявленных вариантов

| Вариант | Human cockpit WER | Общий EN WER | Оба noise guards | Все условия EN-выбора |
|---|---:|---:|---|---|
{chr(10).join(all_rows)}

Словарь содержит до 48 слов из train, без test/dev текстов и числовых ответов.
Фильтр gate при наличии речи сохраняет исходное окно целиком; при отсутствии
обнуляет текст. Результат фильтра вычислен из сохранённых VAD-интервалов: он не
выдаётся за новый независимый ASR-вызов. Выполнено **{calls} новых GPU ASR-вызовов**;
идентичные запросы без EN-словаря переиспользованы по hashes. Точность CUDA float16,
beam 5, temperature 0. Начальные задержки проверки/загрузки моделей сохранены в
execution.json и не являются временем распознавания одного фрагмента.

## Использование и статус

Подготовлен [готовый рецепт](recipe/selected.json) и отдельная команда обработки
локальных файлов: [инструкция](../../docs/improved_local.md).
RU маршрутизируется в large только при явном --language ru. Auto/mixed сохраняют
small. Результат содержит исходный ASR-текст, таймкоды и черновые события; это не
подтверждённые действия экипажа. Существующий API/worker не переключались.

Проверки кода: 443 теста прошли, 9 integration/real-ASR тестов не запускались
в этом наборе. Mypy и Ruff прошли. Отдельно реально выполнены два сквозных
GPU-запуска нового CLI: RU и EN; тексты совпали с сохранёнными ASR-ответами
после нормализации пробелов. [Проверки runtime](runtime-verification.json),
[проверки кода](code-verification.json).

**Полный SPEC: NEEDS_MORE_DATA.** Нет достаточного независимого cockpit-test,
проверенных critical entities, новых event/salience/temporal меток. Новый измеренный
результат относится к общей русской читаемой речи. Дополнительного обучения — 0 шагов.

[Протокол](protocol.md) · [Метрики](metrics.json) · [Зафиксированный план](inference/plan.json)

Готовые тексты FLEURS описаны в [карточке авторов](https://huggingface.co/datasets/google/fleurs).
Исполнение использует локальные закреплённые веса и
[faster-whisper](https://github.com/SYSTRAN/faster-whisper); сетевой доступ при обработке выключен.
"""
    (out / "report.md").write_text(report, encoding="utf-8")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7.2, 4.3), constrained_layout=True)
    bars = ax.bar(["Whisper small", "Whisper large-v3"], [before * 100, after * 100],
                  color=["#718096", "#168a68"], width=.55)
    ax.bar_label(bars, labels=[pct(before), pct(after)], padding=7, fontsize=15, weight="bold")
    ax.set_ylim(0, max(before, after) * 125)
    ax.set_ylabel("Word error rate (%) — lower is better")
    ax.set_title("New Russian evaluation: 100 sentences / 1,894 words", pad=15)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=.2)
    ax.set_axisbelow(True)
    fig.text(.5, -.08, "FLEURS read speech; not a cockpit benchmark. No speaker-level confidence interval.",
             ha="center", fontsize=9)
    fig.savefig(out / "wer.png", dpi=170, bbox_inches="tight")
    plt.close(fig)
    print(json.dumps({"ru_relative_gain": (before - after) / before, "selected_en": english,
                      "recipe_written": True, "calls": calls}))


if __name__ == "__main__":
    main()
