"""Командная строка: выгрузка Jira или явно обозначенный локальный пример."""

import argparse
import csv
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import sys
import tomllib

from .analytics import analyze
from .charts import render_charts
from .client import JiraClient, JiraError


def main(argv=None):
    """Запускает расчет; при ошибке возвращает ненулевой код завершения."""
    parser = argparse.ArgumentParser(description="Аналитика Jira Cloud для ЛР4")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--output", default="output")
    parser.add_argument("--fixture", help="Локальный JSON; результат всегда маркируется ДЕМО")
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
        else:
            email = os.environ.get("JIRA_EMAIL", "")
            token = os.environ.get("JIRA_API_TOKEN", "")
            if not email or not token:
                raise ValueError("Задайте JIRA_EMAIL и JIRA_API_TOKEN в текущем окне PowerShell.")
            client = JiraClient(settings["base_url"], email, token,
                                settings.get("timeout_seconds", 30), settings.get("retries", 3))
            if args.list_fields:
                for field in client.request("/rest/api/3/field"):
                    print(field["id"], "—", field["name"])
                return 0
            issues = client.issues(settings["jql"], severity)
            label = settings["jql"]
            source = {"mode": "jira", "base_url": settings["base_url"], "jql": settings["jql"]}
        if not issues:
            raise ValueError("Выборка пуста. Проверьте JQL, проект и права просмотра.")
        source["exported_at_utc"] = datetime.now(timezone.utc).isoformat()
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
        logging.info("Режим: %s; задач: %s; закрытых с датой: %s; закрытых без трудозатрат: %s",
                     source["mode"], data["total"], data["closed_count"], data["missing_worklogs"])
        logging.info("Готово: %s", (output / "index.html").resolve())
        return 0
    except (JiraError, ValueError, KeyError, TypeError, OSError, ImportError) as exc:
        logging.error("%s", exc)
        return 1
    finally:
        logging.shutdown()


if __name__ == "__main__":
    sys.exit(main())
