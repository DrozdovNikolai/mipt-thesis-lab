# Просмотр визуальных результатов

Просмотрены изображения React/Vue на одинаковых fixtures. Это локальная инженерная проверка; пользовательский pilot и ручная работа с print dialog сюда не входят.

| Случай | Результат |
| --- | --- |
| Analytics 1024 px | Сохранены два ряда графиков. Поля локальных фильтров переносятся внутри карточки, подписи не перекрывают inputs. Из-за переноса controls доступная высота canvas отличается от React; данные и порядок сохранены. |
| Training data 1440 px | Radar, выбор компетенции и история читаемы; отсутствие grade проверено отдельно как `null`, не 0. |
| Training sessions 390 px | React/Vue capture совпадают по размерам 390×1466 и RGB difference 0. Широкие строки доступны через horizontal scroll; его двусторонняя синхронизация проверена E2E. |
| Compatibility 1024 px | Исправлено унаследованное сжатие поля даты: видны день, месяц, год и picker. Controls целиком помещаются; повторены loaded/loading/empty/error снимки на всех предусмотренных ширинах. |
| Settings error 390 px | Ошибка сохраняет доступ к странице; чтение/редактирование и сохранение draft при ошибках проверяются E2E. |
| Login 390, Forbidden 1024 px | Форма и сообщение доступа читаемы; нет горизонтального overflow. Все служебные страницы сняты на 390/768/1024/1440 px. |
| Bootstrap pending/error, login error 390 px | Loading виден до завершения `/me`; ошибка проверки сессии показывает Try again / Back to login. Ошибка входа видна рядом с формой, введённые поля сохранены, overflow нет. |
| Ranked pilots separator | После завершения canvas-анимации обе реализации показывают Kate Lopez (6) и John Miller (9), одинаковые stacked segments, скруглённые внешние края и separator между группами. |
| Native browser zoom 200% | Chrome увеличен через пять Ctrl+Plus с native keyboard events в собственное окно; DPR 1→2, width 1440→720, pinch scale 1. На восьми основных маршрутах 64 controls доступны по hit testing после scroll/focus, root overflow и exceptions нет. Просмотрены Analytics, Settings и Compatibility: поля и действия читаемы, вертикальный scroll доступен. [Протокол](evidence/m9/native-zoom/results.json). |
| Реальная скрытая вкладка, resize в фоне | Headed Chrome 145 без эмуляции фокуса сообщил hidden → visible. Analytics (4 canvas) и Profile (2 canvas) сохраняют плотность пикселей после resize; при возврате к исходному размеру canvas bytes совпали полностью, exceptions нет. [Протокол](evidence/m9/native-tabs/results.json). |
| Single-point trend, длинная подпись | Единственная точка соответствует 3.5; подписанный период отображается, график переживает resize 390→1440 без исключений. |

Canvas-анимация не останавливается через Playwright `animations: disabled`: это относится к CSS/Web Animations. Новые chart captures ждут три одинаковых снимка canvas с интервалом 100 ms. Старые полностраничные captures ждут network idle; их численные differences нельзя использовать как автоматическое доказательство пиксельного равенства графиков.

Исходные пары: `evidence/m0/react` и `evidence/m9/vue`, в том числе `charts`, `service` и `auth`. Сводка различий — [visual-differences.json](evidence/m9/visual-differences.json). Числа сами по себе не подтверждают бизнес-результат.

Остаются native popup/print и пользовательский pilot. Стандартный Playwright сообщает `visible` у обоих tabs из-за настройки focus emulation, в том числе в headed режиме. Для hidden-tab проверки Chrome запущен напрямую, управление идёт через CDP; `document.visibilityState` и события не переопределяются. Raw canvas captures находятся в `evidence/m9/native-tabs`; они сохраняют прозрачность и не входят в 166 сравнительных React/Vue пар.

## Покрытие состояний

Сохранены 166 пар React/Vue (330 tests: два chart tests дают по два снимка). Восемь основных экранов имеют loaded/loading/empty/error на 390/768/1024/1440 px и loaded на 1920 px. Login дополнен pending/error; восстановление сессии — pending/error. Admin/Forbidden — статические экраны, собственных data loading/empty/error у них нет; они используют общие состояния авторизации. `/`, index профиля и неизвестный маршрут перенаправляют на уже снятые страницы.

Ошибки baseline сохранены в снимках: React остаётся на loading после `/me` 503, а после login 401 сообщает только unauthorized. Vue показывает возможность восстановления; это согласованное исправление, а не требование повторить дефект React.

Снимки настоящего 200% zoom: `evidence/m9/native-zoom/<screen>.png` (верх страницы) и `<screen>-controls.png` (после прохода по controls). Они сделаны на реальном synthetic API и не входят в сравнительные React/Vue пары. Проверка фокуса через DOM и hit testing не подменяет native confirm. Для U02 выполнен отдельный сценарий: trusted CDP mouse click открывает настоящий confirm, native Escape отменяет его, фокус возвращается к Delete. Запрос на изменение данных не отправлен, запись остаётся в API. `Page.handleJavaScriptDialog` и stub `window.confirm` не используются; [протокол](evidence/m9/native-confirm/results.json).
