"""Модульные проверки расчетов на заранее известных результатах."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import unittest

from jira_analytics.analytics import analyze, closed_at, parse_time, status_hours, user_counts


def fixture():
    return json.loads((Path(__file__).parent / "fixture.json").read_text(encoding="utf-8"))


class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.issues = fixture()
        self.data = analyze(self.issues, ["Закрыта"])

    def test_iso_timezone_formats(self):
        self.assertEqual(parse_time("2026-10-20T12:00:00+0300"), parse_time("2026-10-20T09:00:00Z"))

    def test_naive_time_rejected(self):
        with self.assertRaises(ValueError):
            parse_time("2026-10-20T12:00:00")

    def test_only_closed_in_lifetime(self):
        self.assertEqual(self.data["total"], 4)
        self.assertEqual(self.data["closed_count"], 2)
        self.assertEqual(self.data["lifetime_hours"], [8.0, 24.0])

    def test_final_close_after_reopen(self):
        end = closed_at(self.issues[0], ["Закрыта"])
        self.assertEqual(end, parse_time("2026-10-20T17:00:00+0300"))

    def test_open_issue_with_old_resolution_is_excluded(self):
        issue = deepcopy(self.issues[2])
        issue["fields"]["resolutiondate"] = "2026-10-20T12:00:00+0300"
        self.assertIsNone(closed_at(issue, ["Закрыта"]))

    def test_repeated_status_is_summed(self):
        totals = status_hours(self.issues[0], closed_at(self.issues[0], ["Закрыта"]))
        self.assertEqual(totals["В работе"], 5)
        self.assertEqual(totals["Закрыта"], 1)
        self.assertEqual(sum(totals.values()), 8)

    def test_days_without_events_are_present(self):
        self.assertEqual([r["day"] for r in self.data["daily"]],
                         ["2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23"])
        self.assertEqual(self.data["daily"][2]["created"], 0)

    def test_cumulative_totals_match_selection(self):
        last = self.data["daily"][-1]
        self.assertEqual(last["cumulative_created"], 4)
        self.assertEqual(last["cumulative_closed"], 2)

    def test_calendar_day_uses_configured_timezone(self):
        issue = deepcopy(self.issues[2])
        issue["fields"]["created"] = "2026-10-20T23:00:00Z"
        self.assertEqual(analyze([issue], ["Закрыта"], 3)["daily"][0]["day"], "2026-10-21")

    def test_missing_worklog_is_not_zero(self):
        self.assertEqual(self.data["logged_hours"], [2.0])
        self.assertEqual(self.data["missing_worklogs"], 1)

    def test_explicit_zero_worklog_is_preserved(self):
        issue = deepcopy(self.issues[1])
        issue["fields"]["timespent"] = 0
        self.assertEqual(analyze([issue], ["Закрыта"])["logged_hours"], [0.0])

    def test_same_display_name_does_not_merge_accounts(self):
        users = self.data["users"]
        self.assertEqual({row["id"] for row in users}, {"user-1", "user-2"})

    def test_same_person_in_two_roles_counts_one_for_ranking(self):
        users = user_counts([self.issues[0]])
        self.assertEqual(users[0]["total_unique"], 1)
        self.assertEqual(users[0]["assignee"], 1)
        self.assertEqual(users[0]["reporter"], 1)

    def test_top_is_limited_to_30(self):
        issues = []
        for number in range(35):
            issue = deepcopy(self.issues[2])
            issue["key"] = f"DEMO-{number}"
            issue["fields"]["assignee"] = {"accountId": str(number), "displayName": str(number)}
            issue["fields"]["reporter"] = None
            issues.append(issue)
        self.assertEqual(len(user_counts(issues)), 30)

    def test_missing_severity_has_own_bucket(self):
        self.assertEqual(self.data["severity_counts"], {"High": 1, "Medium": 2, "Не указана": 1})

    def test_negative_duration_fails(self):
        with self.assertRaises(ValueError):
            status_hours(self.issues[0], datetime(2000, 1, 1, tzinfo=timezone.utc))

    def test_no_close_timestamp_does_not_use_updated(self):
        issue = deepcopy(self.issues[1])
        issue["histories"] = []
        issue["fields"]["resolutiondate"] = None
        issue["fields"]["updated"] = "2026-10-24T12:00:00+0300"
        result = analyze([issue], ["Закрыта"])
        self.assertEqual(result["closed_count"], 1)
        self.assertEqual(result["closed_with_date_count"], 0)
        self.assertEqual(result["lifetime_hours"], [])
        self.assertEqual(len(result["warnings"]), 1)

    def test_closed_without_timestamp_preserves_logged_time(self):
        issue = deepcopy(self.issues[0])
        issue["histories"] = []
        issue["fields"]["resolutiondate"] = None
        result = analyze([issue], ["Закрыта"])
        self.assertEqual(result["closed_count"], 1)
        self.assertEqual(result["closed_without_date_count"], 1)
        self.assertEqual(result["logged_hours"], [2.0])
        self.assertEqual(result["missing_worklogs"], 0)

    def test_unvisited_state_is_counted_as_zero_duration(self):
        self.assertEqual(self.data["status_hours"]["Проверка"], [1.0, 0.0])
        for values in self.data["status_hours"].values():
            self.assertEqual(len(values), self.data["closed_with_date_count"])

    def test_state_durations_add_up_to_each_lifetime(self):
        for row in self.data["issues"]:
            if row["closed"] is not None:
                self.assertAlmostEqual(sum(row["status_hours"].values()), row["lifetime_hours"])


if __name__ == "__main__":
    unittest.main()
