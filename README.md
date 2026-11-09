# Аналитика задач Jira — лабораторная работа 4

Приложение на Python получает задачи **Jira Cloud через REST API** и строит шесть видов отчетов. Результат — автономная HTML-страница, PNG, сводка JSON и CSV по календарным дням.

## Реализованные требования

| Требование | Результат |
|---|---|
| От создания до закрытия | Гистограмма закрытых задач с известной датой финального закрытия |
| Время по состояниям | Отдельная диаграмма каждого состояния; повторные заходы суммируются, непосещенное состояние имеет время 0 |
| Созданные и закрытые по дням | Дневные значения и накопительные итоги на двух панелях |
| Исполнители и репортеры | Подсчет по ролям; не более 30 пользователей, рейтинг по различным задачам |
| Залогированные трудозатраты | Гистограмма закрытых задач, отсутствие записи отделено от явного нуля |
| Степень серьезности | Группировка по полю из конфигурации; для учебного проекта используется priority |

Проверка требований и соответствующих модулей: [docs/requirements.md](docs/requirements.md).

## Установка из исходников

Требуется Python **3.11 или новее**. В PowerShell из папки проекта:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install -e . --no-build-isolation
```

На Linux используйте `python3 -m venv .venv` и `.venv/bin/python`.

## Подключение к Jira

Настройки читаются из `config.toml`:

```toml
[jira]
base_url = "https://your-site.atlassian.net"
jql = "project = HELP ORDER BY created ASC"
closed_status_names = ["Закрыта", "Done", "Closed", "Resolved"]
severity_field = "priority"
utc_offset_hours = 3
timeout_seconds = 30
retries = 3
```

Укажите адрес своей Jira Cloud и JQL. Нужны email Atlassian, API token и право просмотра задач и их истории. Токен передается через окружение:

```powershell
$env:JIRA_EMAIL = Read-Host "Email учетной записи Atlassian"
$taskToken = Read-Host "API token" -AsSecureString
$env:JIRA_API_TOKEN = [System.Net.NetworkCredential]::new("", $taskToken).Password
.\start.cmd --output output-live
Invoke-Item .\output-live\index.html
```

`start.cmd` запускает Python из `.venv`; окружение и зависимости должны быть установлены заранее.

На Linux:

```bash
export JIRA_EMAIL='your-email'
read -s JIRA_API_TOKEN
export JIRA_API_TOKEN
.venv/bin/python -m jira_analytics --config config.toml --output output-live
```

Клиент использует Jira Cloud `/rest/api/3/search/jql` и постраничную историю. Для Jira Server/Data Center, включая ASF Jira, потребуется другой вариант клиента: замена одного URL не заменяет адаптацию API.

## Повторная обработка сохраненной выгрузки

Папка должна содержать `raw_issues.json` и `summary.json`, созданные при подключении к Jira. Учетные данные и сеть не требуются:

```powershell
.\start.cmd --from-export .\path-to-saved-export --output output-rebuilt
```

В отчете указывается сохраненная выгрузка. Исходная дата получения данных сохраняется в JSON, дата повторного расчета хранится отдельно.

## Учебный пример без учетной записи Jira

```powershell
.\start.cmd --fixture tests\fixture.json --output output-demo
```

Этот режим явно помечает результат как **ДЕМО**. Фикстура предназначена для проверки программы.

## Как читать графики

- У гистограмм X — время, Y — число задач в интервале. Над столбцами подписано количество.
- Все диаграммы состояний используют одну единицу времени. В небольшой выборке под рисунком приведены фактические длительности задач.
- Когда все значения равны нулю, распределение показано в точке 0 с пояснением.
- Жизненный цикл заканчивается при финальном закрытии. После повторного открытия прежнее время в закрытом состоянии тоже входит в жизненный цикл.
- Дата `updated` не подменяет закрытие. При отсутствии известной даты закрытия временные длительности пропускаются, но доступные трудозатраты остаются в расчете.
- Учебная выборка из 6 задач, 3 закрытых задач и 1 пользователя демонстрирует работу программы. Топ-30 — верхний предел числа пользователей.
- Поле `priority` соответствует степени серьезности в данном учебном проекте.

## Структура программы

- `client.py` — HTTPS, авторизация, загрузка всех страниц, повторы временных ошибок;
- `analytics.py` — независимые от сети расчеты и история статусов;
- `charts.py` — matplotlib, PNG и автономный HTML;
- `__main__.py` — CLI, TOML, журнал выполнения и экспорт.

Публичные методы имеют docstring. Обрабатываются HTTP 401/403, 429, 5xx, сетевые ошибки и некорректные ответы. Токен не включается в сообщения об ошибках.

## Тесты и сборка

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\build_release.ps1
```

Тесты охватывают расчеты, клиент, CLI и формирование файлов. Внешняя Jira в тестах не вызывается.

Сборка сначала запускает тесты, затем создает wheel текущей версии из `pyproject.toml` и `dist\jira-lab4-analytics-windows.zip`. В ZIP включены только wheel-пакет, `config.toml`, `start.cmd` и `README.md`. Окружение, токены и выгрузки задач в архив не входят.

Установка распакованного дистрибутива версии 1.1.0:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .\jira_lab4_analytics-1.1.0-py3-none-any.whl
```

После настройки конфигурации и окружения выполните `.\start.cmd --output output-live`.

## Создаваемые файлы

- `index.html` — шесть разделов и переключатель отдельных состояний;
- `01_lifetime.png`, `02_statuses.png`, `03_daily.png`, `04_users.png`, `05_logged.png`, `06_severity.png`;
- `02_status_XX.png` — отдельные состояния в порядке появления в истории;
- `charts.json` — соответствие состояний, файлов и единиц времени;
- `raw_issues.json`, `summary.json`, `daily.csv`, `run.log`.

Локальные выгрузки и окружение исключены из Git через `.gitignore`.
