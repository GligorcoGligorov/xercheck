"""Write the results: console summary, CSV per file, summary.json, report.html."""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from html import escape
from pathlib import Path

from .chart import float_chart_svg, float_distribution
from .checks import CHECKS, Finding
from .critical import DrivingPath, describe, driving_paths
from .schedule import Schedule

CHECK_TITLES = {
    "missing_links": "Missing links",
    "negative_float": "Negative float",
    "high_float": "High float",
}


@dataclass
class Result:
    schedule: Schedule
    findings: list[Finding]

    @property
    def paths(self) -> list[DrivingPath]:
        return driving_paths(self.schedule)

    @property
    def errors(self):
        return [i for i in self.schedule.issues if i.severity == "error"]

    @property
    def warnings(self):
        return [i for i in self.schedule.issues if i.severity == "warning"]

    @property
    def checked(self) -> int:
        return sum(1 for a in self.schedule.activities.values() if a.in_scope)

    def by_check(self, check: str) -> list[Finding]:
        return [f for f in self.findings if f.check == check]

    def count(self, check: str, severity: str) -> int:
        return sum(1 for f in self.by_check(check) if f.severity == severity)

    def high_float_with_logic_gap(self) -> tuple[int, int]:
        """How many high-float activities also have a missing or dangling link.

        High float that comes with a logic gap is usually not real slack: the
        activity just isn't tied to anything that would hold it back.
        """
        gaps = {f.activity.task_id for f in self.by_check("missing_links")}
        high = {f.activity.task_id for f in self.by_check("high_float")}
        return len(high & gaps), len(high)

    def summary(self, high_float_days: float) -> dict:
        s = self.schedule
        flagged = {f.activity.task_id for f in self.findings if f.severity == "error"}
        return {
            "file": s.name,
            "p6_version": s.file.p6_version,
            "encoding": s.file.encoding,
            "projects": sorted(set(s.projects.values())),
            "activities": len(s.activities),
            "checked_activities": self.checked,
            "relationships": len(s.links),
            "rows_set_aside": len(self.errors),
            "row_warnings": len(self.warnings),
            "row_issues_by_kind": dict(Counter(i.kind for i in s.issues)),
            "checks": {
                c: {
                    "count": len(self.by_check(c)),
                    "by_rule": dict(Counter(f.rule for f in self.by_check(c))),
                }
                for c in CHECKS
            },
            "activities_with_errors": len(flagged),
            "high_float_with_logic_gap": self.high_float_with_logic_gap()[0],
            "driving_paths": [
                {"project": p.project, "finish": p.finish.code,
                 "float_days": p.float_days, "activities": len(p.activities),
                 "reaches_start": p.reaches_start, "p6_critical": p.p6_critical}
                for p in self.paths
            ],
            "float_distribution": float_distribution(s, high_float_days),
            "high_float_days": high_float_days,
        }


# ---------------------------------------------------------------- console

def console_summary(results: list[Result]) -> str:
    lines = []
    for r in results:
        s = r.schedule
        lines.append(f"\n{s.name}  (P6 {s.file.p6_version}, {s.file.encoding}, "
                     f"{len(s.activities):,} activities, {len(s.links):,} links)")
        lines.append(f"  rows set aside      {len(r.errors):>6,}"
                     + (f"   warnings {len(r.warnings):,}" if r.warnings else ""))
        for c in CHECKS:
            fs = r.by_check(c)
            rules = Counter(f.rule for f in fs)
            detail = ", ".join(f"{k.replace('_', ' ')} {v:,}" for k, v in rules.items())
            if c == "missing_links":
                n, extra = r.count(c, "error"), f"+{r.count(c, 'warning'):,} dangling"
            else:
                n, extra = len(fs), f"{len(fs) / max(r.checked, 1):.1%}"
            lines.append(f"  {CHECK_TITLES[c]:<18}{n:>7,}  {extra:<16}{detail}")
        for p in r.paths:
            lines.append(f"  Driving path {p.project:<8} {describe(p)}")
        both, high = r.high_float_with_logic_gap()
        if both:
            lines.append(f"  -> {both:,} of {high:,} high-float activities also have a "
                         "missing or dangling link")
    return "\n".join(lines)


# ---------------------------------------------------------------- files

