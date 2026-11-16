"""Чтение Jira Server/Data Center и Cloud через публичный REST API."""

import base64
import json
import logging
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

LOG = logging.getLogger(__name__)


def jira_address(value):
    """Принимает адрес сервера или страницу проекта; возвращает базу API и ключ."""
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Укажите адрес Jira https:// без логина и пароля в URL.")
    path = parsed.path.rstrip("/")
    project = None
    match = re.search(r"/projects/([A-Za-z][A-Za-z0-9_]*)(?:/.*)?$", path)
    if match:
        project = match.group(1).upper()
        path = path[:match.start()]
    if parsed.hostname.lower() == "issues.apache.org" and not path:
        path = "/jira"
    return f"https://{parsed.netloc}{path}", project


class JiraError(RuntimeError):
    """Ошибка доступа к API или некорректный ответ сервера."""


class JiraClient:
    """Читает задачи; Server использует API v2, Cloud — enhanced search v3."""

    def __init__(self, base_url, email="", token="", timeout=60, retries=3,
                 api="auto", page_size=100):
        self.base_url, _ = jira_address(base_url)
        if api not in ("auto", "server", "cloud"):
            raise ValueError("api должен быть auto, server или cloud.")
        self.api = ("cloud" if urlparse(self.base_url).hostname.endswith(".atlassian.net")
                    else "server") if api == "auto" else api
        self.timeout = timeout
        self.retries = retries
        if not 1 <= page_size <= 1000:
            raise ValueError("page_size должен быть от 1 до 1000.")
        self.page_size = page_size
        self.headers = {"Accept": "application/json", "User-Agent": "jira-lab4-analytics/1.2"}
        if token:
            if email:
                encoded = base64.b64encode(f"{email}:{token}".encode()).decode()
                self.headers["Authorization"] = f"Basic {encoded}"
            else:
                self.headers["Authorization"] = f"Bearer {token}"

    @property
    def api_root(self):
        """Корень REST API для выбранного типа Jira."""
        return "/rest/api/3" if self.api == "cloud" else "/rest/api/2"

    def request(self, path, params=None):
        """Выполняет GET; повторяет временные сетевые ошибки, HTTP 429 и 5xx."""
        url = self.base_url + path
        if params:
            url += "?" + urlencode(params)
        for attempt in range(self.retries + 1):
            try:
                with urlopen(Request(url, headers=self.headers), timeout=self.timeout) as reply:
                    return json.load(reply)
            except HTTPError as exc:
                code = exc.code
                delay_header = exc.headers.get("Retry-After", "")
                exc.close()
                if code in (401, 403):
                    raise JiraError(f"HTTP {code}: сервер запретил доступ. Проверьте права просмотра и настройки авторизации.") from None
                if code != 429 and not 500 <= code < 600:
                    details = ""
                    if code == 400:
                        # Ответ уже закрыт; URL и секретные заголовки в ошибку не попадают.
                        details = " Проверьте синтаксис JQL и ключ проекта."
                    raise JiraError(f"HTTP {code}: проверьте URL и доступ к проекту.{details}") from None
                if attempt == self.retries:
                    raise JiraError(f"HTTP {code}: исчерпаны повторные попытки.") from None
                delay = float(delay_header) if delay_header.isdigit() else 2 ** attempt
                LOG.warning("Временный HTTP %s; повтор через %.1f с", code, min(delay, 60))
                time.sleep(min(delay, 60))
            except (URLError, TimeoutError, OSError):
                if attempt == self.retries:
                    raise JiraError("Сетевая ошибка: проверьте подключение, DNS и адрес Jira.") from None
                time.sleep(2 ** attempt)
            except (ValueError, UnicodeError):
                raise JiraError("Сервер вернул некорректный JSON.") from None
        raise JiraError("Не удалось получить ответ Jira.")

    def issues(self, jql, severity_field="priority"):
        """Загружает все страницы поиска и полную историю переходов каждой задачи."""
        fields = list(dict.fromkeys([
            "created", "resolutiondate", "status", "assignee", "reporter",
            "priority", "timespent", severity_field,
        ]))
        if self.api == "server":
            return self._server_issues(jql, fields)
        result, tokens, seen_keys = [], set(), set()
        token = None
        while True:
            params = {"jql": jql, "maxResults": self.page_size, "fields": ",".join(fields)}
            if token:
                params["nextPageToken"] = token
            page = self.request("/rest/api/3/search/jql", params)
            if "issues" not in page:
                raise JiraError("В ответе поиска отсутствует список issues.")
            for issue in page["issues"]:
                if issue["key"] not in seen_keys:
                    result.append(issue)
                    seen_keys.add(issue["key"])
            next_token = page.get("nextPageToken")
            if page.get("isLast") is True or not next_token:
                break
            if next_token in tokens:
                raise JiraError("Сервер повторил токен страницы поиска.")
            tokens.add(next_token)
            token = next_token
        for index, issue in enumerate(result, 1):
            issue["histories"] = self.changelog(issue["key"])
            LOG.info("История %s: %s/%s", issue["key"], index, len(result))
        return result

    def _server_issues(self, jql, fields):
        """Server возвращает историю в expand=changelog вместе со страницами поиска."""
        result, seen, start = [], set(), 0
        while True:
            page = self.request("/rest/api/2/search", {
                "jql": jql, "startAt": start, "maxResults": self.page_size,
                "fields": ",".join(fields), "expand": "changelog",
            })
            batch = page.get("issues")
            if not isinstance(batch, list) or not isinstance(page.get("total"), int):
                raise JiraError("Некорректная страница поиска Jira Server.")
            if page.get("startAt", start) != start:
                raise JiraError("Сервер повторил страницу поиска. Выгрузка неполная.")
            for issue in batch:
                if issue["key"] in seen:
                    raise JiraError("Задача повторилась на страницах поиска. Повторите выгрузку со стабильной сортировкой JQL.")
                issue["histories"] = self._server_history(issue)
                issue.pop("changelog", None)
                result.append(issue)
                seen.add(issue["key"])
            start += len(batch)
            LOG.info("Загружено задач: %s/%s", start, page["total"])
            for warning in page.get("warningMessages") or []:
                LOG.warning("Jira: %s", warning)
            if start >= page["total"]:
                return result
            if not batch:
                raise JiraError("Сервер вернул пустую промежуточную страницу поиска.")

    def _server_history(self, issue):
        """Проверяет полноту expanded history, при необходимости читает саму задачу."""
        history = issue.get("changelog", {})
        events = history.get("histories")
        if not isinstance(events, list) or len(events) != history.get("total"):
            full = self.request(f"/rest/api/2/issue/{quote(issue['key'], safe='')}",
                                {"fields": "status", "expand": "changelog"})
            history = full.get("changelog", {})
            events = history.get("histories")
        if (not isinstance(events, list) or len(events) != history.get("total")
                or history.get("startAt", 0) != 0):
            raise JiraError(f"{issue['key']}: Jira Server вернул неполную историю; расчёт длительностей остановлен.")
        return events

    def changelog(self, key):
        """Читает всю историю задачи с учетом startAt, total и isLast."""
        result, start = [], 0
        while True:
            page = self.request(f"/rest/api/3/issue/{quote(key, safe='')}/changelog",
                                {"startAt": start, "maxResults": 100})
            batch = page.get("values")
            if not isinstance(batch, list):
                raise JiraError(f"Некорректная история {key}.")
            result.extend(batch)
            start += len(batch)
            if page.get("isLast") is True or start >= page.get("total", float("inf")):
                return result
            if not batch:
                raise JiraError(f"Неполная история {key}: сервер вернул пустую промежуточную страницу.")
