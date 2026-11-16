"""Интеграция модулей и CLI на локальном наборе, без доступа к реальной Jira."""

import json
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jira_analytics.__main__ import main
from jira_analytics.analytics import analyze
from jira_analytics.client import JiraClient

ROOT = Path(__file__).resolve().parents[1]


class IntegrationTests(unittest.TestCase):
    def test_apache_project_url_to_full_pipeline_without_cloud_credentials(self):
        issues = json.loads((ROOT / "tests" / "fixture.json").read_text(encoding="utf-8"))
        page = {"total": len(issues), "issues": [
            {**issue, "changelog": {"total": len(issue["histories"]), "histories": issue["histories"]}}
            for issue in issues]}
        with tempfile.TemporaryDirectory() as temp, \
             patch.dict(os.environ, {"JIRA_EMAIL": "old-cloud-user", "JIRA_API_TOKEN": "old-cloud-secret"}), \
             patch("jira_analytics.client.urlopen") as transport:
            transport.return_value = io.BytesIO(json.dumps(page).encode())
            code = main(["--config", str(ROOT / "config.toml"), "--project",
                         "https://issues.apache.org/jira/projects/HDFS", "--output", temp])
            self.assertEqual(code, 0)
            request = transport.call_args.args[0]
            self.assertIn("/jira/rest/api/2/search?", request.full_url)
            self.assertNotIn("Authorization", request.headers)
            summary = json.loads((Path(temp) / "summary.json").read_text(encoding="utf-8"))
            self.assertIn('project = "HDFS"', summary["source"]["jql"])
            self.assertEqual(summary["source"]["api"], "server")

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
        client = JiraClient("https://example.org", "test", "test", api="cloud")
        with patch.object(client, "request", side_effect=pages):
            result = analyze(client.issues("project = DEMO"), ["Закрыта"])
        self.assertEqual(result["total"], 4)
        self.assertEqual(result["closed_count"], 2)

    def test_saved_export_rebuilds_without_credentials_or_network(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "saved"
            source.mkdir()
            issues = json.loads((ROOT / "tests" / "fixture.json").read_text(encoding="utf-8"))
            (source / "raw_issues.json").write_text(json.dumps(issues), encoding="utf-8")
            original = {"mode": "jira", "jql": "project = DEMO", "exported_at_utc": "2026-10-20T12:00:00Z"}
            (source / "summary.json").write_text(json.dumps({"total": 4, "source": original}), encoding="utf-8")
            output = Path(temp) / "rebuilt"
            with patch.dict(os.environ, {}, clear=True), patch.object(JiraClient, "issues", side_effect=AssertionError("Network is forbidden")):
                code = main(["--config", str(ROOT / "config.toml"), "--from-export", str(source), "--output", str(output)])
            self.assertEqual(code, 0)
            result = json.loads((output / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(result["source"]["mode"], "saved-jira")
            self.assertEqual(result["source"]["exported_at_utc"], original["exported_at_utc"])
            self.assertEqual(result["total"], 4)
