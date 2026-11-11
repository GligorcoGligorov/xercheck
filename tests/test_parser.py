import tempfile
import unittest
from pathlib import Path

from xercheck.parser import NotAnXerFile, read_xer

FIXTURE = Path(__file__).parent / "fixtures" / "planted-defects.xer"


def write(text: str, encoding: str = "utf-8") -> Path:
    f = tempfile.NamedTemporaryFile("wb", suffix=".xer", delete=False)
    f.write(text.encode(encoding))
    f.close()
    return Path(f.name)


HEADER = "ERMHDR\t19.12\t2026-11-12\n"


class ParserTests(unittest.TestCase):
    def test_reads_tables_fields_and_rows(self):
        xer = read_xer(FIXTURE)
        self.assertEqual(xer.p6_version, "19.12")
        self.assertEqual(set(xer.tables), {"PROJECT", "CALENDAR", "TASK", "TASKPRED"})
        self.assertEqual(xer.tables["TASK"].fields[0], "task_id")
        self.assertEqual(xer.rows("PROJECT")[0].get("proj_short_name"), "DEMO")

    def test_handles_windows_line_endings(self):
        # The fixture is written with CRLF, like a real P6 export.
        self.assertIn(b"\r\n", FIXTURE.read_bytes())
        last = read_xer(FIXTURE).rows("TASK")[-1]
        self.assertFalse(any(v.endswith("\r") for v in last.values.values()))

    def test_wrong_column_count_is_set_aside_with_line_number(self):
        xer = read_xer(FIXTURE)
        bad = [i for i in xer.issues if i.kind == "wrong_column_count"]
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0].line, 28)
        self.assertNotIn("114", {r.get("task_id") for r in xer.rows("TASK")})

    def test_unknown_line_is_flagged_and_reading_continues(self):
        xer = read_xer(FIXTURE)
        self.assertTrue(any(i.kind == "unknown_line" for i in xer.issues))
        self.assertGreater(len(xer.rows("TASKPRED")), 0)  # table after the junk

    def test_trailing_empty_tabs_are_harmless(self):
        p = write(HEADER + "%T\tX\n%F\ta\tb\n%R\t1\t2\t\t\n%E\n")
        xer = read_xer(p)
        self.assertEqual(xer.issues, [])
        self.assertEqual(xer.rows("X")[0].values, {"a": "1", "b": "2"})

    def test_row_before_fields_and_missing_end(self):
        p = write(HEADER + "%T\tX\n%R\t1\n%F\ta\n%R\t2\n")
        kinds = {i.kind for i in read_xer(p).issues}
        self.assertEqual(kinds, {"row_without_fields", "missing_end"})

    def test_data_after_end_marker(self):
        p = write(HEADER + "%T\tX\n%F\ta\n%E\n%R\t1\n")
        self.assertEqual([i.kind for i in read_xer(p).issues], ["data_after_end"])

    def test_windows_1252_text_is_decoded(self):
        p = write(HEADER + "%T\tX\n%F\tname\n%R\tBéton – phase 2\n%E\n", "cp1252")
        xer = read_xer(p)
        self.assertEqual(xer.encoding, "cp1252")
        self.assertEqual(xer.rows("X")[0].get("name"), "Béton – phase 2")

    def test_rejects_files_that_are_not_xer(self):
        for text in ("", "hello\tworld\n", "%T\tTASK\n"):
            with self.subTest(text=text), self.assertRaises(NotAnXerFile):
                read_xer(write(text))


if __name__ == "__main__":
    unittest.main()
