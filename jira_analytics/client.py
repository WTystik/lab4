"""Клиент Jira Cloud с постраничной загрузкой и ограниченными повторами."""

import base64
import json
import logging
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

LOG = logging.getLogger(__name__)


class JiraError(RuntimeError):
    """Ошибка доступа к API или некорректный ответ сервера."""


class JiraClient:
    """Читает задачи Jira Cloud; не изменяет данные проекта."""

    def __init__(self, base_url, email, token, timeout=30, retries=3):
        if urlparse(base_url).scheme != "https":
            raise ValueError("Для Jira требуется адрес https://")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        encoded = base64.b64encode(f"{email}:{token}".encode()).decode()
        self.headers = {"Accept": "application/json", "Authorization": f"Basic {encoded}"}

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
                    raise JiraError(f"HTTP {code}: проверьте email, токен и права просмотра.") from None
                if code != 429 and not 500 <= code < 600:
                    raise JiraError(f"HTTP {code}: проверьте URL, JQL и доступ к проекту.") from None
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
        """Загружает ВСЕ страницы enhanced search, затем полную историю каждой задачи."""
        fields = list(dict.fromkeys([
            "created", "resolutiondate", "status", "assignee", "reporter",
            "priority", "timespent", severity_field,
        ]))
        result, tokens, seen_keys = [], set(), set()
        token = None
        while True:
            params = {"jql": jql, "maxResults": 100, "fields": ",".join(fields)}
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
