"""Read a Primavera P6 .xer export into tables, and set aside lines that don't fit.

An XER file is tab-separated text:

    ERMHDR  <version> <export date> ...      header, first line
    %T      TASK                             start of a table
    %F      task_id  proj_id  task_code ...  field names for that table
    %R      1001     2661     A1000     ...  one row, same order as %F
    %E                                       end of file

The reader never stops on a bad line. Every line it can't use becomes an
Issue with the file name and line number, and reading carries on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# P6 writes XER files in the Windows code page of the machine that exported
# them, almost never UTF-8. Try UTF-8 first (strict), then cp1252, then
# latin-1, which decodes any byte and so never fails.
ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")


@dataclass
class Issue:
    """One problem found in a file. Rows behind an "error" are not used."""

    file: str
    line: int | None
    table: str | None
    kind: str
    detail: str
    severity: str = "error"  # "error" = row set aside, "warning" = row kept


@dataclass
class Row:
    line: int
    values: dict[str, str]

    def get(self, name: str, default: str = "") -> str:
        return self.values.get(name, default)


@dataclass
class Table:
    name: str
    line: int
    fields: list[str] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)


@dataclass
class XerFile:
    path: Path
    encoding: str
    header: list[str]
    tables: dict[str, Table]
    issues: list[Issue]
    line_count: int

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def p6_version(self) -> str:
        return self.header[1] if len(self.header) > 1 else "?"

    def rows(self, table: str) -> list[Row]:
        t = self.tables.get(table)
        return t.rows if t else []


class NotAnXerFile(ValueError):
    """Raised when the input is not an XER export at all."""


def _decode(raw: bytes) -> tuple[str, str]:
    for enc in ENCODINGS:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise AssertionError("latin-1 decodes any byte")  # pragma: no cover


def read_xer(path: str | Path) -> XerFile:
    path = Path(path)
    raw = path.read_bytes()
    if not raw.strip():
        raise NotAnXerFile(f"{path.name}: file is empty")
    text, encoding = _decode(raw)
    lines = text.splitlines()
    first = lines[0].split("\t")
    if first[0].strip() != "ERMHDR":
        raise NotAnXerFile(f"{path.name}: first line is not an ERMHDR header")

    issues: list[Issue] = []
    tables: dict[str, Table] = {}
    current: Table | None = None
    ended = False

    def flag(line: int, kind: str, detail: str, severity: str = "error") -> None:
        issues.append(Issue(path.name, line, current.name if current else None,
                            kind, detail, severity))

    for n, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        parts = line.split("\t")
        tag = parts[0]

        if ended:
            flag(n, "data_after_end", "line after the %E end marker")
            continue

        if tag == "%T":
            name = parts[1].strip() if len(parts) > 1 else ""
            if not name:
                current = None
                flag(n, "bad_table", "%T line with no table name")
                continue
            if name in tables:
                # Keep reading into the table we already have, but say so.
                current = tables[name]
                flag(n, "duplicate_table", f"table {name} appears twice", "warning")
                continue
            current = Table(name=name, line=n)
            tables[name] = current

        elif tag == "%F":
            if current is None:
                flag(n, "fields_without_table", "%F line before any %T")
            elif current.fields:
                flag(n, "duplicate_fields", "second %F line for the same table")
            else:
                current.fields = [f.strip() for f in parts[1:]]

        elif tag == "%R":
            if current is None:
                flag(n, "row_without_table", "%R line before any %T")
                continue
            if not current.fields:
                flag(n, "row_without_fields", "%R line before the table's %F line")
                continue
            values = parts[1:]
            expected = len(current.fields)
            if len(values) > expected and not any(v.strip() for v in values[expected:]):
                values = values[:expected]  # trailing empty tabs: harmless
            if len(values) != expected:
                flag(n, "wrong_column_count",
                     f"{len(values)} values, table has {expected} fields")
                continue
            current.rows.append(Row(n, dict(zip(current.fields, values))))

        elif tag == "%E":
            ended = True

        else:
            flag(n, "unknown_line", f"line starts with {tag[:20]!r}, not %T/%F/%R/%E")

    if not ended:
        issues.append(Issue(path.name, None, None, "missing_end",
                            "no %E end marker; the file may be cut off", "warning"))

    return XerFile(path, encoding, first, tables, issues, len(lines))