def write_csvs(r: Result, folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / "findings.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["check", "rule", "severity", "project", "activity_id",
                    "activity_name", "task_type", "total_float_days", "detail",
                    "xer_line"])
        for f in r.findings:
            a = f.activity
            w.writerow([f.check, f.rule, f.severity, a.project, a.code, a.name,
                        a.task_type, "" if a.float_days is None else f"{a.float_days:g}",
                        f.detail, a.line])
    with open(folder / "row-issues.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["severity", "kind", "table", "xer_line", "detail"])
        for i in r.schedule.issues:
            w.writerow([i.severity, i.kind, i.table or "", i.line or "", i.detail])


def write_all(results: list[Result], out: Path, high_float_days: float) -> dict[str, Path]:
    out.mkdir(parents=True, exist_ok=True)
    for r in results:
        write_csvs(r, out / Path(r.schedule.name).stem)
    svg = float_chart_svg([r.schedule for r in results], high_float_days)
    (out / "float-chart.svg").write_text(svg, encoding="utf-8")
    summary = [r.summary(high_float_days) for r in results]
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out / "report.html").write_text(html_report(results, svg, high_float_days),
                                     encoding="utf-8")
    return {"report": out / "report.html", "chart": out / "float-chart.svg",
            "summary": out / "summary.json"}


# ---------------------------------------------------------------- html

def _findings_table(fs: list[Finding], limit: int = 25) -> str:
    if not fs:
        return '<p class="none">None found.</p>'
    order = {"error": 0, "warning": 1}
    fs = sorted(fs, key=lambda f: (order[f.severity],
                                   -(abs(f.activity.float_days or 0))))
    rows = "".join(
        f"<tr><td><span class='sev {f.severity}'>{f.severity}</span></td>"
        f"<td>{escape(f.activity.project)}</td><td class='mono'>{escape(f.activity.code)}</td>"
        f"<td>{escape(f.activity.name)}</td><td>{escape(f.detail)}</td>"
        f"<td class='num'>{f.activity.line}</td></tr>"
        for f in fs[:limit])
    more = (f"<p class='more'>Showing {limit} of {len(fs):,}. "
            "The full list is in the CSV.</p>" if len(fs) > limit else "")
    return ("<table><thead><tr><th>Severity</th><th>Project</th><th>Activity</th>"
            "<th>Name</th><th>Why</th><th class='num'>Line</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>{more}")


def _issues_table(r: Result) -> str:
    issues = r.schedule.issues
    if not issues:
        return '<p class="none">Every row parsed and passed validation.</p>'
    rows = "".join(
        f"<tr><td><span class='sev {i.severity}'>{i.severity}</span></td>"
        f"<td class='mono'>{escape(i.kind)}</td><td>{escape(i.table or '')}</td>"
        f"<td>{escape(i.detail)}</td><td class='num'>{i.line or ''}</td></tr>"
        for i in issues[:25])
    more = f"<p class='more'>Showing 25 of {len(issues):,}.</p>" if len(issues) > 25 else ""
    return ("<table><thead><tr><th>Severity</th><th>Kind</th><th>Table</th>"
            "<th>Detail</th><th class='num'>Line</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>{more}")


def _insight(r: Result) -> str:
    out = []
    for p in r.paths:
        out.append(f"<p class='insight'><b>Driving path, {escape(p.project)}:</b> "
                   f"{escape(describe(p))}.</p>")
    both, high = r.high_float_with_logic_gap()
    if both:
        out.append(f"<p class='insight'><b>{both:,} of {high:,}</b> high-float "
                   "activities also have a missing or dangling link. That float is "
                   "more likely a logic gap than real slack.</p>")
    return "".join(out)


