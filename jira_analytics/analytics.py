"""Расчеты отделены от сети и от визуализации, время измеряется в часах."""

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone


def parse_time(value):
    """Разбирает ISO 8601 с Z, +03:00 или +0300; требует часовой пояс."""
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Дата Jira должна включать часовой пояс.")
    return result


def transitions(issue):
    """Возвращает хронологический список изменений статуса задачи."""
    result = []
    for event in issue.get("histories", []):
        for item in event.get("items", []):
            if item.get("fieldId") == "status" or item.get("field") == "status":
                result.append((parse_time(event["created"]), item))
    return sorted(result, key=lambda entry: entry[0])


def closed_at(issue, closed_names):
    """Для сейчас закрытой задачи находит финальное закрытие; updated не используется."""
    fields = issue["fields"]
    status = fields["status"]
    if status.get("statusCategory", {}).get("key") != "done" and status["name"] not in closed_names:
        return None
    candidates = [date for date, item in transitions(issue)
                  if item.get("toString") in closed_names
                  or (status.get("id") and item.get("to") == status["id"])]
    if candidates:
        return max(candidates)
    if fields.get("resolutiondate"):
        return parse_time(fields["resolutiondate"])
    return None


def status_hours(issue, end):
    """Суммирует повторные заходы в каждый статус от создания до финального закрытия."""
    start = parse_time(issue["fields"]["created"])
    if end < start:
        raise ValueError(f"{issue['key']}: закрытие раньше создания.")
    events = [(date, item) for date, item in transitions(issue) if start <= date <= end]
    state = (events[0][1].get("fromString") if events else None) or issue["fields"]["status"]["name"]
    totals = defaultdict(float)
    cursor = start
    for date, item in events:
        totals[state] += (date - cursor).total_seconds() / 3600
        cursor = date
        state = item.get("toString") or "Без названия"
    totals[state] += (end - cursor).total_seconds() / 3600
    return dict(totals)


def user_counts(issues):
    """Топ 30 по числу разных задач в объединении ролей; идентичность по accountId."""
    users = {}
    for issue in issues:
        for role in ("assignee", "reporter"):
            user = issue["fields"].get(role)
            if not user:
                continue
            identity = user.get("accountId") or user.get("key") or user.get("name")
            if not identity:
                raise ValueError("У пользователя отсутствует стабильный идентификатор.")
            row = users.setdefault(identity, {"id": identity, "name": user.get("displayName", identity),
                                             "assignee": 0, "reporter": 0, "keys": set()})
            row[role] += 1
            row["keys"].add(issue["key"])
    rows = [{**row, "total_unique": len(row["keys"])} for row in users.values()]
    for row in rows:
        del row["keys"]
    rows.sort(key=lambda row: (-row["total_unique"], row["id"]))
    return rows[:30]


def analyze(issues, closed_names, utc_offset_hours=3, severity_field="priority"):
    """Рассчитывает шесть групп аналитики для всей выгруженной выборки."""
    tz = timezone(timedelta(hours=utc_offset_hours))
    created, closed, severities = Counter(), Counter(), Counter()
    lifetime, logged, rows, warnings = [], [], [], []
    missing_worklogs, closed_count = 0, 0
    for issue in issues:
        fields = issue["fields"]
        start = parse_time(fields["created"])
        created[start.astimezone(tz).date().isoformat()] += 1
        severity = fields.get(severity_field)
        if isinstance(severity, dict):
            severity = severity.get("name") or severity.get("value")
        if isinstance(severity, list):
            raise ValueError("Для серьезности выберите одиночное поле, а не список значений.")
        severities[str(severity or "Не указана")] += 1
        end = closed_at(issue, closed_names)
        row = {"key": issue["key"], "created": start.isoformat(), "closed": None,
               "lifetime_hours": None, "logged_hours": None, "status_hours": {}}
        status = fields["status"]
        is_closed = status.get("statusCategory", {}).get("key") == "done" or status["name"] in closed_names
        if is_closed and end is None:
            warnings.append(f"{issue['key']}: нет даты закрытия; исключена из длительностей и дат закрытия.")
        if is_closed:
            closed_count += 1
            raw_spent = fields.get("timespent")
            spent = None if raw_spent is None else float(raw_spent) / 3600
            if spent is None:
                missing_worklogs += 1
            else:
                if spent < 0:
                    raise ValueError("Залогированное время не может быть отрицательным.")
                logged.append(spent)
            row["logged_hours"] = spent
        if end is not None:
            hours = (end - start).total_seconds() / 3600
            if hours < 0:
                raise ValueError(f"{issue['key']}: отрицательная длительность.")
            lifetime.append(hours)
            closed[end.astimezone(tz).date().isoformat()] += 1
            states = status_hours(issue, end)
            row.update(closed=end.isoformat(), lifetime_hours=hours,
                       status_hours=states)
        rows.append(row)
    # Нулевое время тоже наблюдение: каждый известный статус содержит
    # по одному значению для каждой закрытой задачи с известной датой.
    dated_rows = [row for row in rows if row["closed"] is not None]
    state_names = list(dict.fromkeys(name for row in dated_rows for name in row["status_hours"]))
    by_status = {name: [row["status_hours"].get(name, 0.0) for row in dated_rows]
                 for name in state_names}
    for row in dated_rows:
        row["status_hours"] = {name: row["status_hours"].get(name, 0.0) for name in state_names}
    all_days = sorted(set(created) | set(closed))
    daily, cumulative_created, cumulative_closed = [], 0, 0
    if all_days:
        day = datetime.fromisoformat(all_days[0]).date()
        last = datetime.fromisoformat(all_days[-1]).date()
        while day <= last:
            label = day.isoformat()
            cumulative_created += created[label]
            cumulative_closed += closed[label]
            daily.append({"day": label, "created": created[label], "closed": closed[label],
                          "cumulative_created": cumulative_created, "cumulative_closed": cumulative_closed})
            day += timedelta(days=1)
    return {"total": len(issues), "closed_count": closed_count,
            "closed_with_date_count": len(lifetime), "closed_without_date_count": closed_count - len(lifetime),
            "missing_worklogs": missing_worklogs,
            "lifetime_hours": lifetime, "status_hours": by_status, "daily": daily,
            "users": user_counts(issues), "logged_hours": logged, "severity_counts": dict(severities),
            "severity_field": severity_field, "utc_offset_hours": utc_offset_hours,
            "warnings": warnings, "issues": rows}
