import unittest
from pathlib import Path

from xercheck.critical import driving_paths
from xercheck.parser import read_xer
from xercheck.schedule import build_schedule

ROOT = Path(__file__).parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "planted-defects.xer"


class DrivingPathTests(unittest.TestCase):
    def test_continuous_path_from_start_to_finish(self):
        [p] = driving_paths(build_schedule(read_xer(FIXTURE)))
        self.assertEqual(p.finish.code, "M-FINISH")
        self.assertTrue(p.reaches_start)
        self.assertIn("A8", {a.code for a in p.activities})
        self.assertNotIn("A5", {a.code for a in p.activities})  # 40 days of float

    def test_path_breaks_when_a_predecessor_has_more_float(self):
        s = build_schedule(read_xer(FIXTURE))
        s.activities["101"].float_hours = 80  # A1 now has 10 days of float
        [p] = driving_paths(s)
        self.assertFalse(p.reaches_start)
        self.assertEqual({a.code for a in p.activities}, {"M-FINISH", "A8", "A9"})

    def test_terminal_finish_has_float_so_p6_shows_no_critical_path(self):
        s = build_schedule(read_xer(ROOT / "data" / "terminal-building-airport.xer"))
        [p] = driving_paths(s)
        self.assertEqual((p.finish.code, p.float_days), ("A5800", 1))
        self.assertTrue(p.reaches_start)
        self.assertEqual(len(p.activities), 36)
        self.assertEqual(p.p6_critical, 1)  # only the start milestone


if __name__ == "__main__":
    unittest.main()
