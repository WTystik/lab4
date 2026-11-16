"""Модульные проверки API-клиента с управляемыми ответами транспорта."""

import io
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from jira_analytics.client import JiraClient, JiraError, jira_address


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


class ServerClientTests(unittest.TestCase):
    def setUp(self):
        self.client = JiraClient("https://issues.apache.org/jira")

    @staticmethod
    def issue(key, events=None):
        events = [] if events is None else events
        return {"key": key, "changelog": {"startAt": 0, "total": len(events), "histories": events}}

    def test_apache_root_and_project_urls(self):
        self.assertEqual(jira_address("https://issues.apache.org/"), ("https://issues.apache.org/jira", None))
        self.assertEqual(jira_address("https://issues.apache.org/jira/projects/HDFS/issues"),
                         ("https://issues.apache.org/jira", "HDFS"))
        self.assertEqual(self.client.api, "server")
        self.assertNotIn("Authorization", self.client.headers)

    def test_credentials_in_url_are_rejected(self):
        with self.assertRaises(ValueError):
            jira_address("https://user:secret@issues.apache.org/jira")

    def test_server_search_reads_short_pages_and_embedded_history(self):
        event = {"created": "2026-01-01T10:00:00Z", "items": []}
        with patch.object(self.client, "request", side_effect=[
            {"startAt": 0, "total": 2, "issues": [self.issue("KAFKA-1", [event])]},
            {"startAt": 1, "total": 2, "issues": [self.issue("KAFKA-2")]},
        ]) as request:
            result = self.client.issues("project = KAFKA")
        self.assertEqual([x["key"] for x in result], ["KAFKA-1", "KAFKA-2"])
        self.assertEqual(result[0]["histories"], [event])
        self.assertNotIn("changelog", result[0])
        self.assertEqual(request.call_args_list[1].args[1]["startAt"], 1)
        self.assertEqual(request.call_args_list[0].args[0], "/rest/api/2/search")

    def test_server_partial_search_history_reads_full_issue(self):
        item = self.issue("KAFKA-1")
        item["changelog"]["total"] = 1
        full = self.issue("KAFKA-1", [{"id": "h1"}])
        with patch.object(self.client, "request", side_effect=[
            {"total": 1, "issues": [item]}, full,
        ]) as request:
            self.assertEqual(self.client.issues("project=KAFKA")[0]["histories"], [{"id": "h1"}])
        self.assertEqual(request.call_args_list[1].args[0], "/rest/api/2/issue/KAFKA-1")

    def test_server_incomplete_history_is_not_silently_used(self):
        item = self.issue("KAFKA-1")
        item["changelog"]["total"] = 2
        with patch.object(self.client, "request", side_effect=[{"total": 1, "issues": [item]}, item]):
            with self.assertRaisesRegex(JiraError, "неполную историю"):
                self.client.issues("project=KAFKA")

    def test_server_empty_intermediate_page_fails(self):
        with patch.object(self.client, "request", return_value={"total": 2, "issues": []}):
            with self.assertRaises(JiraError):
                self.client.issues("project=KAFKA")

    def test_server_duplicate_issues_fail(self):
        with patch.object(self.client, "request", side_effect=[
            {"startAt": 0, "total": 2, "issues": [self.issue("KAFKA-1")]},
            {"startAt": 1, "total": 2, "issues": [self.issue("KAFKA-1")]},
        ]):
            with self.assertRaisesRegex(JiraError, "повторилась"):
                self.client.issues("project=KAFKA")

    def test_server_ignoring_start_offset_fails(self):
        with patch.object(self.client, "request", side_effect=[
            {"startAt": 0, "total": 2, "issues": [self.issue("KAFKA-1")]},
            {"startAt": 0, "total": 2, "issues": [self.issue("KAFKA-2")]},
        ]):
            with self.assertRaisesRegex(JiraError, "повторил страницу"):
                self.client.issues("project=KAFKA")

    def test_empty_project_returns_empty_list(self):
        with patch.object(self.client, "request", return_value={"total": 0, "issues": []}):
            self.assertEqual(self.client.issues("project=EMPTY"), [])