def html_report(results: list[Result], svg: str, high_float_days: float) -> str:
    cards, sections = [], []
    for r in results:
        s = r.schedule
        stem = Path(s.name).stem
        stats = [
            ("Activities", f"{len(s.activities):,}"),
            ("Links", f"{len(s.links):,}"),
            ("Rows set aside", f"{len(r.errors):,}"),
            ("Missing links", f"{r.count('missing_links', 'error'):,}",
             f"+{r.count('missing_links', 'warning'):,} dangling"),
            ("Negative float", f"{len(r.by_check('negative_float')):,}"),
            ("High float", f"{len(r.by_check('high_float')):,}",
             f"{len(r.by_check('high_float')) / max(r.checked, 1):.0%} of checked"),
        ]
        cards.append(
            f"<div class='card'><h3>{escape(s.name)}</h3>"
            f"<p class='meta'>P6 {escape(s.file.p6_version)} · {escape(s.file.encoding)} · "
            f"{escape(', '.join(sorted(set(s.projects.values()))))}</p><dl>"
            + "".join(f"<div><dt>{st[0]}</dt><dd>{st[1]}</dd>"
                      + (f"<small>{st[2]}</small>" if len(st) > 2 else "") + "</div>"
                      for st in stats)
            + "</dl></div>")
        body = [f"<section><h2>{escape(s.name)}</h2>",
                f"<p class='meta'>{r.checked:,} activities checked (not complete, not LOE/WBS "
                f"summary). Files: <a href='{stem}/findings.csv'>findings.csv</a> · "
                f"<a href='{stem}/row-issues.csv'>row-issues.csv</a></p>",
                _insight(r),
                "<h4>Broken rows</h4>", _issues_table(r)]
        for c in CHECKS:
            e, w = r.count(c, "error"), r.count(c, "warning")
            parts = [f"{e:,} error{'s' * (e != 1)}"] if e or not w else []
            parts += [f"{w:,} warning{'s' * (w != 1)}"] if w else []
            body += [f"<h4>{CHECK_TITLES[c]} <span class='count'>"
                     f"{' · '.join(parts)}</span></h4>",
                     _findings_table(r.by_check(c))]
        body.append("</section>")
        sections.append("".join(body))

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>XER schedule check</title>
<style>
:root{{color-scheme:light;--bg:#fcfcfb;--card:#fff;--line:#e6e5e0;--t1:#0b0b0b;
--t2:#52514e;--t3:#7b7a74;--err:#c03535;--errbg:#fbeaea;--warn:#8a5a00;--warnbg:#fdf3dc}}
@media (prefers-color-scheme:dark){{:root{{color-scheme:dark;--bg:#1a1a19;--card:#212120;
--line:#2e2e2c;--t1:#f0efec;--t2:#c3c2b7;--t3:#8f8e86;--err:#ff8a8a;--errbg:#3a2020;
--warn:#f1c45a;--warnbg:#3a3020}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--t1);
font:14px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
main{{max-width:1080px;margin:0 auto;padding:32px 24px 64px}}
h1{{font-size:24px;margin:0 0 4px}}h2{{font-size:19px;margin:40px 0 4px}}
h3{{font-size:14px;margin:0}}h4{{font-size:14px;margin:22px 0 8px}}
.meta,.more,.none{{color:var(--t2);margin:4px 0}}.none{{color:var(--t3)}}
a{{color:inherit}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px;margin:24px 0}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}}
dl{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:12px 0 0}}
dt{{color:var(--t3);font-size:12px}}dd{{margin:0;font-size:20px;font-weight:600;
font-variant-numeric:tabular-nums}}
.chart{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px;
overflow-x:auto}}.chart svg{{max-width:100%;height:auto;display:block;margin:auto}}
table{{width:100%;border-collapse:collapse;background:var(--card);font-size:13px}}
th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}}
th{{color:var(--t3);font-weight:500;font-size:12px}}
.num{{text-align:right;font-variant-numeric:tabular-nums}}
.mono{{font-family:ui-monospace,Menlo,monospace;font-size:12px}}
.sev{{font-size:11px;padding:1px 6px;border-radius:4px;font-weight:600}}
.sev.error{{color:var(--err);background:var(--errbg)}}
.sev.warning{{color:var(--warn);background:var(--warnbg)}}
.count{{color:var(--t3);font-weight:400}}
small{{color:var(--t3);font-size:12px}}
.insight{{background:var(--card);border-left:3px solid var(--t3);padding:8px 12px;margin:14px 0}}
</style></head><body><main>
<h1>XER schedule check</h1>
<p class="meta">Broken rows, missing links, negative float and high float
(&gt; {high_float_days:g} working days) for {len(results)} Primavera P6 exports.</p>
<div class="cards">{''.join(cards)}</div>
<div class="chart">{svg}</div>
{''.join(sections)}
</main></body></html>
"""
