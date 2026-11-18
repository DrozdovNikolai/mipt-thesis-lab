# Повторение расширенной серии

Команды ниже предназначены для этого стенда с сохранёнными worktree и зависимостями.
План измерений — [EXPANDED_PLAN.md](EXPANDED_PLAN.md). Запускать одну серию за раз:
подготовка профиля пересоздаёт только экспериментальные БД `thesis_exp_*` внутри
проекта `firefly-thesis-expanded-20260916`.

Использованные версии: Flutter 3.38.9, Dart 3.10.8, Chromium 148.0.7778.96,
Playwright 1.58.2, Node 22.20.0, Python драйвера 3.12.3, matplotlib 3.10.5.
Backend использует закреплённый локальный Docker image ID из `compose.expanded.yml`.
Image ID остальных контейнеров и ограничения ресурсов сохранены в `environment.json`
завершённого прогона. Локальный image ID сам по себе не позволяет скачать образ
из registry: для другой машины нужен экспорт образа либо отдельно документированная сборка.

Браузерный драйвер использует Playwright из `worktrees/candidate/firefly-commander/node_modules`
и обёртку `/tmp/firefly-thesis-browser/chrome`. Она запускает Chromium из
`/home/kolya/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome` с библиотеками
из `/tmp/firefly-thesis-browser/root/usr/lib/x86_64-linux-gnu`. После очистки `/tmp`
это окружение потребуется восстановить. Перенос на другую машину и другие версии
браузера считаются новым окружением; имеющиеся результаты ими не подменяются.

Сначала собрать настоящий Flutter harness, затем запускать измерения:

```bash
cd /mnt/c/DEV/startup/projects/firefly-thesis-lab/worktrees/expanded/firefly-instructor
/home/kolya/flutter/bin/flutter build web --release --no-web-resources-cdn \
  --no-wasm-dry-run --target=lib/thesis_harness.dart \
  --dart-define=FF_BACKEND_BASE_URL=http://127.0.0.1:14601/api
```

В новом Bash-процессе из каталога лаборатории:

```bash
set -euo pipefail
cd /mnt/c/DEV/startup/projects/firefly-thesis-lab
FF_THESIS_RUN="expanded-repeat-$(date -u +%Y%m%dT%H%M%SZ)"
python3 -m http.server 14602 --bind 127.0.0.1 \
  --directory worktrees/expanded/firefly-instructor/build/web \
  > results/expanded-static-repeat.log 2>&1 &
FF_THESIS_WEB_PID=$!
trap 'kill "$FF_THESIS_WEB_PID" 2>/dev/null || true' EXIT
python3 -m expanded.full "$FF_THESIS_RUN" > results/expanded-main-launch.log 2>&1
python3 -m scripts.finish_expanded "results/$FF_THESIS_RUN"
```

Порты 14600–14603 должны быть свободны до запуска. `expanded.full` последовательно
выполняет H2, H1 transport, Chromium, шесть профилей чтения и смешанную нагрузку.
Ожидания допуска по внешней нагрузке не имеют фиксированного срока; уже измеренные
запросы после всплесков нагрузки не удаляются. `finish_expanded` проверяет конечную
БД, матрицу, версии и основные каталоги, строит отчёт, сохраняет четыре дампа и
контрольные суммы, затем останавливает только свой Compose-проект.

На ошибке остаются `failure.json` и частичные артефакты. Такой каталог не является
завершённой серией. Для остановки именно расширенного стенда:

```bash
docker compose -f compose.expanded.yml stop
```

Повторное построение отчёта по завершённым данным не запускает нагрузку:

```bash
python3 -m expanded.verify results/ИМЯ_ПРОГОНА
python3 -m expanded.report results/ИМЯ_ПРОГОНА
```

Аудит основных каталогов привязан к `provenance/expanded-main-source-before.json`.
Если исходные проекты изменились после эксперимента, это будет отмечено как
несовпадение: прежний снимок нельзя обновлять ради успешного аудита. Новая версия
исследования должна иметь собственное происхождение исходников.

В данной серии обнаружен коммит уже существовавшего содержимого основного
backend: строгий аудит Git остался отрицательным при совпавших хешах файлов.
После отдельного разбора в `source-audit-review.json` финализация вызвана с
`--reviewed-metadata-drift`. Этот режим требует точного совпадения HEAD и
хеша Git status с записанным разбором и по-прежнему отклоняет изменения
проверенных исходных файлов либо экспериментальных worktree.

Отчёт и графики входят в `SHA256SUMS`. Перестроение отчёта после изменения кода
анализа требует новой фиксации контрольных сумм с сохранением истории изменения;
сырые измерения при этом не редактируются.
