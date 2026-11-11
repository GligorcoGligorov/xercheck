import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from xercheck.cli import main

ROOT = Path(__file__).parent.parent


class CliTests(unittest.TestCase):
    def test_writes_report_chart_csvs_and_summary(self):
        out = Path(tempfile.mkdtemp())
        with redirect_stdout(StringIO()) as buf:
            code = main([str(ROOT / "tests/fixtures/planted-defects.xer"),
                         "--out", str(out)])
        self.assertEqual(code, 0)
        self.assertIn("Negative float", buf.getvalue())
        for name in ("report.html", "float-chart.svg", "summary.json",
                     "planted-defects/findings.csv", "planted-defects/row-issues.csv"):
            self.assertTrue((out / name).exists(), name)
        summary = json.loads((out / "summary.json").read_text())
        self.assertEqual(summary[0]["rows_set_aside"], 7)
        self.assertTrue((out / "float-chart.svg").read_text().startswith("<svg"))

    def test_bad_input_is_skipped_not_fatal(self):
        bad = Path(tempfile.mkdtemp()) / "notes.xer"
        bad.write_text("not a schedule")
        out = Path(tempfile.mkdtemp())
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()) as err:
            code = main([str(bad), str(ROOT / "tests/fixtures/planted-defects.xer"),
                         "--out", str(out)])
        self.assertEqual(code, 1)
        self.assertIn("not an ERMHDR header", err.getvalue())
        self.assertTrue((out / "report.html").exists())


if __name__ == "__main__":
    unittest.main()
