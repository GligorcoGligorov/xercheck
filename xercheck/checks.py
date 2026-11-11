"""The three schedule checks.

All checks skip finished activities and summary activities (level of
effort, WBS summary), the same scope DCMA's 14-point assessment uses.

1. Missing links   - an activity with no predecessor or no successor is not
                     tied into the network, so its float and dates can't be
                     trusted. Start milestones may have no predecessor and
                     finish milestones no successor.
                     Also flagged (warning): "dangling" ends, where the only
                     links don't drive the start or the finish. An activity
                     with only an FF predecessor can start any time; one
                     with only an SS successor drives nothing when it ends.
2. Negative float  - total float below zero: the activity is already late
                     against a constraint or deadline.
3. High float      - total float above a threshold (default 44 working
                     days, the DCMA 14-point limit). Often means missing
                     logic rather than real slack.
"""

from __future__ import annotations

from dataclasses import dataclass

from .schedule import Activity, Schedule

DEFAULT_HIGH_FLOAT_DAYS = 44.0

CHECKS = ("missing_links", "negative_float", "high_float")


@dataclass
class Finding:
    check: str
    rule: str
    severity: str  # "error" or "warning"
    activity: Activity
    detail: str


def check_missing_links(s: Schedule) -> list[Finding]:
    out: list[Finding] = []
    for a in s.activities.values():
        if not a.in_scope:
            continue
        if not a.predecessors and a.task_type != "TT_Mile":
            out.append(Finding("missing_links", "no_predecessor", "error", a,
                               "no predecessor"))
        elif a.predecessors and not any(l.link_type in ("PR_FS", "PR_SS")
                                        for l in a.predecessors):
            out.append(Finding("missing_links", "dangling_start", "warning", a,
                               "only FF/SF predecessors, nothing drives its start"))
        if not a.successors and a.task_type != "TT_FinMile":
            out.append(Finding("missing_links", "no_successor", "error", a,
                               "no successor"))
        elif a.successors and not any(l.link_type in ("PR_FS", "PR_FF")
                                      for l in a.successors):
            out.append(Finding("missing_links", "dangling_finish", "warning", a,
                               "only SS/SF successors, its finish drives nothing"))
    return out


def check_negative_float(s: Schedule) -> list[Finding]:
    return [
        Finding("negative_float", "negative_float", "error", a,
                f"total float {a.float_days:g} days")
        for a in s.activities.values()
        if a.in_scope and a.float_days is not None and a.float_days < 0
    ]


def check_high_float(s: Schedule, threshold_days: float = DEFAULT_HIGH_FLOAT_DAYS
                     ) -> list[Finding]:
    return [
        Finding("high_float", "high_float", "warning", a,
                f"total float {a.float_days:g} days (> {threshold_days:g})")
        for a in s.activities.values()
        if a.in_scope and a.float_days is not None and a.float_days > threshold_days
    ]


def run_checks(s: Schedule, high_float_days: float = DEFAULT_HIGH_FLOAT_DAYS
               ) -> list[Finding]:
    return (check_missing_links(s)
            + check_negative_float(s)
            + check_high_float(s, high_float_days))
