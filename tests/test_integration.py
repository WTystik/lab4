"""Интеграция модулей и CLI на локальном наборе, без доступа к реальной Jira."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jira_analytics.__main__ import main
from jira_analytics.analytics import analyze
from jira_analytics.client import JiraClient

ROOT = Path(__file__).resolve().parents[1]


class IntegrationTests(unittest.TestCase):
    def test_fixture_to_cli_charts_and_json(self):
        with tempfile.TemporaryDirectory() as temp:
            code = main(["--config", str(ROOT / "config.toml"),
                         "--fixture", str(ROOT / "tests" / "fixture.json"), "--output", temp])
            self.assertEqual(code, 0)
            output = Path(temp)
            summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["source"]["mode"], "demo")
            for name in ["01_lifetime.png", "02_statuses.png", "03_daily.png", "04_users.png",
                         "05_logged.png", "06_severity.png", "02_status_01.png", "daily.csv", "index.html"]:
                self.assertGreater((output / name).stat().st_size, 0)
            self.assertIn("ДЕМО", (output / "index.html").read_text(encoding="utf-8"))

    def test_client_pagination_to_analytics(self):
        issues = json.loads((ROOT / "tests" / "fixture.json").read_text(encoding="utf-8"))
        pages = [{"issues": issues[:2], "nextPageToken": "next"}, {"issues": issues[2:], "isLast": True}]
        pages += [{"values": issue["histories"], "isLast": True} for issue in issues]
        client = JiraClient("https://example.org", "test", "test")
        with patch.object(client, "request", side_effect=pages):
            result = analyze(client.issues("project = DEMO"), ["Закрыта"])
        self.assertEqual(result["total"], 4)
        self.assertEqual(result["closed_count"], 2)
