# Аналитика Apache Jira — лабораторная работа 4

Приложение на Python загружает задачи с https://issues.apache.org/jira через REST API и строит шесть видов графиков. Поддерживаются Jira Server/Data Center (Apache) и Jira Cloud. Результат — автономный HTML, PNG, JSON и CSV.

## Быстрый запуск Windows

Нужен Python 3.11 или новее. Из папки приложения:

```powershell
.\install.cmd
.\start.cmd --project KAFKA --open
```

Публичные проекты Apache не требуют регистрации, email и API token. По умолчанию загружаются **все задачи Kafka**, без ограничения числа страниц. Это занимает несколько минут; в консоли выводится прогресс. После успешного расчёта `--open` открывает `output/index.html` в браузере. Двойной щелчок по `start.cmd` также запускает проект из конфигурации и открывает отчёт.

Выбрать другой проект можно ключом или ссылкой:

```powershell
.\start.cmd --project HDFS --output output-hdfs --open
.\start.cmd --project https://issues.apache.org/jira/projects/KAFKA --open
```

Ссылка на страницу проекта преобразуется в базовый адрес API `https://issues.apache.org/jira`. Корневой сайт `https://issues.apache.org/` — это каталог трекеров, а не endpoint REST API.

## Фильтр выборки

Для анализа периода вместо всего проекта передайте JQL. В отчёте сохраняется точный фильтр; такая выборка содержит только соответствующие ему задачи.

```powershell
.\start.cmd --jql 'project = KAFKA AND created >= -90d ORDER BY created ASC, key ASC' --output output-recent --open
```

Конфигурация `config.toml`:

```toml
[jira]
base_url = "https://issues.apache.org/jira"
api = "auto"
project = "KAFKA"
closed_status_names = ["Закрыта", "Done", "Closed", "Resolved"]
severity_field = "priority"
utc_offset_hours = 3
timeout_seconds = 60
retries = 3
page_size = 100
```

Необязательное поле `jql` задаёт фильтр по умолчанию. Параметр `--project` заменяет его выборкой всех задач указанного проекта; `--jql` имеет высший приоритет. `--server` меняет адрес сервера, `--api server|cloud|auto` — вариант API.

## Шесть отчётов

| Требование | Результат и оси |
|---|---|
| Время от создания до закрытия | Гистограмма закрытых задач; X — время, Y — число задач |
| Время по состояниям | Отдельная гистограмма каждого состояния; X — время, Y — число задач; повторные заходы суммируются |
| Созданные и закрытые по дням | X — календарные дни, Y — число задач; дневные и накопительные значения на двух панелях |
| Пользователи | X — число задач, Y — имена; исполнитель и репортер отдельно, до 30 пользователей по числу различных задач |
| Залогированное время | Гистограмма только закрытых задач; X — трудозатраты, Y — число задач |
| Степень серьёзности | Число задач по `priority`: Blocker, Critical, Major, Minor, Trivial (или значения другого настроенного поля) |

При расчёте закрытыми считаются задачи в категории `done` или в настроенных закрытых статусах. Конец жизненного цикла — финальное закрытие; дата `updated` его не подменяет. Для каждого состояния учитываются и нулевые значения. Единицы времени подбираются по диапазону и подписываются на оси; для длительных проектов используются дни.

Apache часто не содержит записей учёта времени. Отсутствующий `timespent` не заменяется нулём: в отчёте отдельно показано число закрытых задач без трудозатрат. При полном отсутствии записей пятый график явно сообщает об отсутствии наблюдений. Это ограничение данных проекта.

Соответствие ТЗ: [docs/requirements.md](https://github.com/WTystik/lab4/blob/main/docs/requirements.md).

## Другая Jira Cloud

Для адреса `*.atlassian.net` режим `auto` выбирает Cloud API. Задайте `JIRA_EMAIL` и `JIRA_API_TOKEN` в окружении и укажите сервер и проект:

```powershell
$env:JIRA_EMAIL = Read-Host "Email Atlassian"
$taskToken = Read-Host "API token" -AsSecureString
$env:JIRA_API_TOKEN = [System.Net.NetworkCredential]::new("", $taskToken).Password
.\start.cmd --server https://your-site.atlassian.net --project HELP --open
```

На Apache облачные учётные данные из окружения не отправляются. Server-клиент читает публичные проекты анонимно; Cloud-клиент использует Basic Auth, `/rest/api/3/search/jql` и постраничную историю. Server-клиент использует `/rest/api/2/search?expand=changelog`, проверяет полноту истории и не строит длительности по обрезанным данным.

## Повторный расчёт и демонстрация

Сохранённая выгрузка содержит `raw_issues.json` и `summary.json`. Перестроить графики без сети:

```powershell
.\start.cmd --from-export output-kafka --output output-rebuilt --open
```

Для разработки доступна искусственная фикстура (в исходниках):

```powershell
.\start.cmd --fixture tests\fixture.json --output output-demo
```

Результат фикстуры всегда помечен **ДЕМО**. Сохранённая выгрузка сохраняет сведения о сервере и первоначальном получении данных.

## Разработка, тесты и сборка

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\build_release.ps1
```

41 автоматический тест: 37 модульных и 4 интеграционных. Проверяются расчёты, Cloud и Server, страницы поиска, полная история, проект по URL, анонимная загрузка, CLI и формирование графиков. Тесты не обращаются к внешнему серверу.

Сборка запускает тесты, создаёт wheel и `dist/jira-lab4-analytics-windows.zip`. В архив входят wheel, `config.toml`, `install.cmd`, `start.cmd`, `README.md`. Для распакованного дистрибутива выполняются те же `install.cmd` и `start.cmd`. Окружение, токены и выгрузки в архив не включаются.

Linux: `python3 -m venv .venv`, `.venv/bin/python -m pip install .`, затем `.venv/bin/python -m jira_analytics --project KAFKA --open`.

## Структура и результаты

- `client.py` — HTTP, Server/Cloud API, страницы, история, ограниченные повторы 429/5xx и сетевых ошибок;
- `analytics.py` — расчёты без сети;
- `charts.py` — matplotlib и автономный HTML;
- `__main__.py` — конфигурация, CLI, журнал и экспорт.

Выходные файлы: `index.html`, шесть основных PNG, отдельные `02_status_XX.png`, `charts.json`, `raw_issues.json`, `summary.json`, `daily.csv`, `run.log`. В HTML есть переключатель состояний и ссылки на исходные результаты. Локальные выгрузки, окружение и секреты исключены из Git.

REST API Server: https://docs.atlassian.com/software/jira/docs/api/REST/10.3.0/
