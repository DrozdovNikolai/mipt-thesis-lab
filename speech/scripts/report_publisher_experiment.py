"""Render actual adaptation measurements and clearly separate weak-reference agreement."""

import html
import json
from pathlib import Path

from north55_speech.core import atomic_json, file_hash
from north55_speech.metrics import corpus_counts, edit_counts
from north55_speech.reporting import write_csv


def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    root = Path("/reports")
    output = root / "publisher-weak-v1"
    comparison = json.loads((output / "comparison.json").read_text())
    preparation = json.loads(Path("/publisher/preparation-report.json").read_text())
    history = json.loads((output / "training-history.json").read_text())
    # Reuse all eight previously declared trials, never choose a new winner from proxy labels.
    prior = json.loads((root / "pending-dev-ablation.json").read_text())
    from north55_speech.datasets import load_manifest
    dev = {s.sample_id: s for s in load_manifest(Path("/publisher/all/dev.jsonl"))}
    matched_ids = {r["sample_id"] for r in prior["runs"] if r["sample_id"] in dev
                   and dev[r["sample_id"]].annotation_provenance["automatic_training_eligible"]}
    ablation = []
    for name in dict.fromkeys(r["trial"] for r in prior["runs"]):
        rows = [r for r in prior["runs"] if r["trial"] == name and r["sample_id"] in matched_ids]
        counts = corpus_counts([edit_counts(dev[r["sample_id"]].reference_text, r["hypothesis"]) for r in rows])
        ablation.append({"trial": name, "proxy_scored_samples": len(rows), **counts,
                         "source_plan_sha256": prior["plan_sha256"], "quality_evidence": False})
    atomic_json(output / "ablation-proxy.json", {"status": "EXPLORATORY_NOT_SELECTION", "rows": ablation,
        "source_sha256": file_hash(root / "pending-dev-ablation.json"), "sample_ids": sorted(matched_ids),
        "warning": "Alignment uses the parent Whisper family. These scores are not independent WER evidence. No pipeline stage is activated.",
        "candidate_selected": False, "test_accessed": False})
    write_csv(output / "ablation-proxy.csv", ["trial", "proxy_scored_samples", "S", "D", "I", "N", "wer_lexical_corpus", "quality_evidence"], ablation)
    conditions = []
    for condition in sorted({r["condition"] for r in comparison["rows"] if r["cohort"] == "dev"}):
        for system in ("parent", "adapted"):
            rows = [r for r in comparison["rows"] if r["condition"] == condition and r["system"] == system and r["score"] is not None]
            conditions.append({"condition": condition, "system": system, "samples": len(rows), **corpus_counts([r["score"] for r in rows])})
    write_csv(output / "dev-condition-proxy.csv", ["condition", "system", "samples", "S", "D", "I", "N", "wer_lexical_corpus"], conditions)
    losses = {r["step"]: r["eval_loss"] for r in history if "eval_loss" in r}
    fig, ax = plt.subplots(figsize=(7, 3.5), layout="constrained")
    ax.plot(list(losses), list(losses.values()), "o-", color="#17627d")
    ax.set(xlabel="Optimizer step", ylabel="Dev cross-entropy (weak publisher targets)", title="Actual LoRA training; this is not WER")
    for ext in ("png", "svg"):
        fig.savefig(output / f"training-loss.{ext}", dpi=150, bbox_inches="tight")
    plt.close(fig)
    dev_scores = comparison["comparison"]["dev"]
    parent = sum(dev_scores["parent"][k] for k in ("S", "D", "I"))
    adapted = sum(dev_scores["adapted"][k] for k in ("S", "D", "I"))
    reduction = 1-adapted/parent if parent else None
    training = comparison["training"]
    control = comparison["comparison"]["general_control"]
    control_errors = {name: sum(values[k] for k in ("S", "D", "I")) for name, values in control.items()}
    steps = max(row["step"] for row in history)
    lines = ["# Эксперимент на готовых текстах BLeRIOT", "",
        "**Статус научной приёмки: NEEDS_MORE_DATA. Candidate не выбран, release не изменён.**", "",
        f"Подготовлены {preparation['total_rows']} фрагментов: 8 train и 3 dev speaker-группы. "
        f"Автоматические проверки допустили {preparation['eligible_train']} train и {preparation['eligible_dev']} dev пар. "
        "Тексты взяты из документов издателя; колонки PDF восстановлены по координатам. "
        "Сопоставление и таймкоды получены автоматически. Человеческие метки не создавались.", "",
        f"LoRA: small, rank 8, {steps} optimizer steps, {training['train_metrics']['epoch']:g} epochs, {training['gpu']}; "
        f"обучение {training['train_metrics']['train_runtime']} с. "
        "Первый запуск остановился на 0 шагах из-за второй несовместимой GPU; успешная попытка использует только GPU 0. "
        "Сохранены adapter, merged Transformers checkpoint, CT2 float16 и настоящие предсказания. "
        "Сравнение использует исходную и адаптированную модель из одного Transformers checkpoint, одинаковую CT2 conversion и float16 decoding.", "",
        "| Измерение | Исходная | После LoRA | Ограничение |", "|---|---:|---:|---|",
        f"| Расхождения с автоматически привязанным текстом | {parent}/{dev_scores['parent']['N']} ({100*dev_scores['parent']['wer_lexical_corpus']:.2f}%) | {adapted}/{dev_scores['adapted']['N']} ({100*dev_scores['adapted']['wer_lexical_corpus']:.2f}%) | 7 из 24 dev-фрагментов; 3 группы; это не независимый gold |",
        f"| WER общеречевых контролей | {control_errors['parent']}/{control['parent']['N']} ({100*control['parent']['wer_lexical_corpus']:.2f}%) | "
        f"{control_errors['adapted']}/{control['adapted']['N']} ({100*control['adapted']['wer_lexical_corpus']:.2f}%) | "
        f"{comparison['general_controls']} записи; {comparison['general_control_independent_groups']} группа; недостаточно для acceptance |", "",
        f"Снижение расхождений с издательским текстом: **{100*reduction:.2f}%**. "
        "Оно не доказывает требуемое снижение истинного lexical WER: выбор и привязка этих текстов используют родственное ASR. "
        "Есть повторяющиеся сценарии и парные clean/noisy варианты. Разбивка по условиям сохранена отдельно; "
        "число файлов не выдаётся за число независимых групп.", "",
        f"Все {len(comparison['rows'])} распознавания (24 dev + 2 контроля для каждой модели) сохранены, ошибок исполнения: {comparison['runtime_failures']}. "
        "Отсутствующие эталоны 17 dev-фрагментов не заменены машинными гипотезами и не засчитаны как успешные ответы.", "",
        "![Настоящие значения dev loss](training-loss.png)", "",
        "Аналогично рассчитана диагностическая таблица для восьми прежних ablation-вариантов на общей доступной подвыборке. "
        "Это вторичный proxy-анализ старых прогонов, не новый scored dev-search. Ни один дополнительный этап не активирован.", "",
        "Критические сущности и NLP/temporal event precision/recall/F1 не измерены: независимых соответствующих меток нет. "
        "Final test не открывался. EN/RU/mixed остаются техническими режимами, подтверждённого языкового качества нет.", "",
        "Артефакты: comparison.json / comparison.csv; dev-condition-proxy.csv; ablation-proxy.csv; "
        "training-history.json; training-manifest.json; adapted-cpu-smoke.json; verification.json."]
    text = "\n".join(lines) + "\n"
    (output / "report.md").write_text(text, encoding="utf-8")
    page = '<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>BLeRIOT — результат эксперимента</title><style>body{font:16px system-ui;background:#edf2f4;color:#152d3d}main{max-width:1050px;margin:32px auto;background:white;padding:28px}pre{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.6}img{max-width:100%}a{color:#175b83}</style><main>'
    page += '<h1>Эксперимент на готовых текстах BLeRIOT</h1><p><strong>NEEDS_MORE_DATA · release не изменён</strong></p>'
    page += '<p>' + ' · '.join(f'<a href="{name}">{name}</a>' for name in ("comparison.csv", "ablation-proxy.csv", "dev-condition-proxy.csv", "training-manifest.json")) + '</p>'
    page += '<img src="training-loss.png" alt="Измеренный dev loss по шагам обучения"><pre>' + html.escape(text) + '</pre></main></html>'
    (output / "report.html").write_text(page, encoding="utf-8")
    print(json.dumps({"status": "RENDERED", "proxy_relative_reduction": reduction, "research_quality_gate": "NEEDS_MORE_DATA", "ablation_cohort": len(matched_ids)}))


if __name__ == "__main__":
    main()
