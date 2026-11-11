"""Find the driving (critical) path of each project and say whether it holds.

P6 calls an activity critical when total float <= a threshold (usually 0).
That breaks when the project has a finish date later than its early finish:
every activity on the real driving path then carries the same positive
float, and P6 shows no critical path at all.

So instead of "float <= 0", start from the project's finish (the open end
with the lowest float) and walk back through predecessors that carry no
more float than the finish does. If that walk reaches an activity with no
predecessor, the path is continuous from start to finish.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .schedule import Activity, Schedule

EPS = 1e-6


@dataclass
class DrivingPath:
    project: str
    finish: Activity
    float_days: float          # float along the path (the finish's float)
    activities: list[Activity] = field(default_factory=list)
    reaches_start: bool = False
    p6_critical: int = 0       # activities P6 would mark critical (float <= 0)

    @property
    def start(self) -> Activity | None:
        heads = [a for a in self.activities if not a.predecessors]
        return heads[0] if heads else None


def driving_paths(s: Schedule) -> list[DrivingPath]:
    by_project: dict[str, list[Activity]] = {}
    for a in s.activities.values():
        if a.in_scope and a.float_days is not None:
            by_project.setdefault(a.project, []).append(a)

    out = []
    for project, acts in sorted(by_project.items()):
        ends = [a for a in acts if not a.successors]
        if not ends:
            continue
        finish = min(ends, key=lambda a: (a.float_days, -len(a.predecessors)))
        level = finish.float_days + EPS

        seen = {finish.task_id}
        stack = [finish]
        while stack:
            a = stack.pop()
            for link in a.predecessors:
                p = s.activities[link.pred_id]
                if (p.task_id not in seen and p.in_scope and p.float_days is not None
                        and p.float_days <= level):
                    seen.add(p.task_id)
                    stack.append(p)

        path = [s.activities[t] for t in seen]
        out.append(DrivingPath(
            project=project,
            finish=finish,
            float_days=finish.float_days,
            activities=path,
            reaches_start=any(not a.predecessors for a in path),
            p6_critical=sum(1 for a in acts if a.float_days <= EPS),
        ))
    return out


def _days(x: float) -> str:
    return f"{x:g} day" if x == 1 else f"{x:g} days"


def describe(p: DrivingPath) -> str:
    n = len(p.activities)
    if p.reaches_start:
        text = (f"{n:,} activities from {p.start.code} to {p.finish.code}, "
                f"float <= {_days(p.float_days)}")
    else:
        text = (f"breaks: {n:,} activities lead back from {p.finish.code} at "
                f"{_days(p.float_days)} float, but none reaches a start")
    if p.float_days > EPS and p.p6_critical < n:
        text += (f"; P6 marks only {p.p6_critical:,} critical (float <= 0) "
                 "because the finish has float")
    return text
