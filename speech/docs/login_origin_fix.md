# Исправление входа «Неверный origin»

Причина найдена в серверной политике `Referrer-Policy: no-referrer`, а не в
ключе пользователя. При обычной отправке HTML-формы она приводила к
`Origin: null`, который строгая проверка входа отклоняла. В изолированном
браузерном воспроизведении до исправления записан POST /login → 403;
после исправления тот же браузер отправил реальный origin и получил 303,
затем открыл авторизованный список фрагментов.

В FastAPI/UI и сервисе разметки политика заменена на `same-origin`.
На посторонние сайты referrer по-прежнему не передаётся; сравнение origin,
ключа, CSRF-защита записи и HttpOnly/SameSite cookies сохранены.
Запросы с `Origin: null`, другим сайтом, портом или схемой не разрешаются.

Такое влияние referrer policy на обычный POST описано в
[MDN Referrer-Policy](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Referrer-Policy).
Точная причина проверена браузерным запросом нашего приложения, а не только
по документации. Сырые логи и результаты тестов лежат в `reports/login-origin-fix-v1`.

После обновления сервиса пользователю достаточно заново открыть
http://127.0.0.1:8010/ и войти. Если в адресной строке остался `/login` с ошибкой,
перейдите на `/`, чтобы загрузить свежую форму.

Браузерная проверка использовала временный синтетический пакет на порту 8014.
Настоящие train/dev были проверены отдельно через HTTP без сохранения ревизий:
18 аудио ranges, login, packet и exports. Это проверка входа, а не утверждение
о полностью протестированном ручном процессе разметки.

Изменение заголовка в API не меняет декодирование, веса или измерения ML.
Старые отчёты не переименованы в текущие quality results. Образ до исправления
сохранён как `north55-speech:before-login-fix-v1`; исправленный —
`north55-speech:login-fix-v1`, также помеченный текущим `north55-speech:0.1.0`.
API и annotation обновлены; worker и выполняемые им задания не перезапускались.

Выполненные команды PowerShell/Linux из корня проекта:

```sh
docker build -f scripts/Dockerfile.refresh --build-arg BASE_IMAGE=north55-speech:0.1.0 -t north55-speech:login-fix-v1 .
docker compose -f compose.yaml -f compose.annotation.yaml --profile annotation restart annotation
docker compose up -d --no-deps api
docker compose -f compose.yaml -f compose.annotation.yaml --profile annotation exec -T annotation python -m scripts.check_annotation_service --output /tmp/login-origin-service.json
```

Перед `up` текущий tag 0.1.0 был установлен на проверенный исправленный образ;
его SHA и исходный SHA записаны в `reports/login-origin-fix-v1/images.json`.
