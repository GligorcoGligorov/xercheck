"""Turn the raw TASK / TASKPRED / CALENDAR / PROJECT tables into a schedule.

Rows that can't be trusted (no id, duplicate id, a float that isn't a
number, a link to an activity that doesn't exist) are set aside here as
Issues, so the checks only ever see clean data.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .parser import Issue, XerFile

DEFAULT_HOURS_PER_DAY = 8.0

# P6 activity types. TT_Mile is a start milestone, TT_FinMile a finish milestone.
KNOWN_TASK_TYPES = {"TT_Task", "TT_Rsrc", "TT_Mile", "TT_FinMile", "TT_LOE", "TT_WBS"}
KNOWN_LINK_TYPES = {"PR_FS", "PR_SS", "PR_FF", "PR_SF"}
REQUIRED_TABLES = ("TASK", "TASKPRED")


@dataclass
class Activity:
    task_id: str
    code: str
    name: str
    project: str
    task_type: str
    status: str
    float_hours: float | None  # None = P6 has no float for it (not scheduled)
    hours_per_day: float
    line: int
    predecessors: list["Link"] = field(default_factory=list)
    successors: list["Link"] = field(default_factory=list)

    @property
    def float_days(self) -> float | None:
        if self.float_hours is None:
            return None
        return self.float_hours / self.hours_per_day

    @property
    def is_complete(self) -> bool:
        return self.status == "TK_Complete"

    @property
    def is_summary(self) -> bool:
        """Level of effort and WBS summary activities have no logic of their own."""
        return self.task_type in ("TT_LOE", "TT_WBS")

    @property
    def in_scope(self) -> bool:
        """Activities the checks apply to: not finished, not a summary."""
        return not self.is_complete and not self.is_summary


@dataclass
class Link:
    pred_id: str
    succ_id: str
    link_type: str
    line: int


@dataclass
class Schedule:
    file: XerFile
    activities: dict[str, Activity]
    links: list[Link]
    projects: dict[str, str]  # proj_id -> short name
    issues: list[Issue]

    @property
    def name(self) -> str:
        return self.file.name


def _number(text: str) -> float | None:
    text = text.strip()
    if not text:
        return None
    return float(text)  # raises ValueError on junk


def build_schedule(xer: XerFile) -> Schedule:
    issues = list(xer.issues)

    def flag(line, table, kind, detail, severity="error"):
        issues.append(Issue(xer.name, line, table, kind, detail, severity))

    for t in REQUIRED_TABLES:
        if t not in xer.tables:
            flag(None, t, "missing_table", f"no {t} table in the file")

    projects = {r.get("proj_id"): r.get("proj_short_name") or r.get("proj_id")
                for r in xer.rows("PROJECT")}

    hours_per_day: dict[str, float] = {}
    for r in xer.rows("CALENDAR"):
        try:
            h = _number(r.get("day_hr_cnt"))
        except ValueError:
            h = None
        if h and h > 0:
            hours_per_day[r.get("clndr_id")] = h

    activities: dict[str, Activity] = {}
    for r in xer.rows("TASK"):
        tid = r.get("task_id").strip()
        if not tid:
            flag(r.line, "TASK", "missing_id", "activity row has no task_id")
            continue
        if tid in activities:
            flag(r.line, "TASK", "duplicate_id",
                 f"task_id {tid} already used on line {activities[tid].line}")
            continue
        try:
            float_hours = _number(r.get("total_float_hr_cnt"))
        except ValueError:
            flag(r.line, "TASK", "bad_number",
                 f"total float {r.get('total_float_hr_cnt')!r} is not a number")
            continue

        task_type = r.get("task_type")
        if task_type not in KNOWN_TASK_TYPES:
            flag(r.line, "TASK", "unknown_task_type",
                 f"task_type {task_type!r} is not a P6 activity type", "warning")

        status = r.get("status_code")
        if float_hours is None and status != "TK_Complete":
            flag(r.line, "TASK", "no_float",
                 f"{r.get('task_code')}: no total float, so P6 has not scheduled it",
                 "warning")

        cal = r.get("clndr_id")
        hpd = hours_per_day.get(cal, DEFAULT_HOURS_PER_DAY)

        activities[tid] = Activity(
            task_id=tid,
            code=r.get("task_code") or tid,
            name=r.get("task_name"),
            project=projects.get(r.get("proj_id"), r.get("proj_id")),
            task_type=task_type,
            status=status,
            float_hours=float_hours,
            hours_per_day=hpd,
            line=r.line,
        )

    links: list[Link] = []
    seen: dict[tuple[str, str, str], int] = {}
    for r in xer.rows("TASKPRED"):
        succ, pred = r.get("task_id").strip(), r.get("pred_task_id").strip()
        kind = r.get("pred_type")
        if succ not in activities or pred not in activities:
            missing = [x for x in (pred, succ) if x not in activities]
            flag(r.line, "TASKPRED", "unknown_activity",
                 f"link points to task_id {', '.join(missing) or '(blank)'} "
                 "that is not in TASK")
            continue
        if succ == pred:
            flag(r.line, "TASKPRED", "self_link",
                 f"{activities[succ].code} is linked to itself")
            continue
        if kind not in KNOWN_LINK_TYPES:
            flag(r.line, "TASKPRED", "unknown_link_type",
                 f"pred_type {kind!r} is not FS/SS/FF/SF", "warning")
        key = (pred, succ, kind)
        if key in seen:
            flag(r.line, "TASKPRED", "duplicate_link",
                 f"{activities[pred].code} -> {activities[succ].code} "
                 f"already on line {seen[key]}", "warning")
            continue
        seen[key] = r.line
        link = Link(pred, succ, kind, r.line)
        links.append(link)
        activities[pred].successors.append(link)
        activities[succ].predecessors.append(link)

    issues.sort(key=lambda i: (i.line is None, i.line or 0))
    return Schedule(xer, activities, links, projects, issues)
