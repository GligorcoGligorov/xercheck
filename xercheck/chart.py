"""One chart: how total float is spread across activities, file by file.

Pure SVG, no plotting library. Bars are a share of each file's checked
activities, so a 66-activity schedule and a 4,236-activity schedule sit on
the same scale. The two flagged buckets (negative, high) get a shaded band.
"""

from __future__ import annotations

from html import escape

from .schedule import Schedule

# Categorical slots 1-2 of the palette, light and dark steps.
SERIES = [("#2a78d6", "#3987e5"), ("#eb6834", "#d95926")]


def buckets(high_float_days: float) -> list[tuple[str, str]]:
    h = f"{high_float_days:g}"
    return [
        ("neg", "Negative"),
        ("zero", "0 (critical)"),
        ("low", "0–10 d"),
        ("mid", f"10–{h} d"),
        ("high", f"> {h} d"),
        ("none", "Not scheduled"),
    ]


def bucket_of(days: float | None, high_float_days: float) -> str:
    if days is None:
        return "none"
    if days < 0:
        return "neg"
    if days == 0:
        return "zero"
    if days <= 10:
        return "low"
    if days <= high_float_days:
        return "mid"
    return "high"


def float_distribution(s: Schedule, high_float_days: float) -> dict[str, int]:
    counts = {k: 0 for k, _ in buckets(high_float_days)}
    for a in s.activities.values():
        if a.in_scope:
            counts[bucket_of(a.float_days, high_float_days)] += 1
    return counts


def float_chart_svg(schedules: list[Schedule], high_float_days: float) -> str:
    bks = buckets(high_float_days)
    dists = [float_distribution(s, high_float_days) for s in schedules]
    totals = [max(sum(d.values()), 1) for d in dists]
    shares = [[d[k] / t * 100 for k, _ in bks] for d, t in zip(dists, totals)]

    W, H = 760, 390
    left, right, top, bottom = 56, 20, 74, 60
    pw, ph = W - left - right, H - top - bottom
    ymax = max(10, min(100, (int(max(max(r) for r in shares) / 10) + 1) * 10))
    group_w = pw / len(bks)
    n = len(schedules)
    bar_w = min(30, (group_w - 24) / n)
    gap = 2

    def y(v: float) -> float:
        return top + ph - v / ymax * ph

    css_light = "".join(f".s{i}{{fill:{c[0]}}}" for i, c in enumerate(SERIES))
    css_dark = "".join(f".s{i}{{fill:{c[1]}}}" for i, c in enumerate(SERIES))
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'width="{W}" height="{H}" role="img" '
        'aria-labelledby="float-title float-desc" font-family="system-ui,-apple-system,'
        'Segoe UI,Roboto,sans-serif">',
        '<style>'
        '.bg{fill:#fcfcfb}.t1{fill:#0b0b0b}.t2{fill:#52514e}.t3{fill:#7b7a74}'
        '.grid{stroke:#e6e5e0}.axis{stroke:#bdbcb4}.band{fill:#f3f2ee}'
        f'{css_light}'
        '@media (prefers-color-scheme:dark){'
        '.bg{fill:#1a1a19}.t1{fill:#f0efec}.t2{fill:#c3c2b7}.t3{fill:#8f8e86}'
        '.grid{stroke:#2e2e2c}.axis{stroke:#55544f}.band{fill:#232322}'
        f'{css_dark}}}'
        '</style>',
        '<title id="float-title">Total float by activity, share of each schedule</title>',
        f'<desc id="float-desc">Share of checked activities in each float range. '
        f'Ranges below zero and above {high_float_days:g} working days are flagged.</desc>',
        f'<rect class="bg" width="{W}" height="{H}" rx="8"/>',
        f'<text class="t1" x="{left}" y="28" font-size="16" font-weight="600">'
        'Where does the float sit?</text>',
        f'<text class="t2" x="{left}" y="48" font-size="12">Share of checked '
        'activities by total float (working days). Shaded ranges are flagged.</text>',
    ]

    # Shaded bands behind the flagged buckets.
    for i, (k, _) in enumerate(bks):
        if k in ("neg", "high"):
            out.append(f'<rect class="band" x="{left + i * group_w:.1f}" y="{top}" '
                       f'width="{group_w:.1f}" height="{ph}"/>')
            out.append(f'<text class="t3" x="{left + (i + .5) * group_w:.1f}" '
                       f'y="{top + 14}" font-size="10" text-anchor="middle" '
                       'letter-spacing=".06em">FLAGGED</text>')

    # Grid and y labels.
    for v in range(0, ymax + 1, 10 if ymax > 40 else 5):
        out.append(f'<line class="grid" x1="{left}" x2="{W - right}" '
                   f'y1="{y(v):.1f}" y2="{y(v):.1f}"/>')
        out.append(f'<text class="t3" x="{left - 8}" y="{y(v) + 4:.1f}" '
                   f'font-size="11" text-anchor="end">{v}%</text>')

    # Bars: rounded top, square at the baseline.
    for i, (k, label) in enumerate(bks):
        gx = left + i * group_w + (group_w - (n * bar_w + (n - 1) * gap)) / 2
        for j in range(n):
            v, c = shares[j][i], dists[j][k]
            x = gx + j * (bar_w + gap)
            tip = escape(f"{schedules[j].name} · {label}: {c} activities ({v:.1f}%)")
            if c:
                hgt = max(v / ymax * ph, 1.5)
                r = min(4, bar_w / 2, hgt)
                yt, yb = top + ph - hgt, top + ph
                out.append(
                    f'<path class="s{j}" d="M{x:.1f},{yb:.1f}V{yt + r:.1f}'
                    f'Q{x:.1f},{yt:.1f} {x + r:.1f},{yt:.1f}H{x + bar_w - r:.1f}'
                    f'Q{x + bar_w:.1f},{yt:.1f} {x + bar_w:.1f},{yt + r:.1f}'
                    f'V{yb:.1f}Z"><title>{tip}</title></path>')
            # Count over every bar keeps identity off colour alone.
            out.append(f'<text class="t2" x="{x + bar_w / 2:.1f}" '
                       f'y="{y(v) - 5:.1f}" font-size="10" text-anchor="middle">'
                       f'{c:,}</text>')
        out.append(f'<text class="t2" x="{left + (i + .5) * group_w:.1f}" '
                   f'y="{top + ph + 18}" font-size="11.5" text-anchor="middle">'
                   f'{escape(label)}</text>')

    out.append(f'<line class="axis" x1="{left}" x2="{W - right}" '
               f'y1="{top + ph}" y2="{top + ph}"/>')

    # Legend, bottom right.
    lx = W - right
    for j in reversed(range(n)):
        name = escape(f"{schedules[j].name} ({totals[j]:,})")
        lx -= 6.4 * len(name) + 30
        out.append(f'<rect class="s{j}" x="{lx:.0f}" y="{H - 30}" width="10" height="10" rx="2"/>'
                   f'<text class="t2" x="{lx + 15:.0f}" y="{H - 21}" font-size="11.5">{name}</text>')
    out.append("</svg>")
    return "\n".join(out)
