"""Quiet hours and per-source rhythm. Run: python3 -m unittest discover -s tests -t ."""
import unittest
from datetime import datetime, timezone
from unittest import mock

from radar import main


class QuietHoursTest(unittest.TestCase):
    def at(self, hour):
        cfg = {"timezone": "Europe/Paris", "quiet_hours": {"start": 23, "end": 6}}
        fake = datetime(2026, 10, 7, hour, 30)
        with mock.patch.object(main, "local_now", return_value=fake):
            return main.quiet(cfg)

    def test_night_window_crosses_midnight(self):
        self.assertTrue(self.at(23))
        self.assertTrue(self.at(2))
        self.assertTrue(self.at(5))
        self.assertFalse(self.at(6))
        self.assertFalse(self.at(14))
        self.assertFalse(self.at(22))

    def test_no_quiet_hours_configured(self):
        self.assertFalse(main.quiet({}))


class RhythmTest(unittest.TestCase):
    def test_rhythms(self):
        firm = lambda **kw: dict({"name": "X", "category": "Private Equity", "tier": "3", "source": "workday"}, **kw)
        self.assertEqual(main.rhythm(firm(source="trackr", source_id="UK|Finance|2027|spring-weeks", aggregator=True), set()), "spring")
        self.assertEqual(main.rhythm(firm(source="trackr", source_id="France|Finance|2027|off-cycle-internships", aggregator=True), set()), "normal")
        self.assertEqual(main.rhythm(firm(source="linkedin", aggregator=True), set()), "hourly")
        self.assertEqual(main.rhythm(firm(source="jobteaser", aggregator=True), set()), "2h")
        self.assertEqual(main.rhythm(firm(category="Banque BB"), set()), "spring")
        self.assertEqual(main.rhythm(firm(category="Banque BB", source="oleeo"), set()), "normal")
        self.assertEqual(main.rhythm(firm(name="Blackstone"), {"Blackstone"}), "spring")
        self.assertEqual(main.rhythm(firm(), set()), "normal")

    def test_slots(self):
        t = datetime(2026, 10, 7, 14, 7, tzinfo=timezone.utc)
        self.assertEqual(main.slot("normal", t), main.slot("normal", t.replace(minute=14)))
        self.assertNotEqual(main.slot("normal", t), main.slot("normal", t.replace(minute=15)))
        self.assertEqual(main.slot("hourly", t), main.slot("hourly", t.replace(minute=59)))
        self.assertIsNone(main.slot("spring", t))


class SpringAlarmTest(unittest.TestCase):
    def test_five_notifications_for_a_new_spring(self):
        sent = []
        spring = {"id": "1", "company": "Rothschild & Co", "title": "2027 Spring Insight Programme", "url": "https://x",
                  "tier": "1", "cycle": "Spring / Insight", "level": "A", "region": "London / UK", "category": "Boutique M&A"}
        other = dict(spring, id="2", title="Off-cycle M&A", cycle="Off-cycle")
        with mock.patch.object(main.notify, "send", side_effect=sent.append), mock.patch.object(main, "ALARM_GAP_SEC", 0):
            main.instant({"spring_alarm": 5}, [spring])
            self.assertEqual(len(sent), 5)
            sent.clear()
            main.instant({"spring_alarm": 5}, [other])
            self.assertEqual(len(sent), 1)


if __name__ == "__main__":
    unittest.main()
