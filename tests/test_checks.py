import unittest
from collections import Counter
from pathlib import Path

from xercheck.checks import check_high_float, run_checks
from xercheck.parser import read_xer
from xercheck.schedule import build_schedule

FIXTURE = Path(__file__).parent / "fixtures" / "planted-defects.xer"


def codes(findings, rule=None):
    return {f.activity.code for f in findings if rule is None or f.rule == rule}


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.s = build_schedule(read_xer(FIXTURE))
        self.kinds = Counter(i.kind for i in self.s.issues)

    def test_bad_task_rows_are_set_aside(self):
        for kind in ("duplicate_id", "missing_id", "bad_number"):
            self.assertEqual(self.kinds[kind], 1, kind)
        self.assertNotIn("BAD", {a.code for a in self.s.activities.values()})
        self.assertEqual(self.s.activities["101"].name, "Linked fine")  # first one wins

    def test_bad_links_are_set_aside(self):
        self.assertEqual(self.kinds["unknown_activity"], 1)
        self.assertEqual(self.kinds["self_link"], 1)
        self.assertEqual(self.kinds["duplicate_link"], 1)
        self.assertEqual(len(self.s.links), 14)

    def test_unscheduled_activity_is_kept_with_a_warning(self):
        self.assertEqual(self.kinds["no_float"], 1)
        self.assertIsNone(self.s.activities["112"].float_days)

    def test_float_uses_each_activity_calendar(self):
        self.assertEqual(self.s.activities["103"].float_days, 50)  # 400 h / 8
        self.assertEqual(self.s.activities["104"].float_days, 45)  # 450 h / 10

    def test_missing_table_is_reported(self):
        xer = read_xer(FIXTURE)
        del xer.tables["TASKPRED"]
        kinds = {i.kind for i in build_schedule(xer).issues}
        self.assertIn("missing_table", kinds)


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.f = run_checks(build_schedule(read_xer(FIXTURE)))

    def test_missing_links(self):
        self.assertEqual(codes(self.f, "no_predecessor"), {"A6"})
        self.assertEqual(codes(self.f, "no_successor"), {"A7"})

    def test_dangling_links(self):
        self.assertEqual(codes(self.f, "dangling_start"), {"A8"})
        self.assertEqual(codes(self.f, "dangling_finish"), {"A9"})

    def test_milestones_complete_and_loe_are_not_flagged(self):
        flagged = codes(self.f)
        for code in ("M-START", "M-FINISH", "DONE", "LOE"):
            self.assertNotIn(code, flagged)

    def test_negative_float(self):
        self.assertEqual(codes(self.f, "negative_float"), {"A2"})

    def test_high_float_threshold_is_exclusive(self):
        self.assertEqual(codes(self.f, "high_float"), {"A3", "A4"})  # A5 is 40 days

    def test_high_float_threshold_is_configurable(self):
        s = build_schedule(read_xer(FIXTURE))
        self.assertEqual(codes(check_high_float(s, 39)), {"A3", "A4", "A5"})


class RealFileTests(unittest.TestCase):
    """The two public exports in data/, pinned so a parser change can't drift."""

    DATA = Path(__file__).parent.parent / "data"

    def test_terminal_building(self):
        s = build_schedule(read_xer(self.DATA / "terminal-building-airport.xer"))
        f = run_checks(s)
        self.assertEqual((len(s.activities), len(s.links)), (66, 84))
        self.assertEqual([i for i in s.issues if i.severity == "error"], [])
        self.assertEqual(Counter(x.rule for x in f),
                         Counter(dangling_finish=11, high_float=10))

    def test_hotel_project(self):
        s = build_schedule(read_xer(self.DATA / "hotel-project.xer"))
        f = run_checks(s)
        self.assertEqual((len(s.activities), len(s.links)), (4236, 7586))
        self.assertEqual(s.file.encoding, "cp1252")
        rules = Counter(x.rule for x in f)
        self.assertEqual((rules["no_predecessor"], rules["no_successor"]), (20, 25))
        self.assertEqual(rules["high_float"], 2263)
        self.assertEqual(rules["negative_float"], 0)


if __name__ == "__main__":
    unittest.main()
