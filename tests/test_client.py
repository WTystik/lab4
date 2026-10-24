"""Модульные проверки API-клиента с управляемыми ответами транспорта."""

import io
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from jira_analytics.client import JiraClient, JiraError


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.client = JiraClient("https://example.atlassian.net", "student@example.org", "test-token", retries=1)

    def test_search_reads_all_pages(self):
        with patch.object(self.client, "request", side_effect=[
            {"issues": [{"key": "T-1"}], "nextPageToken": "p2", "isLast": False},
            {"issues": [{"key": "T-2"}], "isLast": True},
        ]) as request, patch.object(self.client, "changelog", return_value=[]):
            self.assertEqual(len(self.client.issues("project = T")), 2)
            self.assertEqual(request.call_args_list[1].args[1]["nextPageToken"], "p2")

    def test_repeated_search_token_fails(self):
        with patch.object(self.client, "request", return_value={"issues": [], "nextPageToken": "same"}):
            with self.assertRaises(JiraError):
                self.client.issues("project = T")

    def test_history_reads_short_pages_until_total(self):
        with patch.object(self.client, "request", side_effect=[
            {"values": [{"id": "1"}], "total": 2, "isLast": False},
            {"values": [{"id": "2"}], "total": 2, "isLast": True},
        ]) as request:
            self.assertEqual(len(self.client.changelog("T-1")), 2)
            self.assertEqual(request.call_args_list[1].args[1]["startAt"], 1)

    def test_empty_intermediate_history_fails(self):
        with patch.object(self.client, "request", return_value={"values": [], "total": 3, "isLast": False}):
            with self.assertRaises(JiraError):
                self.client.changelog("T-1")

    def test_unauthorized_is_reported_without_token(self):
        error = HTTPError("https://example.org", 401, "Denied", {}, None)
        with patch("jira_analytics.client.urlopen", side_effect=error):
            with self.assertRaises(JiraError) as result:
                self.client.request("/rest/api/3/myself")
            self.assertNotIn("test-token", str(result.exception))

    def test_rate_limit_retries(self):
        error = HTTPError("https://example.org", 429, "Rate limit", {"Retry-After": "1"}, None)
        with patch("jira_analytics.client.urlopen", side_effect=[error, io.BytesIO(b'{"ok": true}')]), \
             patch("jira_analytics.client.time.sleep") as sleep:
            self.assertEqual(self.client.request("/test"), {"ok": True})
            sleep.assert_called_once_with(1)

    def test_non_json_is_rejected(self):
        with patch("jira_analytics.client.urlopen", return_value=io.BytesIO(b"<html>login</html>")):
            with self.assertRaises(JiraError):
                self.client.request("/test")

    def test_http_is_rejected(self):
        with self.assertRaises(ValueError):
            JiraClient("http://example.org", "user", "token")
