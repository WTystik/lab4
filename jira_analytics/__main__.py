"""Командная строка: выгрузка Jira или явно обозначенный локальный пример."""

import argparse
import csv
from datetime import datetime, timezone
import json
import logging
import os
import re
from pathlib import Path
import sys
import tomllib
import webbrowser

from .analytics import analyze
from .charts import render_charts
from .client import JiraClient, JiraError, jira_address


def main(argv=None):
    """Запускает расчет; при ошибке возвращает ненулевой код завершения."""
    parser = argparse.ArgumentParser(description="Аналитика Apache Jira / Jira Cloud для ЛР4")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--output", default="output")
    parser.add_argument("--project", help="Ключ проекта (KAFKA, HDFS) или ссылка на страницу проекта")
    parser.add_argument("--server", help="Адрес Jira, например https://issues.apache.org/jira")
    parser.add_argument("--api", choices=["auto", "server", "cloud"], help="Тип REST API")
    parser.add_argument("--jql", help="Собственный фильтр вместо всех задач проекта")
    parser.add_argument("--open", action="store_true", help="Открыть готовый отчёт в браузере")
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--fixture", help="Локальный JSON; результат всегда маркируется ДЕМО")
    inputs.add_argument("--from-export", help="Папка ранее сохраненной выгрузки Jira: raw_issues.json и summary.json")
    parser.add_argument("--list-fields", action="store_true", help="Показать ID полей Jira")
    args = parser.parse_args(argv)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(output / "run.log", encoding="utf-8")], force=True)
    try:
        with open(args.config, "rb") as handle:
            config = tomllib.load(handle)
        settings = config["jira"]
        severity = settings.get("severity_field", "priority")
        if args.fixture:
            issues = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
            label = "ДЕМО  локальный искусственный набор  не выгрузка Jira"
            source = {"mode": "demo", "fixture": str(args.fixture)}
        elif args.from_export:
            previous = Path(args.from_export)
            saved = json.loads((previous / "summary.json").read_text(encoding="utf-8"))
            issues = json.loads((previous / "raw_issues.json").read_text(encoding="utf-8"))
            origin = saved.get("source", {})
            if origin.get("mode") not in ("jira", "saved-jira"):
                raise ValueError("Для повторного расчета требуется сохраненная выгрузка Jira; для примера используйте --fixture.")
            if len(issues) != saved["total"]:
                raise ValueError("Число задач в raw_issues.json не совпадает со сводкой выгрузки.")
            source = {**origin, "mode": "saved-jira"}
            label = origin.get("jql", "Выборка Jira") + " · сохраненная выгрузка"
        else:
            email = os.environ.get("JIRA_EMAIL", "")
            token = os.environ.get("JIRA_API_TOKEN", "")
            base_url, url_project = jira_address(args.server or settings["base_url"])
            project = args.project or url_project or settings.get("project")
            if project and project.startswith("https://"):
                base_url, project = jira_address(project)
                if not project:
                    raise ValueError("В ссылке не найден проект. Используйте /jira/projects/KAFKA или ключ KAFKA.")
            if project:
                if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", project):
                    raise ValueError("Некорректный ключ проекта. Пример: KAFKA или HDFS.")
                project = project.upper()
            jql = args.jql or (None if args.project or url_project else settings.get("jql"))
            if not jql:
                if not project:
                    raise ValueError("Укажите --project KAFKA или jql в config.toml.")
                jql = f'project = "{project}" ORDER BY created ASC, key ASC'
            # Облачные учетные данные не отправляются на публичный Apache Server.
            api = args.api or settings.get("api", "auto")
            if api == "server" or (api == "auto" and not base_url.split("/")[2].endswith(".atlassian.net")):
                email, token = "", ""
            client = JiraClient(base_url, email, token,
                                settings.get("timeout_seconds", 60), settings.get("retries", 3),
                                api=api,
                                page_size=settings.get("page_size", 100))
            if client.api == "cloud" and (not email or not token):
                raise ValueError("Для Jira Cloud задайте JIRA_EMAIL и JIRA_API_TOKEN. Публичная Apache Jira работает без них.")
            if args.list_fields:
                for field in client.request(client.api_root + "/field"):
                    print(field["id"], "—", field["name"])
                return 0
            logging.info("Источник: %s; API: %s; фильтр: %s", base_url, client.api, jql)
            issues = client.issues(jql, severity)
            label = jql
            source = {"mode": "jira", "base_url": base_url, "api": client.api, "jql": jql}
        if not issues:
            raise ValueError("Выборка пуста. Проверьте JQL, проект и права просмотра.")
        time_field = "processed_at_utc" if args.from_export else "exported_at_utc"
        source[time_field] = datetime.now(timezone.utc).isoformat()
        data = analyze(issues, settings.get("closed_status_names", ["Закрыта", "Done", "Closed"]),
                       settings.get("utc_offset_hours", 3), severity)
        data["source"] = source
        (output / "raw_issues.json").write_text(json.dumps(issues, ensure_ascii=False, indent=2), encoding="utf-8")
        (output / "summary.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        with open(output / "daily.csv", "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=["day", "created", "closed", "cumulative_created", "cumulative_closed"])
            writer.writeheader()
            writer.writerows(data["daily"])
        render_charts(data, output, label)
        for warning in data["warnings"]:
            logging.warning(warning)
        logging.info("Режим: %s; задач: %s; закрытых: %s; с датой: %s; без трудозатрат: %s",
                     source["mode"], data["total"], data["closed_count"],
                     data["closed_with_date_count"], data["missing_worklogs"])
        logging.info("Готово: %s", (output / "index.html").resolve())
        if args.open:
            webbrowser.open((output / "index.html").resolve().as_uri())
        return 0
    except (JiraError, ValueError, KeyError, TypeError, OSError, ImportError) as exc:
        logging.error("%s", exc)
        return 1
    finally:
        # Удаляем закрытые FileHandler: повторный запуск main в том же процессе
        # не должен пытаться заново открыть журнал уже удалённой папки.
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
            handler.close()


if __name__ == "__main__":
    sys.exit(main())
