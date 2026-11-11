"""Command line: xercheck data/*.xer --out reports"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .checks import DEFAULT_HIGH_FLOAT_DAYS, run_checks
from .parser import NotAnXerFile, read_xer
from .report import Result, console_summary, write_all
from .schedule import build_schedule


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="xercheck",
        description="Check Primavera P6 .xer files for broken rows, missing links, "
                    "negative float and high float.")
    ap.add_argument("files", nargs="+", type=Path, help=".xer files to check")
    ap.add_argument("--out", type=Path, default=Path("reports"),
                    help="folder for report.html, the chart and CSVs (default: reports)")
    ap.add_argument("--high-float-days", type=float, default=DEFAULT_HIGH_FLOAT_DAYS,
                    help="flag total float above this many working days (default: 44)")
    args = ap.parse_args(argv)

    started = time.perf_counter()
    results, failed = [], 0
    for path in args.files:
        try:
            sched = build_schedule(read_xer(path))
        except (OSError, NotAnXerFile) as e:
            print(f"skipped {path}: {e}", file=sys.stderr)
            failed += 1
            continue
        results.append(Result(sched, run_checks(sched, args.high_float_days)))

    if not results:
        return 2
    print(console_summary(results))
    paths = write_all(results, args.out, args.high_float_days)
    print(f"\nreport  {paths['report']}\nchart   {paths['chart']}"
          f"\ndone in {time.perf_counter() - started:.2f}s")
    return 1 if failed else 0


def run() -> None:
    """Console entry point; exits quietly if output is piped into head/less."""
    try:
        sys.exit(main())
    except BrokenPipeError:
        sys.stderr.close()
        sys.exit(0)


if __name__ == "__main__":  # pragma: no cover
    run()
